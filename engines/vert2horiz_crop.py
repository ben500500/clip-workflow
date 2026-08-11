#!/usr/bin/env python3
"""
vert2horiz_crop.py — 竖屏转横屏 + 人脸跟踪裁切

功能：
  将竖屏视频（9:16）转为横屏（16:9），支持两种裁切模式：
  - 固定裁切：取画面固定区域（适合人物居中场景，速度快）
  - 动态跟踪：逐帧检测人脸，动态调整裁切窗口（适合人物走动场景）

原理：
  1. 固定模式：先抽样检测视频中人脸的平均位置，以人脸为锚点定位裁切窗口
     （保证面部完整），检测不到人脸时回退到顶部保护更好的默认位置。
  2. 动态模式：逐帧检测人脸 → 以「人脸顶部 + 头顶预留 margin」为锚生成裁切
     窗口（确保额头/头发完整入镜）→ 平滑处理 → 输出。
  3. 最终用 ffmpeg 执行裁切 + 缩放。

  人脸检测器优先使用 YuNet（cv2.FaceDetectorYN，OpenCV≥4.5.1，检测稳定、
  支持多脸），OpenCV 5.0 已移除 Haar cascade，故 Haar 仅作降级 fallback。

用法：
  # 固定裁切（默认，快速）
  python vert2horiz_crop.py input.mp4 output.mp4

  # 动态跟踪（慢但准）
  python vert2horiz_crop.py input.mp4 output.mp4 --mode dynamic

  # 指定裁切高度比例（0.0-1.0，默认 0.5625 = 9/16）
  python vert2horiz_crop.py input.mp4 output.mp4 --ratio 0.6

  # 指定输出分辨率（默认 1280x720）
  python vert2horiz_crop.py input.mp4 output.mp4 --output-size 1280x720

依赖：
  - OpenCV: pip install opencv-python (≥4.5.1 推荐)
  - FFmpeg: 系统安装

作者: Ben + AI协作
日期: 2026-08-06 (2026-08-11 修复面部完整性)
"""

import cv2
import json
import subprocess
import numpy as np
from pathlib import Path
import argparse
import sys
import tempfile
import os

# 人脸框顶部上方需额外预留的头部空间（头发/前额），占人脸框高度的比例。
# 人脸检测框通常刚好框住面部，头顶的头发/发际线上方需要额外 margin，
# 否则直接把窗口顶部对齐人脸框会把额头/头发裁掉。
HEAD_MARGIN_RATIO = 0.35
# 固定裁切在检测不到人脸时采用的顶部保护偏移（画面高度的比例）。
# 竖屏人物素材中头部通常位于画面上部 1/3 以内，窗口顶部需尽量靠上以保住头顶。
FIXED_FALLBACK_TOP_RATIO = 0.12
# 抽样检测帧数上限（固定模式用于定位人脸平均位置）。
FIXED_SAMPLE_MAX = 24


def get_video_info(path):
    """获取视频宽高和帧率"""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {path}")

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    return w, h, fps, total


class FaceDetector:
    """人脸检测器封装：优先 YuNet（OpenCV 4.5.1+），Haar 作为降级备选。

    detect(frame) -> list[(x, y, w, h, confidence)]，坐标为画面像素。
    返回空列表表示本帧未检测到人脸。
    """

    def __init__(self):
        self._yunet = None
        self._haar = None
        self._width = None
        self._height = None

    def _ensure_yunet(self, w, h):
        if self._yunet is None:
            try:
                model = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "yunet.onnx"
                )
                if not os.path.exists(model):
                    model = cv2.samples.findFile("yunet.onnx")
                self._yunet = cv2.FaceDetectorYN_create(model, "", (w, h))
            except Exception:
                self._yunet = False
        if self._yunet and (self._width != w or self._height != h):
            self._yunet.setInputSize((w, h))
            self._width, self._height = w, h
        return self._yunet

    def _ensure_haar(self):
        if self._haar is None:
            try:
                self._haar = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception:
                self._haar = False
        return self._haar

    def detect(self, frame):
        h, w = frame.shape[:2]
        yunet = self._ensure_yunet(w, h)
        if yunet:
            try:
                _, faces = yunet.detect(frame)
                if faces is not None and len(faces):
                    out = []
                    for f in faces:
                        x, y, fw, fh = f[:4]
                        # YuNet 前 14 列为 bbox + 关键点，最后一列为置信度
                        score = float(f[-1]) if len(f) >= 15 else 1.0
                        if fw > 0 and fh > 0:
                            out.append((int(x), int(y), int(fw), int(fh), score))
                    if out:
                        return out
            except Exception:
                pass  # 降级到 Haar

        haar = self._ensure_haar()
        if haar:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                rects = haar.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
                )
                return [(int(x), int(y), int(w2), int(h2), 1.0)
                        for (x, y, w2, h2) in rects]
            except Exception:
                pass
        return []


