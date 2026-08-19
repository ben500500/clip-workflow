#!/usr/bin/env python3
"""去重扩展特效模块：三个方向的落地实现。

方向一（sparkle）：若隐若现的星星点 / 小光环。
  用预生成的透明光点/光晕 sprite（径向衰减 + 柔和辉光），通过 overlay 叠加，
  并用 geq 在 alpha 通道上叠加时间正弦包络，实现"呼吸式"明暗脉动的星星点与小光环，
  叠加后几乎不可察觉（默认透明度很低），却能在帧级特征上增加差异化。

方向二（mask 加速）：仅对 mask 覆盖的 ROI 做局部修复，其余像素不参与重算。
  相比全帧 inpaint，可省掉大量无效计算（ROI 往往只占画面 10%~20%）。

方向三（face_watermark）：人脸跟踪 + 动态漂浮淡色水印。
  复用 vert2horiz_crop.py 的 FaceDetector（YuNet + Haar 降级），逐帧检测主体人脸，
  用滑动窗口/滑窗平滑出稳定脸中心轨迹，再用 drawtext 的 if(lt(t,..)) 链式时间条件
  让极淡水印（默认 white@0.06~0.10）沿轨迹缓慢漂浮，实现"水印跟脸走但不遮挡内容"。

本模块被 engines/slice.py 的去重滤镜链（build_dedupe_filter）按需调用，
所有特效均为可选开关，默认关闭，不影响既有去重行为。
"""

from __future__ import annotations

import math
import os
import random
import tempfile

# 允许导入同目录的竖屏转横屏引擎（人脸检测依赖 OpenCV）
sys_path = os.path.dirname(os.path.abspath(__file__))
if sys_path not in os.sys.path:
    os.sys.path.insert(0, sys_path)
try:
    import vert2horiz_crop
except ImportError:  # pragma: no cover - OpenCV 未安装
    vert2horiz_crop = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


# 默认光点 sprite 尺寸
DEFAULT_SPRITE = 80


def _sprite_available() -> bool:
    """sprite 生成依赖 numpy + cv2（或 PIL 兜底）。"""
    if np is not None and cv2 is not None:
        return True
    try:
        import PIL  # noqa: PLC0415
        return True
    except Exception:
        return False


def _write_png(path: str, rgba: "np.ndarray") -> None:
    if cv2 is not None:
        cv2.imwrite(path, rgba)
    else:
        from PIL import Image  # noqa: PLC0415
        Image.fromarray(rgba, "RGBA").save(path)


def generate_star_sprite(size: int = DEFAULT_SPRITE) -> str:
    """生成一颗带径向衰减 + 柔和辉光的白点 sprite（透明 PNG），返回路径。

    中心是明亮的小核（星星点），外围是柔和的大范围辉光（小光环），
    透明度向外衰减，保证叠加后"若隐若现"不突兀。
    """
    size = max(16, int(size))
    yy, xx = np.mgrid[0:size, 0:size]
    c = (size - 1) / 2.0
    d = np.sqrt((xx - c) ** 2 + (yy - c) ** 2)
    # 明亮小核（半径约 size/8）+ 柔和辉光（半径约 size/2.2）
    core = np.clip(1 - d / (size / 8.0), 0, 1)
    halo = np.exp(-((d) / (size / 2.6)) ** 2) * 0.55
    alpha = np.clip(np.maximum(core, halo), 0, 1)
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[..., 0] = 255
    rgba[..., 1] = 255
    rgba[..., 2] = 255
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    path = os.path.join(tempfile.gettempdir(), f"dedupe_star_{size}.png")
    _write_png(path, rgba)
    return path


