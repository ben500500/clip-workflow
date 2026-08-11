#!/usr/bin/env python3
"""
vert2horiz_crop.py — 竖屏转横屏 + 人脸跟踪裁切

功能：
  将竖屏视频（9:16）转为横屏（16:9），支持两种裁切模式：
  - 固定裁切：取画面固定区域（适合人物居中场景，速度快）
  - 动态跟踪：逐帧检测人脸，动态调整裁切窗口（适合人物走动场景）

原理：
  1. 固定模式：取画面中间偏上区域，裁切为 16:9 比例
  2. 动态模式：OpenCV Haar cascade 检测人脸 → 以人脸为中心生成裁切窗口 → 平滑处理 → 输出
  3. 最终用 ffmpeg 执行裁切 + 缩放

用法：
  # 固定裁切（默认，快速）
  python vert2horiz_crop.py input.mp4 output.mp4

  # 动态跟踪（慢但准）
  python vert2horiz_crop.py input.mp4 output.mp4 --mode dynamic

  # 指定裁切高度比例（0.0-1.0，默认 0.5625 = 9/16）
  python vert2horiz_crop.py input.mp4 output.mp4 --ratio 0.6

  # 指定输出分辨率（默认 1920x1080）
  python vert2horiz_crop.py input.mp4 output.mp4 --output-size 1280x720

依赖：
  - OpenCV: pip install opencv-python
  - FFmpeg: 系统安装

作者: Ben + AI协作
日期: 2026-08-06
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


def detect_faces(frame, detector):
    """检测人脸，返回最大人脸的中心坐标 (cx, cy)"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(60, 60)
    )
    
    if len(faces) == 0:
        return None
    
    # 取最大的人脸（通常是主角）
    largest = max(faces, key=lambda f: f[2] * f[3])
    x, y, w, h = largest
    return (x + w // 2, y + h // 2)


def smooth_positions(positions, window=15):
    """滑动窗口平滑，避免裁切窗口抖动"""
    smoothed = []
    for i in range(len(positions)):
        start = max(0, i - window // 2)
        end = min(len(positions), i + window // 2 + 1)
        
        # 过滤掉 None 值
        valid_positions = [p for p in positions[start:end] if p]
        if not valid_positions:
            smoothed.append(positions[i] if positions[i] else (0, 0))
            continue
        
        avg_x = np.mean([p[0] for p in valid_positions])
        avg_y = np.mean([p[1] for p in valid_positions])
        smoothed.append((int(avg_x), int(avg_y)))
    
    return smoothed


def _build_face_detector():
    """构建人脸级联检测器，多路径兜底。

    Alpine 的 py3-opencv 包不带 cv2.data（haarcascades 数据文件缺失），
    直接 cv2.data.haarcascades 会抛 AttributeError。依次尝试：
      1. cv2.data.haarcascades（标准 opencv-python 安装）
      2. 常见系统路径（/usr/share/opencv4 等）
    全部失败时返回 None，由调用方降级处理（跳过人脸检测）。
    """
    candidates = []
    try:
        import cv2.data  # noqa: F401  显式导入子模块，确保 cv2.data 属性可用
        base = cv2.data.haarcascades
        candidates.append(os.path.join(base, "haarcascade_frontalface_default.xml"))
    except Exception:
        pass
    candidates += [
        "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
        "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
        "/usr/local/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            detector = cv2.CascadeClassifier(path)
            if not detector.empty():
                return detector
    return None


def analyze_faces(video_path, detect_interval=2, smooth_window=15):
    """
    逐帧分析人脸位置
    
    Args:
        video_path: 视频路径
        detect_interval: 每隔 N 帧检测一次（减少计算量）
        smooth_window: 平滑窗口大小
    
    Returns:
        positions: [(cx, cy), ...] 每帧的人脸中心坐标
    """
    print("开始人脸分析...")
    
    detector = _build_face_detector()
    if detector is None:
        # haarcascade 数据文件缺失（如 Alpine py3-opencv 无 cv2.data）：
        # 跳过人脸检测，全部按画面中心处理（等效 fixed 中心裁切）
        print("警告: 未找到 haarcascade 人脸检测数据，降级为画面中心裁切", file=sys.stderr)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    positions = []
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # 每隔 N 帧检测一次
        if frame_idx % detect_interval == 0:
            face = detect_faces(frame, detector) if detector is not None else None
            if face:
                positions.append(face)
            else:
                # 没检测到人脸，用上一帧位置或画面中心
                src_w = frame.shape[1]
                src_h = frame.shape[0]
                positions.append(positions[-1] if positions else (src_w // 2, src_h // 2))
        else:
            positions.append(positions[-1] if positions else (frame.shape[1] // 2, frame.shape[0] // 2))
        
        frame_idx += 1
        
        # 进度显示
        if frame_idx % 100 == 0:
            progress = frame_idx / total_frames * 100
            print(f"  分析进度: {frame_idx}/{total_frames} ({progress:.1f}%)")
    
    cap.release()
    
    print(f"  分析完成: {len(positions)} 帧")
    
    # 平滑处理
    print("平滑处理中...")
    positions = smooth_positions(positions, window=smooth_window)
    
    return positions


def generate_fixed_crop_params(src_w, src_h, crop_ratio=9/16):
    """
    生成固定裁切参数
    
    Args:
        src_w: 源视频宽度
        src_h: 源视频高度
        crop_ratio: 裁切高度比例（默认 9/16 = 0.5625）
    
    Returns:
        dict: {crop_w, crop_h, crop_x, crop_y}
    """
    # 竖屏转横屏：宽度不变，高度按比例裁切
    crop_w = src_w
    crop_h = int(src_w * crop_ratio)
    
    # 如果裁切高度大于源高度，反过来
    if crop_h > src_h:
        crop_h = src_h
        crop_w = int(src_h / crop_ratio)
    
    # 固定裁切：取画面中间偏上（人脸通常在画面上 1/3）
    # y 偏移 = 画面高度的 25%（保留上部分）
    crop_y = int(src_h * 0.25)
    crop_x = (src_w - crop_w) // 2
    
    # 边界约束
    crop_y = max(0, min(src_h - crop_h, crop_y))
    crop_x = max(0, min(src_w - crop_w, crop_x))
    
    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "crop_x": crop_x,
        "crop_y": crop_y,
    }


def generate_dynamic_crop_params(positions, src_w, src_h, crop_ratio=9/16):
    """
    生成动态裁切参数
    
    Args:
        positions: 人脸中心坐标列表
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
    
    params = []
    for i, (cx, cy) in enumerate(positions):
        # 以人脸为中心计算裁切窗口
        # 横屏裁切：宽度撑满，只需计算 y 偏移
        crop_y = cy - crop_h // 2
        
        # 边界约束
        min_y = 0
        max_y = src_h - crop_h
        crop_y = max(min_y, min(max_y, crop_y))
        
        params.append({
            "frame": i,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": 0,
            "crop_y": int(crop_y),
        })
    
    return params


def apply_fixed_crop(video_path, output_path, crop_params, output_size="1920x1080"):
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


def apply_dynamic_crop(video_path, output_path, crop_params, fps, output_size="1920x1080"):
    """
    用 ffmpeg sendcmd 应用动态裁切
    """
    if not crop_params:
        raise ValueError("裁切参数为空")
    
    crop_w = crop_params[0]["crop_w"]
    crop_h = crop_params[0]["crop_h"]
    
    out_w, out_h = output_size.split("x")
    
    # 生成 sendcmd 文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        cmd_file = f.name
        for p in crop_params:
            timestamp = p["frame"] / fps
            # ffmpeg sendcmd 要求每条命令以分号结尾，否则解析报错
            # （“Missing terminator or extraneous data”），这里补上；
            # 首帧时间戳为 0，天然作为裁切窗口的初始位置
            f.write(f"{timestamp} crop y {p['crop_y']};\n")
    
    try:
        print(f"动态裁切: {len(crop_params)} 帧, scale={out_w}x{out_h}")
        
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
    parser.add_argument("--ratio", type=float, default=9/16,
                        help="裁切高度比例（默认 0.5625 = 9/16）")
    parser.add_argument("--output-size", default="1920x1080",
                        help="输出分辨率（默认 1920x1080）")
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
    
    if args.mode == "fixed":
        # 固定裁切
        print("\n模式: 固定裁切")
        crop_params = generate_fixed_crop_params(src_w, src_h, args.ratio)
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
        positions = analyze_faces(
            args.input,
            detect_interval=args.detect_interval,
            smooth_window=args.smooth_window
        )
        
        crop_params = generate_dynamic_crop_params(positions, src_w, src_h, args.ratio)
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