def sample_avg_face(detector, video_path, src_w, src_h, max_frames=FIXED_SAMPLE_MAX):
    """抽样若干帧，返回主体人脸框的中位数，用于固定裁切定位。

    使用中位数而非均值，避免个别帧被背景路人/误检拉偏主体位置。
    返回 (avg_fx, avg_fy, avg_fw, avg_fh) 或 None（始终未检测到人脸）。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total = max(total, 1)
    # 均匀采样，最多 max_frames 帧
    step = max(1, total // max_frames)
    bboxes = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % step == 0:
            faces = detector.detect(frame)
            main = pick_main_face(faces)
            if main:
                bboxes.append(main[:4])
        idx += 1
        if len(bboxes) >= max_frames:
            break
    cap.release()

    if not bboxes:
        return None
    arr = np.array(bboxes, dtype=np.float64)
    avg = np.median(arr, axis=0)
    return (int(avg[0]), int(avg[1]), int(avg[2]), int(avg[3]))


def pick_main_face(faces):
    """从多个检测到的人脸中选择主体人脸。

    评分 = 面积 x 置信度 x 位置偏好。
    - 面积最大通常代表离镜头最近、最清晰的主角；
    - 位置偏好：竖屏人物素材中主体/讲述者通常位于画面上部，
      对同样大小的多个人脸，优先选择更靠上（y 更小）的那个，
      避免被画面下方/边角的背景路人抢占主体。
    返回单个人脸 (x, y, w, h, confidence)，无可用人脸返回 None。
    """
    if not faces:
        return None

    def score(f):
        x, y, w, h, conf = f
        area = w * h
        # 位置权重：y 越小（越靠上）权重越大。归一化到 0.5~1.0。
        pos = max(0.5, 1.0 - y / 2000.0)
        return area * max(conf, 0.0) * pos

    best = max(faces, key=score)
    return best


def compute_crop_y_keep_face(face_box, src_h, crop_h):
    """根据人脸框计算能保证「面部完整 + 头顶 margin」的裁切窗口顶部 y。

    face_box: (fx, fy, fw, fh)
    约束：
      - 窗口顶部尽量在人脸顶部上方留 HEAD_MARGIN_RATIO*fh 的头部空间
      - 人脸底部必须在窗口内（fy+fh <= crop_y+crop_h）
      - crop_y ∈ [0, src_h-crop_h]
    """
    fx, fy, fw, fh = face_box
    top_margin = int(fh * HEAD_MARGIN_RATIO)

    # 期望窗口顶部 = 人脸顶部上方留 margin
    crop_y = fy - top_margin
    # 但不能为了留 margin 而把人脸底部挤出窗口
    min_y_for_face = fy + fh - crop_h  # 满足人脸底部在窗口内的最小 crop_y
    crop_y = max(crop_y, min_y_for_face)
    # 边界约束
    crop_y = max(0, min(src_h - crop_h, crop_y))
    return int(crop_y)


def generate_fixed_crop_params(detector, video_path, src_w, src_h, crop_ratio=9 / 16):
    """
    生成固定裁切参数（智能定位人脸，保证面部完整）。

    Args:
        detector: FaceDetector 实例
        video_path: 源视频路径
        src_w: 源视频宽度
        src_h: 源视频高度
        crop_ratio: 裁切高度比例（默认 9/16 = 0.5625）

    Returns:
        dict: {crop_w, crop_h, crop_x, crop_y}
    """
    crop_w = src_w
    crop_h = int(src_w * crop_ratio)

    # 若裁切高度大于源高度，反过来
    if crop_h > src_h:
        crop_h = src_h
        crop_w = int(src_h / crop_ratio)

    # 智能定位：抽样检测主体人脸，以其为锚保证面部完整
    avg_face = sample_avg_face(detector, video_path, src_w, src_h)
    if avg_face is not None:
        crop_y = compute_crop_y_keep_face(avg_face, src_h, crop_h)
    else:
        # 未检测到人脸：回退到顶部保护更好的默认位置（上移，保住头顶）
        crop_y = int(src_h * FIXED_FALLBACK_TOP_RATIO)

    crop_y = max(0, min(src_h - crop_h, crop_y))
    crop_x = (src_w - crop_w) // 2

    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "crop_x": crop_x,
        "crop_y": crop_y,
    }


def analyze_faces(video_path, detect_interval=2, smooth_window=15, detector=None):
    """
    逐帧分析人脸位置（动态模式用）。

    Args:
        video_path: 视频路径
        detect_interval: 每隔 N 帧检测一次（减少计算量）
        smooth_window: 平滑窗口大小
        detector: 可选 FaceDetector 实例

    Returns:
        faces: [主体人脸 bbox (x,y,w,h) 或 None] 每帧一个
        positions: [主体人脸中心 (cx, cy)] 每帧一个（兼容旧接口）
    """
    print("开始人脸分析...")

    if detector is None:
        detector = FaceDetector()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_frames = max(total_frames, 1)
    faces = []
    positions = []
    frame_idx = 0
    last_face = None  # (x,y,w,h) 上一帧主体人脸，用于未检测到时保持

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 每隔 N 帧检测一次
        if frame_idx % detect_interval == 0:
            detected = detector.detect(frame)
            main = pick_main_face(detected)
            if main is not None:
                last_face = main[:4]
            face = last_face
        else:
            face = last_face

        if face is not None:
            x, y, w, h = face
            faces.append((x, y, w, h))
            positions.append((x + w // 2, y + h // 2))
        else:
            # 未检测到人脸：回退到画面中心
            fw, fh = frame.shape[1], frame.shape[0]
            faces.append(None)
            positions.append((fw // 2, fh // 2))

        frame_idx += 1

        # 进度显示
        if frame_idx % 100 == 0:
            progress = frame_idx / total_frames * 100
            print(f"  分析进度: {frame_idx}/{total_frames} ({progress:.1f}%)")

    cap.release()
    print(f"  分析完成: {len(positions)} 帧")

    # 平滑处理
    print("平滑处理中...")
    faces = smooth_face_boxes(faces, window=smooth_window)

    return faces, positions


def smooth_face_boxes(faces, window=15):
    """对人脸框做滑动窗口平均，避免裁切窗口抖动。

    faces: [(x,y,w,h) 或 None]
    """
    smoothed = []
    n = len(faces)
    for i in range(n):
        start = max(0, i - window // 2)
        end = min(n, i + window // 2 + 1)
        valid = [f for f in faces[start:end] if f is not None]
        if not valid:
            smoothed.append(faces[i])
            continue
        arr = np.array(valid, dtype=np.float64).mean(axis=0)
        smoothed.append((int(arr[0]), int(arr[1]), int(arr[2]), int(arr[3])))
    return smoothed


def savgol_smooth(values, window=11, polyorder=2):
    """对一维序列做 Savitzky-Golay 平滑（低通滤波，抑制高频抖动）。

    比简单滑动均值保形更好（能保留人物的低频运动趋势，同时滤掉
    检测噪声导致的帧间高频抖动）。窗口须为奇数且 >= polyorder+1。
    边界用最近有效窗口做局部拟合，保证输出长度与输入一致。
    """
    vals = np.asarray(values, dtype=np.float64)
    n = len(vals)
    if n == 0:
        return vals.copy()
    if n < 3:
        return vals.copy()
    window = int(window)
    if window < 3 or window % 2 == 0:
        window = 11
    window = min(window, n if n % 2 == 1 else n - 1)
    if window < 3:
        return vals.copy()
    polyorder = int(min(polyorder, window - 1))
    polyorder = max(1, polyorder)

    half = window // 2
    out = np.empty_like(vals)
    # 逐点局部最小二乘拟合（scipy 不可用时也能工作，纯 numpy 实现）
    for i in range(n):
        s = max(0, i - half)
        e = min(n, i + half + 1)
        idx = np.arange(s, e, dtype=np.float64)
        if e - s < polyorder + 1:
            out[i] = vals[i]
            continue
        # 局部多项式拟合（零阶即窗口均值）
        A = np.vander(idx - i, polyorder + 1, increasing=True)
        coef, *_ = np.linalg.lstsq(A, vals[s:e], rcond=None)
        out[i] = coef[0]
    return out


def debounce_crop_y(crop_ys, min_step=3):
    """对 crop_y 序列做最小移动死区去抖：位置变化小于 min_step 像素时保持不动。

    这是消除画面抖动最直接的一环——即便做了平滑，只要相邻帧 crop_y
    差 1~2 像素就会让整个裁切窗口逐帧平移，人眼看就是画面「呼吸式」抖动。
    施加阈值后，微小波动被吞掉，只有位置真正移动超过 min_step 才更新，
    同时保留人物的整体运动轨迹。

    crop_ys: 逐帧 crop_y 列表
    min_step: 最小移动像素阈值（像素）
    """
    if not len(crop_ys):
        return list(crop_ys)
    out = []
    last = crop_ys[0]
    for v in crop_ys:
        if abs(v - last) >= min_step:
            last = v
        out.append(last)
    return out


def generate_dynamic_crop_params(faces, src_w, src_h, crop_ratio=9 / 16):
    """
    生成动态裁切参数（以人脸为锚，保证面部完整，并做抗抖动处理）。

    Args:
        faces: 每帧主体人脸 bbox (x,y,w,h) 或 None
        src_w: 源视频宽度
        src_h: 源视频高度
        crop_ratio: 裁切高度比例

    Returns:
        list: [{frame, crop_w, crop_h, crop_x, crop_y}, ...]
    """
    crop_w = src_w
    crop_h = int(src_w * crop_ratio)

    if crop_h > src_h:
        crop_h = src_h
        crop_w = int(src_h / crop_ratio)

    raw_crop_ys = []
    for face in faces:
        if face is not None:
            crop_y = compute_crop_y_keep_face(face, src_h, crop_h)
        else:
            crop_y = int(src_h * FIXED_FALLBACK_TOP_RATIO)
        crop_y = max(0, min(src_h - crop_h, crop_y))
        raw_crop_ys.append(int(crop_y))

    # 抗抖动两级处理：
    # 1) Savitzky-Golay 低通平滑（滤掉高频检测噪声，保留低频运动趋势）
    # 2) 最小移动死区去抖（微小位置变化直接吞掉，杜绝逐帧微平移）
    crop_ys = savgol_smooth(raw_crop_ys, window=11, polyorder=2)
    crop_ys = debounce_crop_y(crop_ys, min_step=3)

    params = []
    for i, crop_y in enumerate(crop_ys):
        crop_y = max(0, min(src_h - crop_h, int(round(crop_y))))
        params.append({
            "frame": i,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": 0,
            "crop_y": crop_y,
        })

    return params


def apply_fixed_crop(video_path, output_path, crop_params, output_size="1280x720"):
    """
    用 ffmpeg 应用固定裁切
    """
    crop_w = crop_params["crop_w"]
    crop_h = crop_params["crop_h"]
    crop_x = crop_params["crop_x"]
    crop_y = crop_params["crop_y"]

    out_w, out_h = output_size.split("x")

    print(f"固定裁切: crop={crop_w}:{crop_h}:{crop_x}:{crop_y}, scale={out_w}x{out_h}")

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={out_w}:{out_h}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-y",
        output_path
    ]

    print(f"执行 FFmpeg...")
    subprocess.run(cmd, check=True)
    print(f"输出: {output_path}")


def apply_dynamic_crop(video_path, output_path, crop_params, fps, output_size="1280x720"):
    """
    用 ffmpeg sendcmd 应用动态裁切
    """
    if not crop_params:
        raise ValueError("裁切参数为空")

    crop_w = crop_params[0]["crop_w"]
    crop_h = crop_params[0]["crop_h"]

    out_w, out_h = output_size.split("x")

    # 稀疏化写入 sendcmd：只在 crop_y 显著变化时才写命令，未变化/微变的帧
    # 自动保持上一写入位置。这样既大幅减少 ffmpeg 命令数，也彻底避免
    # 逐帧微平移造成的画面抖动（配合 generate_dynamic_crop_params 的
    # Savitzky-Golay 平滑 + 死区去抖，效果最佳）。
    min_step = 3  # 与 debounce_crop_y 的最小移动阈值保持一致
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        cmd_file = f.name
        last_y = None
        written = 0
        for p in crop_params:
            y = p["crop_y"]
            if last_y is None or abs(y - last_y) >= min_step:
                timestamp = p["frame"] / fps
                # ffmpeg sendcmd 要求每条命令以分号结尾，否则解析报错
                # （“Missing terminator or extraneous data”），这里补上；
                # 首帧时间戳为 0，天然作为裁切窗口的初始位置
                f.write(f"{timestamp} crop y {y};\n")
                last_y = y
                written += 1

    try:
        print(f"动态裁切: {len(crop_params)} 帧, 写入 {written} 条 sendcmd, scale={out_w}x{out_h}")

        cmd = [
            "ffmpeg", "-i", video_path,
            "-filter_complex",
            f"[0:v]sendcmd=f={cmd_file},crop={crop_w}:{crop_h}:0:0,scale={out_w}:{out_h}[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]

        print(f"执行 FFmpeg（动态裁切）...")
        subprocess.run(cmd, check=True)
        print(f"输出: {output_path}")

    finally:
        # 清理临时文件
        if os.path.exists(cmd_file):
            os.remove(cmd_file)


def main():
    parser = argparse.ArgumentParser(
        description="竖屏转横屏 + 人脸跟踪裁切",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 固定裁切（默认，快速）
  python vert2horiz_crop.py input.mp4 output.mp4

  # 动态跟踪（慢但准）
  python vert2horiz_crop.py input.mp4 output.mp4 --mode dynamic

  # 指定裁切比例和输出分辨率
  python vert2horiz_crop.py input.mp4 output.mp4 --ratio 0.6 --output-size 1280x720
        """
    )

    parser.add_argument("input", help="输入视频路径")
    parser.add_argument("output", help="输出视频路径")
    parser.add_argument("--mode", choices=["fixed", "dynamic"], default="fixed",
                        help="裁切模式: fixed=固定裁切（默认）, dynamic=动态跟踪")
    parser.add_argument("--ratio", type=float, default=9 / 16,
                        help="裁切高度比例（默认 0.5625 = 9/16）")
    parser.add_argument("--output-size", default="1280x720",
                        help="输出分辨率（默认 1280x720）")
    parser.add_argument("--detect-interval", type=int, default=2,
                        help="人脸检测间隔帧数（默认 2，减少计算量）")
    parser.add_argument("--smooth-window", type=int, default=15,
                        help="平滑窗口大小（默认 15）")
    parser.add_argument("--save-params", action="store_true",
                        help="保存裁切参数到 JSON 文件")

    args = parser.parse_args()

    # 检查输入文件
    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # 获取视频信息
    print(f"分析视频: {args.input}")
    src_w, src_h, fps, total = get_video_info(args.input)
    print(f"  源视频: {src_w}x{src_h}, {fps:.2f}fps, {total} 帧")

    # 检查是否为竖屏
    if src_w >= src_h:
        print(f"警告: 源视频不是竖屏（{src_w}x{src_h}），继续处理...")

    detector = FaceDetector()

    if args.mode == "fixed":
        # 固定裁切（智能定位人脸）
        print("\n模式: 固定裁切")
        crop_params = generate_fixed_crop_params(
            detector, args.input, src_w, src_h, args.ratio
        )
        print(f"  裁切窗口: {crop_params['crop_w']}x{crop_params['crop_h']}")
        print(f"  裁切位置: x={crop_params['crop_x']}, y={crop_params['crop_y']}")

        apply_fixed_crop(args.input, args.output, crop_params, args.output_size)

        if args.save_params:
            params_file = args.output + ".crop_params.json"
            with open(params_file, "w") as f:
                json.dump([crop_params], f, indent=2)
            print(f"参数已保存: {params_file}")

    else:
        # 动态跟踪
        print("\n模式: 动态跟踪")
        faces, _positions = analyze_faces(
            args.input,
            detect_interval=args.detect_interval,
            smooth_window=args.smooth_window,
            detector=detector,
        )

        crop_params = generate_dynamic_crop_params(faces, src_w, src_h, args.ratio)
        print(f"  生成 {len(crop_params)} 帧裁切参数")

        apply_dynamic_crop(args.input, args.output, crop_params, fps, args.output_size)

        if args.save_params:
            params_file = args.output + ".crop_params.json"
            with open(params_file, "w") as f:
                json.dump(crop_params, f, indent=2)
            print(f"参数已保存: {params_file}")

    print("\n完成!")


if __name__ == "__main__":
    main()