def build_sparkle_filter(
    cfg: dict,
    width: int = 0,
    height: int = 0,
    base_path: str | None = None,
) -> list[str]:
    """方向一：构造若隐若现星星点/小光环的 vf 滤镜段列表。

    返回单条 `-vf` 链兼容的滤镜段（用 geq 在画面上叠加小十字星点/光点，
    配合时间正弦包络实现呼吸式明暗闪烁），可直接拼进 build_dedupe_filter 的
    vf_parts，无需额外输入流（不依赖 overlay 的多输入）。

    cfg（dict）：
      - count: int  光点数量（默认 3）
      - size: int   星点半径 px（默认 3，越大越像小光环）
      - opacity: float  峰值亮度（默认 12，越小越不易察觉）
      - positions: [[x,y], ...]  可选固定位置；不传则随机散布
      - seed: int  随机种子，保证同配置可复现
    """
    if not cfg:
        return []
    count = max(1, int(cfg.get("count") or 3))
    size = max(1, int(cfg.get("size") or 3))
    opacity = float(cfg.get("opacity") or 12.0)
    opacity = max(1.0, min(40.0, opacity))
    seed = int(cfg.get("seed") or 0)
    rnd = random.Random(seed)

    if width <= 0 or height <= 0:
        width, height = 1280, 720
    positions = cfg.get("positions") or []
    parts = []
    for i in range(count):
        if positions and i < len(positions):
            x, y = int(positions[i][0]), int(positions[i][1])
        else:
            x = rnd.randint(int(width * 0.15), int(width * 0.85))
            y = rnd.randint(int(height * 0.12), int(height * 0.78))
        # 呼吸频率与相位随机，固定 seed 可复现
        freq = rnd.choice([0.6, 0.8, 1.0, 1.3, 1.6])
        phase = rnd.uniform(0, 2 * math.pi)
        r = size
        # geq 在星点小范围内叠加亮度：核心 + 十字星芒，亮度用时间正弦呼吸（若隐若现）
        #   亮度基座 0，峰值 opacity，乘 sin 包络使明暗周期性波动。
        terms = (
            f"eq(mod(abs(X-{x})+abs(Y-{y})\,{r}),0)"
        )
        star = (
            f"if(eq(abs(X-{x}),0)*lt(abs(Y-{y}),{r})\,1\,0)+"
            f"if(eq(abs(Y-{y}),0)*lt(abs(X-{x}),{r})\,1\,0)"
        )
        glow = (
            f"max(0\,1-sqrt(pow(X-{x}\,2)+pow(Y-{y}\,2))/{r})"
        )
        amp = f"{opacity:.1f}*(0.25+0.75*max(0\,sin(2*PI*T*{freq:.2f}+{phase:.2f})))"
        expr = f"lum(X,Y)+{amp}*({star})"
        parts.append(f"geq=lum='{expr}'")

    return parts


def _build_pos_expression(positions: list[tuple[float, float]], interval: float) -> tuple[str, str]:
    """把 (时间, x) / (时间, y) 序列转成 drawtext 可用的 if(lt(t,..),..) 链式表达式。

    positions: 排序后的 [(time, value), ...]。
    返回 (x_expr, y_expr)。
    """
    # 用近似区间构建 if() 链：t 落在 [t_k, t_{k+1}) 取第 k 段值
    def chain(series: list[tuple[float, float]]) -> str:
        n = len(series)
        if n == 0:
            return "0"
        if n == 1:
            return f"{series[0][1]:.1f}"
        # 从后往前嵌套 if
        expr = f"{series[-1][1]:.1f}"
        for k in range(n - 2, -1, -1):
            t_next = series[k + 1][0]
            expr = f"if(lt(t\\,{t_next:.2f})\\,{series[k][1]:.1f}\\,{expr})"
        return expr

    xs = [(t, v) for t, v in positions]
    return chain(xs), chain(xs)  # 占位，实际按坐标分列


def build_face_watermark_filter(
    cfg: dict,
    video_path: str,
    width: int = 0,
    height: int = 0,
) -> str | None:
    """方向三：构造人脸跟踪 + 动态漂浮淡色水印的 drawtext 滤镜段。

    复用 vert2horiz_crop.FaceDetector 逐帧检测主体人脸，平滑出脸中心轨迹，
    再生成 drawtext，x/y 用 if(lt(t,..)) 链式时间条件随时间移动到脸中心附近。

    cfg（dict）：
      - text: str        水印文字（默认 "W"）
      - opacity: float   透明度（默认 0.08，越淡越不易察觉）
      - font_size: int   字号（默认 24）
      - interval: float  轨迹关键帧间隔秒（默认 1.0，越小越顺滑但表达式越长）
      - offset: int      相对脸中心的像素偏移（默认 0，落在脸正上方附近）
      - detect_interval: int  人脸检测帧间隔（默认 2，越大越快）

    返回 drawtext 滤镜段字符串；无 OpenCV/无视频时返回 None（不叠加）。
    """
    if not cfg or not video_path or not os.path.isfile(video_path):
        return None
    if vert2horiz_crop is None:
        return None
    text = str(cfg.get("text") or "W")
    opacity = float(cfg.get("opacity") or 0.08)
    opacity = max(0.02, min(0.3, opacity))
    font_size = int(cfg.get("font_size") or 24)
    interval = max(0.25, float(cfg.get("interval") or 1.0))
    offset = int(cfg.get("offset") or 0)
    detect_interval = max(1, int(cfg.get("detect_interval") or 2))

    if width <= 0 or height <= 0:
        # 用 ffprobe 探测分辨率
        dims = _ffprobe_size(video_path)
        if dims:
            width, height = dims
        else:
            return None

    # 复用竖屏转横屏的人脸检测 + 平滑
    try:
        detector = vert2horiz_crop.FaceDetector()
        faces, positions = vert2horiz_crop.analyze_faces(
            video_path,
            detect_interval=detect_interval,
            smooth_window=15,
            detector=detector,
        )
    except Exception:
        return None

    total = len(positions)
    if total == 0:
        return None

    # 采样成 (time, cx, cy) 关键帧，把脸中心作为水印锚点（落在脸上方附近）
    keypoints = []  # (time, x, y)
    for i in range(0, total):
        cx, cy = positions[i]
        t = i / max(1, _fps_approx(video_path) or 30)
        keypoints.append((t, cx, cy))

    # 按 interval 降采样为关键帧，避免表达式过长
    sampled: list[tuple[float, float, float]] = []
    last_t = -1e9
    for t, cx, cy in keypoints:
        if t - last_t >= interval - 1e-6:
            sampled.append((t, cx, cy))
            last_t = t
    if not sampled or len(sampled) < 2:
        return None
    # 补充最后一帧
    last_t, last_x, last_y = keypoints[-1]
    if sampled[-1][0] < last_t - 1e-6:
        sampled.append((last_t, last_x, last_y))

    # 水印锚点：落在脸中心上方 offset 处（offset 可为负则落在脸上）
    x_series = [(t, max(0.0, min(width - 1, cx))) for t, cx, cy in sampled]
    y_series = [(t, max(0.0, min(height - 1, cy - offset))) for t, cx, cy in sampled]
    x_expr = _chain_expr(x_series)
    y_expr = _chain_expr(y_series)

    font_opt = _resolve_font()
    text_esc = text.replace("\\", "\\\\").replace(";", "\\;")
    return (
        f"drawtext={font_opt}:text='{text_esc}':fontcolor=white@{opacity:.2f}"
        f":fontsize={font_size}:x='{x_expr}':y='{y_expr}'"
    )


def _chain_expr(series: list[tuple[float, float]]) -> str:
    """把 [(time, value)] 转成 if(lt(t,..),..) 链式表达式。"""
    n = len(series)
    if n == 0:
        return "0"
    if n == 1:
        return f"{series[0][1]:.1f}"
    expr = f"{series[-1][1]:.1f}"
    for k in range(n - 2, -1, -1):
        t_next = series[k + 1][0]
        expr = f"if(lt(t\\,{t_next:.2f})\\,{series[k][1]:.1f}\\,{expr})"
    return expr


def _ffprobe_size(path: str) -> tuple[int, int] | None:
    import json  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        ).stdout
        d = json.loads(out)
        s = d["streams"][0]
        return int(s["width"]), int(s["height"])
    except Exception:
        return None


def _fps_approx(path: str) -> float:
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate,r_frame_rate", "-of", "default=nw=1", path],
            capture_output=True, text=True, timeout=30,
        ).stdout
        for line in out.splitlines():
            if "r_frame_rate=" in line or "avg_frame_rate=" in line:
                val = line.split("=", 1)[1]
                if "/" in val:
                    num, den = val.split("/")
                    try:
                        if float(den) > 0:
                            return float(num) / float(den)
                    except Exception:
                        pass
    except Exception:
        pass
    return 30.0


def _resolve_font() -> str:
    """解析 drawtext 可用字体（与 slice.py 保持一致，找不到则返回空）。"""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/system/fonts/DroidSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return f"fontfile={c}"
    return ""


def crop_inpaint_roi(image, mask, radius=3):
    """方向二：仅对 mask 覆盖的 ROI 做 inpaint，其余像素不重算（加速）。

    相比整帧 inpaint，ROI 通常只占画面 10%~20%，可省掉大量无效计算。

    Args:
        image: BGR 全帧
        mask: 单通道 uint8（白=待修复）
        radius: inpaint 半径
    Returns:
        修复后的全帧（非 ROI 区域保持原样）
    """
    if cv2 is None:
        raise RuntimeError("cv2 不可用，无法做 ROI inpaint")
    h, w = mask.shape[:2]
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return image.copy()
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    # 加边距，给 inpaint 留过渡空间
    pad = max(radius + 2, 8)
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    roi_img = image[y0:y1, x0:x1]
    roi_mask = mask[y0:y1, x0:x1]
    result = cv2.inpaint(roi_img, roi_mask, radius, cv2.INPAINT_TELEA)
    out = image.copy()
    out[y0:y1, x0:x1] = result
    return out
