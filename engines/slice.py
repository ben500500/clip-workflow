#!/usr/bin/env python3
"""ffmpeg-based slice engine for Clip Workflow.

Usage:
  slice.py <source> <cutlist> <output_dir> --mode fast|dedupe|scrub [--intervals FILE] [--watermark JSON]

Cutlist format (per line):  start end name   (HH:MM:SS.mmm times)
Interval format (per line): start end

Prints OUTPUT:<name>:<duration> and PROGRESS:<pct> lines to stdout.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

# 允许导入同目录下的竖屏转横屏引擎（vert2horiz_crop.py 依赖 OpenCV）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import vert2horiz_crop
except ImportError:  # pragma: no cover - OpenCV 未安装时动态模式不可用
    vert2horiz_crop = None


# 默认 CPU 资源分配比例（%）：切片时限制 ffmpeg 编码线程数，避免占满整机 CPU
DEFAULT_CPU_PERCENT = 50


# ──────────────────────────────────────────────
# 去重（老电视质感）滤镜链：轻/标准/重 三档
# ──────────────────────────────────────────────
# 去重不是堆得越多越好，而是"空间 + 时域 + 色彩 + 质感"四层组合，
# 让成品与原素材在帧级特征、色彩直方图、时域指纹三个维度同时拉开距离。
# 老电视效果本质是质感层，同时天然改变亮度（扫描线）、噪点结构（颗粒）、色调
# （复古偏色），本身即是一种很「润」的去重手段。
#
# 每档参数：
#   crop      空间层：相对裁切比例（裁掉四周后缩放回原尺寸，改像素对齐/构图）
#   hflip     空间层：是否水平镜像（直接破坏帧哈希）
#   speed     时域层：变速系数（改时长与帧对齐）
#   saturation/gamma/contrast/brightness  色彩层：降饱和 + 复古调色
#   colorbalance / colortemperature       色彩层：复古偏色（暖黄/冷调）
#   noise     质感层：颗粒噪点强度（alls，时域+空域）
#   scanline  质感层：扫描线（drawgrid h 间隔 / 黑条透明度）
#   vignette  质感层：暗角角度
#   roll_band 质感层：滚动暗带强度（0 关闭）
#   jitter    质感层：画面微抖动（0 关闭）
DEDUPE_PRESETS = {
    "light": {
        "crop": 0.02,
        "hflip": False,
        "speed": 1.02,
        "saturation": 0.92,
        "gamma": 1.02,
        "contrast": 1.01,
        "brightness": 0.005,
        "colorbalance": "rs=.03:gs=.02:bs=-.03:rm=.03:gm=.02:bm=-.03",
        "colortemperature": "temperature=6200",
        "noise": 3,
        "scanline": None,
        "vignette": "PI/6",
        "roll_band": 0,
        "jitter": 0,
    },
    "standard": {
        "crop": 0.03,
        "hflip": True,
        "speed": 1.03,
        "saturation": 0.85,
        "gamma": 1.03,
        "contrast": 1.03,
        "brightness": 0.01,
        "colorbalance": "rs=.06:gs=.03:bs=-.06:rm=.06:gm=.03:bm=-.06",
        "colortemperature": "temperature=5800",
        "noise": 6,
        "scanline": {"h": 3, "color": "black@0.10"},
        "vignette": "PI/5",
        "roll_band": 0,
        "jitter": 0,
    },
    "heavy": {
        "crop": 0.05,
        "hflip": True,
        "speed": 1.05,
        "saturation": 0.78,
        "gamma": 1.06,
        "contrast": 1.05,
        "brightness": 0.02,
        "colorbalance": "rs=.10:gs=.05:bs=-.10:rm=.10:gm=.05:bm=-.10",
        "colortemperature": "temperature=5600",
        "noise": 10,
        "scanline": {"h": 2, "color": "black@0.16"},
        "vignette": "PI/4",
        "roll_band": 12,
        "jitter": 2,
    },
}


def _even(n: int) -> int:
    """把整数收敛为偶数（保证 yuv420p 编码时宽高为偶数）。"""
    n = int(n)
    if n < 2:
        return 2
    return n if n % 2 == 0 else n - 1


def build_dedupe_filter(preset: str, width: int = 0, height: int = 0) -> tuple[str, str]:
    """根据去重档位（light/standard/heavy）构造 (vf, af) 滤镜链。

    四层组合：空间（缩放裁切 + 可选镜像）、时域（变速）、色彩（降饱和 + 复古偏色 + 轻微亮度）、
    质感（噪点 / 扫描线 / 暗角 / 滚动暗带 / 画面抖动）。

    width/height 用于在裁切后缩放回原始分辨率（保持输出尺寸一致）；未提供或为 0 时
    仅做相对裁切（轻微改变分辨率，同样有效）。
    """
    preset = (preset or "standard").lower()
    if preset not in DEDUPE_PRESETS:
        preset = "standard"
    p = DEDUPE_PRESETS[preset]

    crop = float(p["crop"])
    speed = float(p["speed"])

    # 空间层：裁切（改构图/像素对齐），有原始分辨率则缩放回原尺寸
    if width > 0 and height > 0:
        cw = _even(width * (1.0 - crop))
        ch = _even(height * (1.0 - crop))
        spatial = f"crop={cw}:{ch},scale={width}:{height}"
    else:
        spatial = f"crop=iw*{1.0 - crop:.4f}:ih*{1.0 - crop:.4f}"
    if p["hflip"]:
        spatial += ",hflip"

    # 时域层：变速（视频 setpts 与音频 atempo 需一一对应）
    vf_parts = [spatial, f"setpts=PTS/{speed:.3f}"]
    af = f"atempo={speed:.3f}"

    # 色彩层：降饱和 + 复古调色 + 轻微亮度
    vf_parts.append(
        f"eq=saturation={p['saturation']}:gamma={p['gamma']}"
        f":contrast={p['contrast']}:brightness={p['brightness']}"
    )
    vf_parts.append(f"colorbalance={p['colorbalance']}")
    vf_parts.append(f"colortemperature={p['colortemperature']}")

    # 质感层：颗粒噪点（时域+空域，老电视颗粒感）
    vf_parts.append(f"noise=alls={p['noise']}:allf=t+u")

    # 质感层：扫描线（每 N px 一条 1px 暗线）
    if p["scanline"]:
        h = p["scanline"]["h"]
        color = p["scanline"]["color"]
        vf_parts.append(f"drawgrid=w=iw:h={h}:t=1:color={color}")

    # 质感层：暗角（老电视边缘压暗）
    if p["vignette"]:
        vf_parts.append(f"vignette=angle={p['vignette']}")

    # 质感层：滚动暗带（上下缓慢滚动的亮度条带，重档开启）
    if p["roll_band"]:
        band = float(p["roll_band"])
        vf_parts.append(f"geq=lum='lum(X,Y)-{band}*sin(2*PI*T*0.4+2*PI*Y/H)'")

    # 质感层：画面微抖动（正弦摆动裁切后缩放回原尺寸，重档开启）
    if p["jitter"]:
        j = float(p["jitter"])
        if width > 0 and height > 0:
            cw = _even(width - 2 * j)
            ch = _even(height - 2 * j)
            vf_parts.append(
                f"crop={cw}:{ch}:x='{j}+{j}*sin(2*PI*t*3)':y='{j}+{j}*cos(2*PI*t*2)'"
                f",scale={width}:{height}"
            )
        else:
            vf_parts.append(
                f"crop=iw-{int(2*j)}:ih-{int(2*j)}"
                f":x='{j}+{j}*sin(2*PI*t*3)':y='{j}+{j}*cos(2*PI*t*2)'"
            )

    return ",".join(vf_parts), af


def cpu_threads_for_percent(percent: int) -> int:
    """根据 CPU 分配比例计算 ffmpeg 使用的线程数（至少 1，最多为 CPU 核心数）。

    算法：threads = max(1, round(cores * percent / 100))，
    例如 8 核 + 50%% => 4 线程，8 核 + 100%% => 8 线程。
    """
    if percent <= 0:
        percent = DEFAULT_CPU_PERCENT
    if percent > 100:
        percent = 100
    try:
        cores = os.cpu_count() or 1
    except Exception:
        cores = 1
    n = int(round(cores * percent / 100.0))
    if n < 1:
        n = 1
    if n > cores:
        n = cores
    return n


def parse_time(s: str) -> float:
    parts = s.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def read_cutlist(path: str):
    cuts = []
    if not path or not os.path.isfile(path):
        return cuts
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                cuts.append((parse_time(parts[0]), parse_time(parts[1]), parts[2]))
            except ValueError:
                continue
    return cuts


def read_intervals(path: str):
    intervals = []
    if not path or not os.path.isfile(path):
        return intervals
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                intervals.append((parse_time(parts[0]), parse_time(parts[1])))
            except ValueError:
                continue
    return intervals


def subtract_intervals(cuts, intervals):
    """Remove interval overlaps from each cut.

    Returns segments as (start, end, name, cut_index).
    """
    segments = []
    for idx, (s, e, name) in enumerate(cuts):
        segs = [(s, e)]
        for is_, ie in intervals:
            if is_ >= e or ie <= s:
                continue
            new = []
            for a, b in segs:
                if is_ <= a and ie >= b:
                    continue
                if is_ > a:
                    new.append((a, min(is_, b)))
                if ie < b:
                    new.append((max(ie, a), b))
            segs = new
        for a, b in segs:
            segments.append((a, b, name, idx))
    return segments


def ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def ffprobe_resolution(path: str) -> tuple[int, int]:
    """探测视频分辨率 (width, height)，失败返回 (0, 0)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        parts = out.stdout.split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


def ffprobe_size(path: str) -> tuple[int, int]:
    """读取视频分辨率 (width, height)，失败返回 (0, 0)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        line = (out.stdout or "").strip().splitlines()
        if line:
            parts = line[0].split(",")
            if len(parts) >= 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                return int(parts[0].strip()), int(parts[1].strip())
    except Exception:
        pass
    return 0, 0


def run_ffmpeg(args, timeout=3600, threads=1):
    # 若未显式设置 -threads，则追加（避免并发切片抢占过多 CPU）
    if "-threads" not in args:
        args = ["-threads", str(threads)] + list(args)
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + proc.stderr.decode(errors="replace")[-2000:])
    return proc


def detect_best_encoder(preferred: str | None = None) -> str:
    """探测可用的最佳编码器。

    三期 GPU 加速编码：优先使用硬件编码器（nvenc/hevc_videotoolbox），
    不可用则回退到软件 libx264。
    """
    if preferred:
        try:
            probe = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15,
            )
            encoders = probe.stdout or ""
            if preferred in encoders:
                return preferred
        except Exception:
            pass
    try:
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
        )
        encoders = probe.stdout or ""
        for enc in ("hevc_videotoolbox", "h264_videotoolbox", "h264_nvenc", "hevc_nvenc", "libx264"):
            if enc in encoders:
                return enc
    except Exception:
        pass
    return "libx264"


def build_encoder_args(encoder: str, threads: int) -> list[str]:
    """根据编码器构造 ffmpeg 编码参数."""
    if encoder in ("h264_nvenc", "hevc_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-cq", "23"]
    if encoder in ("h264_videotoolbox", "hevc_videotoolbox"):
        return ["-c:v", encoder, "-q:v", "65"]
    # 软件编码回退
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", str(threads)]


def slice_segment(src, start, end, out, vf=None, af=None, threads=1, encoder="libx264", copy_if_possible=True):
    # fast 模式且无滤镜时走流拷贝（-c copy），只切不重编码，速度 10×+；
    # 需要滤镜（去重/水印/竖转横）或显式关闭时回退到重编码分支。
    copy_mode = bool(copy_if_possible and not vf and not af)
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
    ]
    if copy_mode:
        cmd += ["-c", "copy", "-movflags", "+faststart"]
    else:
        cmd += build_encoder_args(encoder, threads)
        cmd += ["-c:a", "aac", "-b:a", "128k"]
        if vf:
            cmd += ["-vf", vf]
        if af:
            cmd += ["-af", af]
    cmd.append(out)
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def concat_segments(parts, out, threads=1, encoder="libx264", copy_if_possible=True):
    if len(parts) == 1:
        # 单段时无需重新编码（水印已在 slice_segment 阶段叠加）
        shutil.move(parts[0], out)
        return
    # 多段：若各段均为 copy 产出（同编码/分辨率/时基），用 concat demuxer 免重编码拼接
    if copy_if_possible and all(_is_copy_segment(p) for p in parts):
        _concat_demuxer(parts, out)
        return
    filter_complex = "".join(
        f"[{i}:v][{i}:a]" for i in range(len(parts))
    ) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
    ]
    for part in parts:
        cmd += ["-i", part]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", out]
    run_ffmpeg(cmd, threads=threads)


def _is_copy_segment(path: str) -> bool:
    """粗略判断片段是否为流拷贝产出（封装格式 mp4 即可；copy 片段编码/时基一致）。"""
    try:
        return os.path.getsize(path) > 0 and path.lower().endswith(".mp4")
    except OSError:
        return False


def _concat_demuxer(parts, out):
    """用 ffmpeg concat demuxer + -c copy 免重编码拼接多段。"""
    list_file = out + ".concat.txt"
    with open(list_file, "w") as f:
        for p in parts:
            # ffmpeg concat demuxer：单引号内用 '\'' 转义内嵌单引号，路径含引号也能安全解析
            escaped = p.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    try:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", "-movflags", "+faststart", out]
        run_ffmpeg(cmd, timeout=3600)
    finally:
        try:
            os.unlink(list_file)
        except OSError:
            pass


def safe_name(name: str) -> str:
    name = os.path.basename(name)
    if not name.endswith(".mp4"):
        name += ".mp4"
    return name


# 角标位置到 overlay x/y 坐标表达式的映射
# 位置以视频宽高为基准（W/H），角标宽高以 scale 后的 overlay 图为准（w/h）
# {O} 为角标到视频边缘的偏移量占位符，运行时会替换为具体像素值（默认 10）
BADGE_POSITIONS = {
    # 左上 / 中上 / 右上 / 最左侧(中左) / 左下 / 中下 / 右下
    "top-left":      ("{O}", "{O}"),
    "top-center":    ("(W-w)/2", "{O}"),
    "top-right":     ("W-w-{O}", "{O}"),
    "left":          ("{O}", "(H-h)/2"),
    "bottom-left":   ("{O}", "H-h-{O}"),
    "bottom-center": ("(W-w)/2", "H-h-{O}"),
    "bottom-right":  ("W-w-{O}", "H-h-{O}"),
}

# 角标默认偏移量（px，未指定时使用）
BADGE_DEFAULT_OFFSET = 10
# 角标默认宽度（px，未指定且未设置宽度时使用；0 表示保持原图尺寸）
BADGE_DEFAULT_WIDTH = 0
# 角标默认透明度（0~1，未指定时使用）
BADGE_DEFAULT_OPACITY = 1.0


def _badge_scale_and_opacity(badge: dict, default_width: int) -> str:
    """构造单个角标的 scale + 透明度 filter 链。

    默认尺寸：优先使用角标自身 width；否则回退到调用方传入的 default_width；
    再否则保持原图尺寸。透明度通过 colorchannelmixer 的 aa（alpha）通道实现。
    """
    try:
        width = int(badge.get("width") or 0)
    except (TypeError, ValueError):
        width = 0
    if width <= 0:
        width = int(default_width or 0)
    scale = f"scale={width}:-1" if width > 0 else "null"

    try:
        opacity = float(badge.get("opacity") or BADGE_DEFAULT_OPACITY)
    except (TypeError, ValueError):
        opacity = BADGE_DEFAULT_OPACITY
    opacity = min(1.0, max(0.0, opacity))

    chain = scale
    if opacity < 1.0:
        # rgba 保证有 alpha 通道后再调节透明度
        chain += f",format=rgba,colorchannelmixer=aa={opacity:.3f}"
    else:
        chain += ",format=rgba"
    return chain


def build_badges_overlay_args(
    badges: list,
    threads: int,
    encoder: str,
    default_width: int = BADGE_DEFAULT_WIDTH,
) -> list[str]:
    """构造在成品视频上叠加多角标的 ffmpeg 命令参数（-filter_complex 多输入）。

    返回完整的 ffmpeg 参数（含 -y、主视频输入、各角标 -i、filter_complex、
    overlay 叠加、编码输出到 -o）。调用方只需追加输出路径。
    角标全程叠加在视频指定位置上（不随时间消失），支持多角标。

    每个角标支持：position（六角位置）、width（宽度，px）、offset（到边缘偏移，px）、
    opacity（透明度 0~1）。default_width 为所有角标的默认宽度（角标未单独设 width 时生效）。
    """
    # 校验角标图片存在
    valid = []
    for badge in badges:
        path = badge.get("path") or ""
        if path and os.path.isfile(path):
            valid.append(badge)
    if not valid:
        return []

    # 构造 filter_complex
    parts = []
    num = len(valid)
    for i, badge in enumerate(valid):
        position = (badge.get("position") or "top-left").lower()
        if position not in BADGE_POSITIONS:
            position = "top-left"
        chain = _badge_scale_and_opacity(badge, default_width)
        parts.append(f"[{i + 1}:v]{chain}[badge{i}]")

    current = "[0:v]"
    for i in range(num):
        position = (valid[i].get("position") or "top-left").lower()
        if position not in BADGE_POSITIONS:
            position = "top-left"
        x_template, y_template = BADGE_POSITIONS[position]
        try:
            offset = int(valid[i].get("offset") or BADGE_DEFAULT_OFFSET)
        except (TypeError, ValueError):
            offset = BADGE_DEFAULT_OFFSET
        offset = max(0, offset)
        x_expr = x_template.replace("{O}", str(offset))
        y_expr = y_template.replace("{O}", str(offset))
        out_label = f"[vout{i}]" if i < num - 1 else "[vout]"
        current = f"{current}[badge{i}]overlay=x={x_expr}:y={y_expr}:shortest=0{out_label}"
    parts.append(current)
    filter_complex = ";".join(parts)

    # 返回 ["-i", badge1, "-i", badge2, ..., "-filter_complex", fc, "-map", "[vout]", 编码参数]
    # 调用方在开头追加 -i <主视频>
    args = []
    for badge in valid:
        args += ["-i", badge["path"]]
    args += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:a", "aac", "-b:a", "128k",
    ]
    args += build_encoder_args(encoder, threads)
    return args


def apply_badges(src, out, badges, threads=1, encoder="libx264", default_width: int = BADGE_DEFAULT_WIDTH):
    """对成品视频执行一次角标 overlay 叠加，产出新文件。"""
    badge_args = build_badges_overlay_args(badges, threads, encoder, default_width=default_width)
    if not badge_args:
        # 无有效角标，直接复制
        shutil.copy(src, out)
        return
    cmd = ["ffmpeg", "-y", "-threads", str(threads), "-i", src] + badge_args + [out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


# ──────────────────────────────────────────────
# 固定文字叠加（角标文字版：最左侧 / 左下角 / 右上角）
# ──────────────────────────────────────────────

# 固定文字位置到 drawtext x/y 坐标表达式的映射。
# 坐标以输出视频宽高为基准（w/h 为视频宽高，tw/th 为文本块宽高）。
# {O} 为文字到视频边缘的偏移量占位符，运行时会替换为具体像素值（默认 10）。
# "left" 为最左侧（画面左侧垂直居中，竖排文字）。
TEXT_OVERLAY_POSITIONS = {
    "top-left":     ("{O}", "{O}"),
    "top-center":   ("(w-tw)/2", "{O}"),
    "top-right":    ("w-tw-{O}", "{O}"),
    "left":         ("{O}", "(h-th)/2"),
    "bottom-left":  ("{O}", "h-th-{O}"),
    "bottom-center":("(w-tw)/2", "h-th-{O}"),
    "bottom-right": ("w-tw-{O}", "h-th-{O}"),
}

# 固定文字默认偏移量（px）
TEXT_OVERLAY_DEFAULT_OFFSET = 10
# 固定文字默认字号（px）
TEXT_OVERLAY_DEFAULT_FONT_SIZE = 36
# 固定文字默认颜色（CSS 十六进制，白字）
TEXT_OVERLAY_DEFAULT_COLOR = "#FFFFFF"
# 固定文字默认描边颜色（深色描边，保证任意背景下清晰）
TEXT_OVERLAY_DEFAULT_BORDER_COLOR = "#000000"


# 中文字体候选（容器内通常装有 font-noto-cjk / wqy 等）
# 注意：这里只放单字体文件（.ttf/.otf）。Noto CJK / wqy-zenhei 的 .ttc 是字体集合，drawtext
# 用 fontfile 引用时会默认加载集合里第一个子字体（往往是 JP 日文字形），导致简体字（如"门"）
# 渲染成日式/异常字形，因此 .ttc 一律不放进来、统一走下方 fontconfig 的 font= 精确匹配。
_TEXT_SINGLE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttf",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
# 仅当没有任何单字体文件时才考虑 ttc 集合（配合 fontconfig FontName 精确匹配简体中文）
_TEXT_TTC_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
]

# 用 fc-match 动态解析 Noto Sans CJK SC 真实路径，避免依赖写死的发行版路径（Debian/Alpine 布局不同）。
_FCMATCH_CMD = "fc-match"
# 提取出的 SC 单字体缓存（避免每次调用都重复解析/提取）
_SC_FONTFILE_CACHE = {"path": None}


# 只有当 fc-match 解析到的 family 命中这些 CJK 简体中文字体时才可信。
# 关键：fc-match 找不到目标字体时不会报错/返回空，而是回退到“最接近”的字体
# （如 DejaVu / Droid），此时返回的 file 路径虽存在但**不是**简体中文字体——
# 直接用它 fontfile= 会导致“门”等简体字渲染成异常/缺字字形。
# 所以必须同时校验 family 名称，命中 CJK SC 才信任其 file 路径。
_SC_FAMILY_HINTS = (
    "noto sans cjk sc",
    "noto sans cjk",          # 含 SC 子字体的大集合
    "source han sans sc",
    "source han serif sc",
    "wenquanyi",               # 文泉驿（含简中）
    "wqy",
    "cjk",
    # 注意：不带 Droid Sans Fallback——实测其“门”(U+95E8) 为异常/次选字形，
    # 不可信任，避免再次把“门”渲染错。
)


def _fc_match_sc_font() -> str:
    """用 fontconfig 的 fc-match 动态解析 "Noto Sans CJK SC" 的真实字体路径。

    自适应 Debian/Alpine 等不同发行版，返回匹配字体的绝对路径；无 fc-match、
    匹配失败、或解析到的 family **不是 CJK 简体中文字体**时返回空串。
    通过缓存避免重复调用外部进程。

    核心防护：fc-match 找不到目标字体时会回退到任意“最接近”字体（如 DejaVu），
    其 file 路径存在但渲染不了简体中文，直接使用会导致“门”字异常。因此这里
    额外校验 family 名称，只信任命中 CJK 简体中文字体的结果。
    """
    if _SC_FONTFILE_CACHE["path"] is not None:
        return _SC_FONTFILE_CACHE["path"]
    try:
        # 一次拿回 file 与 family，family 用于校验是否真的是简体中文字体
        proc = subprocess.run(
            [_FCMATCH_CMD, "-f", "%{file}\t%{family}\n", "Noto Sans CJK SC"],
            capture_output=True, text=True, timeout=5,
        )
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            _SC_FONTFILE_CACHE["path"] = ""
            return ""
        parts = line[0].split("\t")
        file_path = parts[0].strip() if parts else ""
        family = (parts[1] if len(parts) > 1 else "").lower()
        if file_path and os.path.isfile(file_path) and any(h in family for h in _SC_FAMILY_HINTS):
            _SC_FONTFILE_CACHE["path"] = file_path
            return file_path
    except (OSError, subprocess.SubprocessError):
        pass
    _SC_FONTFILE_CACHE["path"] = ""
    return ""


def _extract_sc_face(ttc_path: str) -> str:
    """把 Noto CJK .ttc 集合里的 SC 简体中文字面提取成独立单字体 .ttf。

    drawtext 用 fontfile 引用 .ttc 时会默认加载第一个子字体（往往是 JP 日文字形），
    导致简体字"门"等渲染成日式/异常字形。方案 C：用 fontTools 把 SC face 单独提取成
    单字体 .ttf，彻底绕开 fontconfig 的 face 选择歧义。提取产物缓存在系统临时目录，
    一次提取后续复用。依赖 fonttools（backend/slice-worker 镜像均已安装）。
    """
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return ""
    cache_key = os.path.join(tempfile.gettempdir(),
                             "NotoSansCJKsc-Regular-" + str(abs(hash(ttc_path))) + ".ttf")
    if os.path.isfile(cache_key):
        return cache_key
    try:
        # 遍历 .ttc 集合里所有 face，挑出包含 "SC"/"Simplified" 的简体中文字面
        sc_index = None
        num_fonts = TTFont(ttc_path, fontNumber=0, lazy=True).reader.numFonts
        for i in range(num_fonts):
            try:
                f2 = TTFont(ttc_path, fontNumber=i, lazy=True)
                nm = f2["name"]
                combined = "".join(
                    (nm.getDebugName(n) or "").lower()
                    for n in (1, 4, 6) if nm.getDebugName(n)
                )
                # 精确匹配 "cjk sc" / "cjksc"（PostScript 名 notosanscjksc-Regular）。
                # 旧逻辑用 "sc" in combined 会误命中所有 face——因为 "cjk" 包含子串 "sc"
                # （c**sc**jk），导致永远选到第一个 face[0]=JP 而非真正的 SC face。
                if ("cjk sc" in combined or "cjksc" in combined
                        or "simplified chinese" in combined
                        or "simplified" in combined):
                    sc_index = i
                    break
            except Exception:
                continue
        if sc_index is None:
            return ""
        sc_font = TTFont(ttc_path, fontNumber=sc_index, lazy=True)
        sc_font.save(cache_key)
        return cache_key if os.path.isfile(cache_key) else ""
    except Exception:
        try:
            if os.path.isfile(cache_key):
                os.unlink(cache_key)
        except OSError:
            pass
        return ""


def _fontconfig_has_cjk_sc() -> bool:
    """判断 fontconfig 是否真的能解析到 CJK 简体中文字体（用于 font= 兜底）。

    仅检查 family 是否存在可用字体，不关心具体 file 路径；避免依赖写死的
    ttc 路径。命中则说明 ffmpeg 的 drawtext font= 可用 fontconfig 精确匹配。
    """
    try:
        proc = subprocess.run(
            [_FCMATCH_CMD, "-f", "%{family}\n", "Noto Sans CJK SC"],
            capture_output=True, text=True, timeout=5,
        )
        fam = ((proc.stdout or "").strip().splitlines() or [""])
        fam = fam[0].lower() if fam else ""
        return any(h in fam for h in _SC_FAMILY_HINTS)
    except (OSError, subprocess.SubprocessError):
        return False


def _resolve_drawtext_font() -> str:
    """返回 drawtext 的字体参数片段。

    B+C 结合方案：
      B) 优先用 fc-match 动态解析 "Noto Sans CJK SC" 真实字体路径（自适应 Debian/Alpine），
         命中即用 fontfile= 精确加载该字体（含正确的"门"字形）。
      C) fc-match 解析到的若是 .ttc 集合，则用 fontTools 提取 SC face 为单字体 .ttf
         再加载，彻底绕开 ttc 默认加载日文子字体、避免"门"渲染成日式/异常字形。
    兜底：单字体候选 / fontconfig font=Noto Sans CJK SC。
    """
    # ① B：fc-match 动态解析 Noto Sans CJK SC 真实路径
    sc_path = _fc_match_sc_font()
    if sc_path and os.path.isfile(sc_path):
        # ② C：若命中 .ttc 集合，提取 SC face 为单字体再加载（绕开 face 选择歧义）
        if sc_path.lower().endswith(".ttc"):
            single = _extract_sc_face(sc_path)
            if single:
                return f":fontfile={single}"
            # 提取失败（镜像未装 fontTools 等）：不能回退 fontfile=.ttc——
            # drawtext 加载 .ttc 默认取第一个子字体（JP 日文字形），"门"等简体字
            # 会渲染成日式/异常字形。改走 fontconfig font= 精确匹配 SC face。
            return ":font=Noto Sans CJK SC"
        return f":fontfile={sc_path}"
    # ③ 兜底 A：有 Noto CJK 集合时用 fontconfig font= 精确匹配简体中文
    if _fontconfig_has_cjk_sc() or any(os.path.isfile(f) for f in _TEXT_TTC_CANDIDATES):
        return ":font=Noto Sans CJK SC"
    # ④ 兜底 B：单字体文件
    _text_fontfile = next((f for f in _TEXT_SINGLE_FONT_CANDIDATES if os.path.isfile(f)), "")
    if _text_fontfile:
        return f":fontfile={_text_fontfile}"
    return ""


def _build_text_overlays_filter(text_overlays: list) -> str:
    """构造固定文字的 drawtext filter 链（叠加在视频上）。

    每个元素支持：
      - text: 文字内容（必填）
      - position: 位置（left 最左侧 / bottom-left 左下角 / top-right 右上角 等七位）
      - font_size: 字号（px，可选，默认 36）
      - color: 字体颜色（CSS #RRGGBB，可选，默认白）
      - border_color: 描边颜色（CSS #RRGGBB，可选，默认黑）
      - vertical: 是否竖排（仅 left 位置常用，可选，默认 False）
      - offset: 到边缘偏移（px，可选，默认 10）
    返回 drawtext filter 段（多个用逗号连接），空列表返回空串。
    """
    filters = []
    for ov in text_overlays:
        if not ov:
            continue
        text = ov.get("text") or ""
        if not text:
            continue
        position = (ov.get("position") or "bottom-left").lower()
        if position not in TEXT_OVERLAY_POSITIONS:
            position = "bottom-left"
        try:
            font_size = int(ov.get("font_size") or TEXT_OVERLAY_DEFAULT_FONT_SIZE)
        except (TypeError, ValueError):
            font_size = TEXT_OVERLAY_DEFAULT_FONT_SIZE
        font_size = max(12, min(200, font_size))
        try:
            offset = int(ov.get("offset") or TEXT_OVERLAY_DEFAULT_OFFSET)
        except (TypeError, ValueError):
            offset = TEXT_OVERLAY_DEFAULT_OFFSET
        offset = max(0, offset)
        vertical = bool(ov.get("vertical"))

        font_opt = _resolve_drawtext_font()
        # drawtext 的 fontcolor/border 用 0xRRGGBB 十六进制，最可靠。
        # 把 CSS 色值（#RRGGBB / #RGB）统一转为 0xRRGGBB。
        c_hex = _css_to_drawtext(ov.get("color") or TEXT_OVERLAY_DEFAULT_COLOR)
        b_hex = _css_to_drawtext(ov.get("border_color") or TEXT_OVERLAY_DEFAULT_BORDER_COLOR)

        x_tpl, y_tpl = TEXT_OVERLAY_POSITIONS[position]
        x_expr = x_tpl.replace("{O}", str(offset))
        y_expr = y_tpl.replace("{O}", str(offset))

        # 转义 drawtext 特殊字符（冒号/反斜杠/分号/单引号）
        esc = text.replace("\\", "\\\\").replace(":", "\\:").replace(";", "\\;").replace("'", "\\\\'")

        if vertical:
            # 竖排文字：把文字逐字符叠加（drawtext 无原生竖排，用多个 drawtext 逐字下排）
            chars = list(text)
            n = len(chars)
            sub_filters = []
            # 竖排整块高度 = 字符数 × 字号，需按整块高度垂直居中，
            # 否则 (h-th)/2 只居中了第一个字符，整列文字会整体偏上、无法居中。
            for k, ch in enumerate(chars):
                ch_esc = ch.replace("\\", "\\\\").replace(":", "\\:").replace(";", "\\;").replace("'", "\\\\'")
                sub_filters.append(
                    f"drawtext={font_opt}:text='{ch_esc}':fontcolor={c_hex}"
                    f":bordercolor={b_hex}:borderw=2:fontsize={font_size}"
                    f":x={x_expr}:y='(h-{n}*{font_size})/2+{k}*{font_size}'"
                )
            filters.append(",".join(sub_filters))
        else:
            filters.append(
                f"drawtext={font_opt}:text='{esc}':fontcolor={c_hex}"
                f":bordercolor={b_hex}:borderw=2:fontsize={font_size}"
                f":x={x_expr}:y={y_expr}"
            )
    return ",".join(filters)


def apply_text_overlays(src, out, text_overlays, threads=1, encoder="libx264"):
    """对成品视频执行一次固定文字叠加，产出新文件。

    text_overlays 为空或全无效时直接复制源文件，不做重编码。
    """
    valid = [o for o in (text_overlays or []) if o and (o.get("text") or "").strip()]
    if not valid:
        shutil.copy(src, out)
        return
    vf = _build_text_overlays_filter(valid)
    cmd = [
        "ffmpeg", "-y", "-threads", str(threads), "-i", src,
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a:0?",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def build_watermark_filter(wm: dict) -> str:
    """构造 ffmpeg 动态文字水印 filter（drawtext）。

    动态效果：
      - 水平缓慢移动（mod(2*t, w+tw)-tw）：文字从左侧缓缓滑向右侧，周期滚动
      - 透明度呼吸（alpha='0.4+0.3*sin(2*PI*t)'）：明暗变化，增强“动态”观感
      - 位置默认底部，可切换顶部
    """
    text = wm.get("text") or "Clip Workflow"
    font_size = int(wm.get("font_size") or 28)
    opacity = float(wm.get("opacity") or 0.5)
    position = (wm.get("position") or "bottom").lower()
    if position not in ("top", "bottom"):
        position = "bottom"

    opacity = max(0.05, min(1.0, opacity))
    font_size = max(12, min(120, font_size))

    # 字体：与固定文字共用同一套解析逻辑（优先单字体 .ttf/.otf；无单字体时用
    # fontconfig 的 font=Noto Sans CJK SC 精确匹配简体中文，避免 .ttc 集合默认加载
    # 第一个日文子字体，导致"门"等简体字渲染成日式/异常字形）。
    font_opt = _resolve_drawtext_font()

    if position == "top":
        y_expr = "40"
    else:
        y_expr = "h-th-40"

    # 转义 filter 特殊字符：后端已转义过冒号/逗号，这里再处理反斜杠与分号
    text = text.replace("\\", "\\\\").replace(";", "\\;")
    alpha = "'0.4+0.3*sin(2*PI*t)'"
    return (
        f"drawtext={font_opt}:text='{text}':fontcolor=white@{opacity:.2f}"
        f":fontsize={font_size}:x='mod(2*t\\,w+tw)-tw':y={y_expr}"
        f":alpha={alpha}"
    )


# ──────────────────────────────────────────────
# 字幕烧录（ASR 识别后叠加到成品视频）
# ──────────────────────────────────────────────

# 字幕字号（相对输出高度比例）
# 默认 0.22→FontSize 22，约占画面高度 5.5%~6%，比历史默认 0.30 进一步降低，
# 更显轻盈不遮挡画面。横屏/竖屏均清晰可读。用户可通过配置调大或调小。
SUBTITLE_FONT_RATIO = 0.22
# 字幕字间距（ASS Spacing，单位像素）。用户反馈原字体自带字距偏宽，默认 -1 进一步缩小让字幕文字更紧凑；
# 可通过配置项调大或调小。
SUBTITLE_SPACING = -1
# 字幕距底边距离（相对输出高度比例，越小越贴近画面底部；用户反馈原 0.08 偏高，调低到 0.05 更贴底）
SUBTITLE_BOTTOM_RATIO = 0.05

# 字幕样式：默认（白字黑边 + 半透明黑底）与自定义（可选字体/边框色，无底色）
SUBTITLE_STYLE_DEFAULT = "default"
SUBTITLE_STYLE_CUSTOM = "custom"


def css_hex_to_ass(color: Optional[str]) -> str:
    """把 CSS 十六进制颜色（#RRGGBB）转为 libass 使用的 &HBBGGRR 格式。

    例如 #FFFFFF → &H00FFFFFF，#FF0000 → &H000000FF。
    解析失败或为空时返回 None，由调用方回退到默认值。
    """
    if not color:
        return ""
    c = str(color).strip().lstrip("#")
    if len(c) == 3:  # 简写 #RGB
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return ""
    try:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
    except ValueError:
        return ""
    # libass 颜色为 &HAABBGGRR（高位 alpha，后续依次 BGR）
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _css_to_drawtext(color: Optional[str]) -> str:
    """把 CSS 十六进制颜色（#RRGGBB / #RGB）转为 drawtext 使用的 0xRRGGBB 格式。

    例如 #EDD736 → 0xEDD736，#fff → 0xFFFFFF。解析失败返回白色。
    """
    if not color:
        return "0xFFFFFF"
    c = str(color).strip().lstrip("#")
    if len(c) == 3:  # 简写 #RGB
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return "0xFFFFFF"
    try:
        int(c, 16)
    except ValueError:
        return "0xFFFFFF"
    return f"0x{c.upper()}"


def _parse_srt_timestamp(ts: str) -> float:
    """解析 SRT 时间戳 "HH:MM:SS,mmm" 为秒。"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _format_srt_timestamp(seconds: float) -> str:
    """把秒格式化为 SRT 时间戳 "HH:MM:SS,mmm"。"""
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000.0))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def read_srt(path: str) -> list[dict]:
    """解析 SRT 文件为有序字幕记录列表 [{start, end, text}]。"""
    records = []
    if not path or not os.path.isfile(path):
        return records
    try:
        with open(path, encoding="utf-8-sig") as f:
            content = f.read()
    except OSError:
        return records
    # 按空行分块
    blocks = [b for b in content.replace("\r\n", "\n").split("\n\n") if b.strip()]
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # 找到时间行（含 -->）
        time_idx = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                time_idx = i
                break
        if time_idx is None:
            continue
        time_line = lines[time_idx]
        try:
            left, right = time_line.split("-->", 1)
        except ValueError:
            continue
        start = _parse_srt_timestamp(left)
        end = _parse_srt_timestamp(right)
        text = " ".join(lines[time_idx + 1:])
        if end <= start:
            end = start + 1.0
        records.append({"start": start, "end": end, "text": text})
    return records


# 语音检测参数：判断"是否有人在说话"的静音阈值与最短静音长度。
# 小于该音量的区间视为静音（无人说话），字幕将不在静音期间显示。
# 阈值 -38dB、最短静音 0.5s（比原 -35dB/0.6s 更灵敏），能识别更多低音量停顿，
# 避免字幕"提早出现/延后消失"。
SILENCE_THRESHOLD_DB = -38.0
# 最短静音时长（秒）：小于该长度的短暂停顿不切断字幕，避免台词因句中换气被频繁闪断。
MIN_SILENCE_SECONDS = 0.5
# 语音窗口边界收缩（秒）：每条字幕在语音窗口基础上前后各收一点，
# 让字幕只贴着说话瞬间显示，不早现不晚退。
SPEECH_EDGE_PADDING = 0.15


def detect_speech_windows(video_path: str,
                         silence_threshold: float = SILENCE_THRESHOLD_DB,
                         min_silence: float = MIN_SILENCE_SECONDS) -> list[tuple]:
    """用 ffmpeg silencedetect 检测源视频的语音（非静音）区间。

    返回有序的 (start, end) 秒级区间列表，仅覆盖有人说话的时间段；
    失败或无法检测时返回 []（调用方回退为不限，即整段都视为说话）。
    """
    if not video_path or not os.path.isfile(video_path):
        return []
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", (f"silencedetect=noise={silence_threshold}dB:"
                f"d={min_silence}"),
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=3600)
    except Exception:
        return []
    out = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        return []

    silence_starts: list[float] = []
    silence_ends: list[float] = []
    for line in out.splitlines():
        if "silence_start:" in line:
            try:
                silence_starts.append(float(line.split("silence_start:")[1].strip()))
            except ValueError:
                pass
        elif "silence_end:" in line:
            try:
                silence_ends.append(float(line.split("silence_end:")[1].strip().split()[0]))
            except ValueError:
                pass
    if not silence_starts:
        # 没有检测到静音，说明全程都在说话 → 返回 None 表示"不裁剪"
        return []

    try:
        duration = ffprobe_duration(video_path)
    except Exception:
        duration = 0.0

    # 把静音区间取并集（ffmpeg 可能会输出相邻/重叠的静音段）
    silences = []
    for s, e in zip(silence_starts, silence_ends):
        silences.append((s, e))
    if len(silence_starts) > len(silence_ends):
        # 结尾静音一直持续到文件结束
        silences.append((silence_starts[-1], duration or silence_starts[-1] + 1.0))
    silences.sort()
    merged_sil = []
    for s, e in silences:
        if merged_sil and s <= merged_sil[-1][1]:
            merged_sil[-1] = (merged_sil[-1][0], max(merged_sil[-1][1], e))
        else:
            merged_sil.append([s, e])

    # 非静音区间 = 相邻静音之间的空隙
    speech = []
    cursor = 0.0
    for s, e in merged_sil:
        if s > cursor + 0.05:
            speech.append((cursor, s))
        cursor = max(cursor, e)
    if duration > 0 and cursor < duration - 0.05:
        speech.append((cursor, duration))
    return speech


def _trim_to_speech(start: float, end: float, speech_windows: list[tuple]) -> list[tuple]:
    """把一段 [start, end]（源时间）裁剪为与说话区间重叠的若干子区间。

    speech_windows 为空表示不裁剪（整段视为说话）。
    每条字幕在语音窗口基础上前后各收缩 SPEECH_EDGE_PADDING 秒，
    让字幕只贴着说话瞬间显示，避免提早出现/延后消失。
    """
    if not speech_windows:
        return [(start, end)]
    pad = SPEECH_EDGE_PADDING
    trimmed = []
    for ws, we in speech_windows:
        s = max(start, ws + pad)
        e = min(end, we - pad)
        if e - s >= 0.05:
            trimmed.append((s, e))
    return trimmed


def _filter_and_align_srt(records: list[dict], seg_start: float, seg_end: float,
                          offset: float, out: list[dict],
                          speech_windows: list[tuple] | None = None) -> None:
    """从源字幕中截取 [seg_start, seg_end] 区间，时间轴减去 seg_start 再叠加 offset，
    写入 out（用于多子段拼接时的连续时间轴对齐）。

    speech_windows: 可选，源时间坐标下的说话区间；传入后字幕仅在说话期间显示，
    跨越静音的字幕会被切分成多段，静音期间不再残留上一句字幕。
    """
    speech_windows = speech_windows or []
    for r in records:
        # 与片段有交集的字幕才保留；重叠部分做裁剪
        s = max(r["start"], seg_start)
        e = min(r["end"], seg_end)
        if e <= s:
            continue
        # 按说话区间裁剪：静音期间不显示字幕，避免字幕"一直挂在屏幕上"
        for ts, te in _trim_to_speech(s, e, speech_windows):
            if te - ts < 0.05:
                continue
            out.append({
                "start": (ts - seg_start) + offset,
                "end": (te - seg_start) + offset,
                "text": r["text"],
            })


def build_clip_subtitle(src_srt: str, segments: list[tuple], out_srt: str,
                        speech_windows: list[tuple] | None = None) -> str:
    """根据一个切片的源时间段列表，从源 SRT 截取并拼接出该切片对应的字幕文件。

    segments: 按拼接顺序排列的源时间段 [(start, end), ...]。
    生成的字幕时间轴从 0 开始（与成品视频一致）。返回 out_srt 路径。

    speech_windows: 可选，源时间坐标下的说话区间；传入后字幕仅在说话期间显示，
    静音/停顿期间字幕自动隐藏（不再"一直出现"）。
    """
    records = read_srt(src_srt)
    merged = []
    offset = 0.0
    for start, end in segments:
        _filter_and_align_srt(records, start, end, offset, merged, speech_windows)
        offset += max(0.0, end - start)
    # 排序并重新编号
    merged.sort(key=lambda r: r["start"])
    lines = []
    for i, r in enumerate(merged, start=1):
        lines.append(f"{i}\n{_format_srt_timestamp(r['start'])} --> {_format_srt_timestamp(r['end'])}\n{r['text']}\n")
    with open(out_srt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_srt


def burn_subtitle(video_in: str, subtitle_srt: str, video_out: str,
                  threads: int = 1, encoder: str = "libx264",
                  font_ratio: Optional[float] = None,
                  spacing: Optional[int] = None,
                  style: Optional[str] = None,
                  font_color: Optional[str] = None,
                  border_color: Optional[str] = None) -> None:
    """用 ffmpeg subtitles filter 把字幕烧录到成品视频。

    带字体、样式与描边，保证中文字幕清晰可读；输出为重新编码的视频。
    font_ratio: 字幕字号（相对输出视频高度的比例，不传用默认值 SUBTITLE_FONT_RATIO）。
    spacing: 字幕字间距（ASS Spacing 像素，不传用默认值 SUBTITLE_SPACING）。
    style: 字幕样式（SUBTITLE_STYLE_DEFAULT=白字黑边+半透明黑底 / SUBTITLE_STYLE_CUSTOM=可
        自定义字体色与边框色，且无底色）。不传用默认样式。
    font_color / border_color: 自定义样式的字体色/边框色（CSS 十六进制 #RRGGBB）。
    注意：字幕烧录涉及逐帧重编码 + subtitles filter，与硬件编码器（nvenc/videotoolbox）
    组合在某些环境会报 "Error while opening encoder"，故这里强制使用 libx264 软件编码，
    保证烧录稳定可靠（烧录通常单次、数据量不大，速度可接受）。
    """
    # 字幕烧录强制用 libx264 软件编码，避免硬件编码器 + subtitles filter 兼容问题
    encoder = "libx264"
    if not os.path.isfile(subtitle_srt) or os.path.getsize(subtitle_srt) == 0:
        # 无字幕内容时直接复制，避免无谓重编码
        shutil.copy(video_in, video_out)
        return

    # 字幕字号：未指定时用默认值（加大后的清晰字号），用户可在切片配置中调节
    font_ratio = font_ratio if font_ratio is not None else SUBTITLE_FONT_RATIO
    # 字幕字间距：未指定时用默认值（默认 0 更紧凑），用户可通过切片配置调节
    spacing = spacing if spacing is not None else SUBTITLE_SPACING

    # subtitles filter 需要能定位到字幕文件；路径含特殊字符时需转义冒号/逗号/引号
    srt_esc = (subtitle_srt.replace("\\", "\\\\")
               .replace(":", "\\:").replace(",", "\\,").replace("'", "\\\\'"))
    # 规范写法：subtitles=filename='<path>':force_style='...'
    # 不传 fontfile（不同 ffmpeg 版本对 subtitles filter 的 fontfile 选项支持不一），
    # 改用 libass 的 FontName + 系统 fontconfig（Worker 镜像装有 font-noto-cjk）匹配中文字体。
    # 默认样式：白字 + 黑色粗描边 + 半透明黑底（底色），字号按输出高度比例。
    style = style or SUBTITLE_STYLE_DEFAULT
    if style == SUBTITLE_STYLE_CUSTOM:
        # 自定义模式：可自由选择字体色与边框色，无底色（不使用 BorderStyle=3 的实底方框），
        # 以纯描边（BorderStyle=1）呈现，保证任何背景上字幕都清晰且不遮挡画面。
        primary_colour = css_hex_to_ass(font_color) or "&H00FFFFFF"
        outline_colour = css_hex_to_ass(border_color) or "&H00000000"
        back_colour = "&H00000000"  # 透明，去掉底色
        sub_style = (f"PrimaryColour={primary_colour},OutlineColour={outline_colour}"
                     f",BackColour={back_colour},BorderStyle=1,Outline=2,Shadow=0")
    else:
        primary_colour = "&H00FFFFFF"
        outline_colour = "&H00101010"
        back_colour = "&H80000000"
        sub_style = (f"PrimaryColour={primary_colour},OutlineColour={outline_colour}"
                     f",BackColour={back_colour},BorderStyle=3,Outline=2,Shadow=0")
    sub_filter = (
        f"subtitles=filename='{srt_esc}'"
        f":force_style='FontName=Noto Sans CJK SC,FontSize={font_ratio * 100:.0f}"
        f",{sub_style},MarginV={SUBTITLE_BOTTOM_RATIO * 1000:.0f}"
        f",Spacing={int(spacing)}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
        "-i", video_in,
        "-vf", sub_filter,
        "-map", "0:v:0", "-map", "0:a:0?",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", video_out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


# ──────────────────────────────────────────────
# 源视频字幕打码（去片源自带字幕）
# ──────────────────────────────────────────────

# 默认打码区域（相对输出视频宽/高比例）。字幕通常位于画面底部一条横带，
# 无需逐帧检测；固定区域 + SRT 时间轴驱动即可，仅在字幕出现时段生效。
# 注意：实际字幕位置可能不在底部（如居中偏下），开启时引擎会优先用 OpenCV 自动
# 检测字幕真实位置，检测失败才回退到下方默认比例。
SUBTITLE_MASK_WIDTH_RATIO = 0.9
SUBTITLE_MASK_HEIGHT_RATIO = 0.12
SUBTITLE_MASK_BOTTOM_RATIO = 0.02
# 默认打码样式
SUBTITLE_MASK_STYLE_DEFAULT = "delogo"
# 打码样式集合
SUBTITLE_MASK_STYLES = ("delogo", "mosaic", "blur", "fill")
# 马赛克缩放后的块大小（px），越大马赛克颗粒越粗
SUBTITLE_MASK_BLOCK = 8
# 模糊滤镜核大小（px）
SUBTITLE_MASK_BLUR_RADIUS = 12
# 自动检测字幕区域时最多采样的帧数（越多越稳，但越慢）
SUBTITLE_MASK_DETECT_MAX_FRAMES = 10
# 区域检测的"间歇性"打分参数：对话字幕是间歇出现（说话时才在屏），而固定水印/角标
# 几乎每一帧都在。检测时用"出现频率"区分二者，优先挑间歇出现的字幕带，避免被
# 恒定水印误导而打偏。出现频率越接近 PRESENCE_IDEAL 越加分，越接近 0（无内容）
# 或 1（恒定水印）越减分。
SUBTITLE_MASK_PRESENCE_IDEAL = 0.6
SUBTITLE_MASK_PRESENCE_SLOPE = 2.5
SUBTITLE_MASK_PRESENCE_MIN = 0.3
SUBTITLE_MASK_PRESENCE_MAX = 2.0


def _mask_text_clusters(mask):
    """向量化统计每行的"文字簇"数量（横向连续非零段）。

    字幕文字带区别于人物/背景的关键：一行内会分布多个相互分离的文字笔画簇
    （每个汉字一个簇，簇间有空隙），而人物服装/大块色块往往只有少数连续簇。
    mask: (H, W) 布尔掩码。返回长度为 H 的数组，值为每行文字簇个数。
    """
    import numpy as np
    starts = np.hstack([mask[:, :1], (mask[:, 1:] & ~mask[:, :-1])])
    return starts.sum(axis=1)


def detect_subtitle_region(video: str, srt: str = "") -> Optional[tuple[int, int, int, int]]:
    """用 OpenCV 从源视频采样帧自动检测字幕文字区域。

    返回 (x, y, w, h)，区域已按视频宽高裁剪到边界内；检测失败或 OpenCV
    不可用时返回 None（由调用方回退到固定比例区域）。

    采样时机：有 SRT 时取 SRT 出现的时刻（字幕在场），无 SRT 时均匀采样全程。

    检测原理（文字簇投票，针对金色/黄色等彩色字幕更可靠）：
      旧实现按 Canny 边缘密度找"最高密度横带"，在人物画面里容易被服装/背景的
      密集边缘误导而打偏（尤其金色/黄色字幕在复杂画面上边缘梯度弱）。
      本实现改用"颜色 + 文字簇"判别：
        - 颜色通道：金色/黄色 + 白色/浅色字幕（字幕最常见的两种配色）
        - 文字簇特征：一行内横向分布的独立文字笔画簇数量——字幕文字带总是
          有多个文字簇（每个字一个簇），而人物/装饰大块区域簇数很少。
        - 跨帧累积投票 + 位置偏下优先，对「底部/居中偏下/顶部」任意位置自适应。
    """
    width, height = ffprobe_size(video)
    if width <= 0 or height <= 0:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    # 确定采样时刻
    times = []
    records = read_srt(srt) if srt and os.path.isfile(srt) else []
    if records:
        sample = records[:SUBTITLE_MASK_DETECT_MAX_FRAMES]
        times = [max(0.0, (float(r["start"]) + float(r["end"])) / 2.0) for r in sample]
    else:
        dur = ffprobe_duration(video)
        if not dur or dur <= 0:
            return None
        n = min(SUBTITLE_MASK_DETECT_MAX_FRAMES, max(6, int(dur)))
        times = [dur * (i + 0.5) / n for i in range(n)]

    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        cluster_peak = np.zeros(height, dtype=np.float64)
        dens = np.zeros(height, dtype=np.float64)
        presence = np.zeros(height, dtype=np.float64)
        color_acc = np.zeros((height, width), dtype=np.float64)
        frames = 0
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            b = frame[:, :, 0].astype(np.int16)
            g = frame[:, :, 1].astype(np.int16)
            r = frame[:, :, 2].astype(np.int16)
            # 金色/黄色字幕（R 高、G 高、B 低，R/G 接近）
            gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & (g - b > 40) & (abs(r - g) < 110)
            # 白色/浅色字幕
            white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & (abs(g - b) < 45) & (abs(r - b) < 45)
            mask = gold | white
            dens += mask.sum(axis=1)
            cl = _mask_text_clusters(mask)
            # 逐帧最大值：即使字幕只在部分采样帧出现（间歇性对话字幕），其峰值也能被捕捉
            cluster_peak = np.maximum(cluster_peak, cl)
            # 该行在当前帧是否有文字簇内容（用于统计"出现频率"，区分间歇字幕/恒定水印）
            presence += (cl > 3).astype(np.float64)
            color_acc += mask.astype(np.float64)
            frames += 1
        if frames == 0:
            return None
        dens /= float(frames)
        presence /= float(frames)

        # 无实际内容的位置不计入文字簇（避免噪声）。
        # 用"峰值文字簇"而非均值做主信号：均值会被恒定水印/角标拉高（几乎每帧都在），
        # 而对话字幕是间歇的；峰值能捕捉到字幕真实出现时的密度。
        combo = cluster_peak.copy()
        combo[dens < 0.5] = 0.0
        k = np.ones(7, dtype=np.float64) / 7.0
        smooth = np.convolve(combo, k, mode="same")
        peak = float(smooth.max())
        if peak < 1.0:
            return None

        # 按文字簇强度找候选横带
        thr = peak * 0.3
        ys = np.where(smooth > thr)[0]
        if ys.size == 0:
            return None
        bands = []
        s = int(ys[0]); p = int(ys[0])
        for y in ys[1:]:
            if int(y) - p > 5:
                bands.append((s, p)); s = int(y)
            p = int(y)
        bands.append((s, p))

        # 打分：文字簇峰值 × 高度紧凑度 × 间歇性（出现频率） × 位置偏下优先
        candidates = []
        for y0, y1 in bands:
            h = y1 - y0 + 1
            val = float(smooth[y0:y1 + 1].max())
            compact = 1.0 if 15 <= h <= 130 else (0.4 if h < 15 else 0.15)
            # 出现频率越接近理想值（约 0.6，间歇性对话字幕）越加分，越接近 0（无内容）
            # 或 1（恒定水印/角标）越减分，从而把"对话字幕"从"固定水印"中区分出来。
            # 对"接近恒定（pr 很高）"做**二次方重罚**：恒定水印几乎每帧在场，其 pr≈1，
            # 若用线性惩罚不足以抵消其更高的文字簇强度，会导致区域被误选到水印上。
            pr = float(presence[y0:y1 + 1].mean())
            err = pr - SUBTITLE_MASK_PRESENCE_IDEAL
            # pr 越接近 1（恒定水印）惩罚越剧烈，越接近理想值（间歇字幕）越加分。
            if pr >= 0.85:
                dynamism = SUBTITLE_MASK_PRESENCE_MIN * 0.5   # 几乎恒定的水印：强烈减分
            elif pr <= 0.15:
                dynamism = SUBTITLE_MASK_PRESENCE_MIN * 0.5   # 几乎不出现：无意义
            else:
                dynamism = SUBTITLE_MASK_PRESENCE_MAX - \
                    err * err * SUBTITLE_MASK_PRESENCE_SLOPE * 3.0
            dynamism = max(SUBTITLE_MASK_PRESENCE_MIN * 0.5,
                           min(SUBTITLE_MASK_PRESENCE_MAX, dynamism))
            score = val * compact * dynamism
            if y0 > height * 0.3:
                score *= 1.3
            candidates.append((score, val, y0, y1, h, pr, dynamism))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        _, _, y0, y1, h, _, _ = candidates[0]

        # 上下扩展余量（向下更多，覆盖描边/换行/下延），确保 delogo 完整补平
        up = max(10, int(h * 0.3))
        down = max(16, int(h * 0.5))
        y0 = max(0, y0 - up)
        y1 = min(height - 1, y1 + down)

        # 横向范围
        col = color_acc[y0:y1 + 1, :].sum(axis=0)
        col_peak = float(col.max())
        if col_peak <= 1:
            return 0, y0, width, (y1 - y0)
        cols = np.where(col > col_peak * 0.1)[0]
        if cols.size == 0:
            return 0, y0, width, (y1 - y0)
        x0 = max(0, int(cols.min()) - 10)
        x1 = min(width - 1, int(cols.max()) + 10)
        return x0, y0, (x1 - x0), (y1 - y0)
    finally:
        if cap is not None:
            cap.release()


# 帧级（精细化）检测参数：判断"字幕/水印是否实际出现在区域内"的阈值与采样密度。
# 相比固定区域全程打码，开启 temporal 后只在内容出现的时段打码，画面其余时间零改动。
# 处理速度会变慢（需按时间采样判断内容在场与否），但更精细、画面更干净。
# 判断"在场"改用以字幕专属的"金色/黄色 + 白色/浅色"文字像素密度为信号（与区域/空间
# 检测一致），而非 Canny 边缘密度——因为复杂/繁忙画面在字幕横带内常年有高密度边缘，
# 用边缘会把"无字幕时段"也误判为在场，导致精细化失效（整段都被打码）。
# 字幕文字像素占区域比例超过该绝对下限视为"在场"（避免全黑/全白噪声帧）。
SUBTITLE_MASK_TEMPORAL_COLOR_RATIO = 0.003
# 捕获短句字幕的"噪声地板 → 峰值"相对下限（0~1，越小越能捕获低密度短句）。
SUBTITLE_MASK_TEMPORAL_LOW_FRAC = 0.25
# 阈值不低于噪声地板的该倍数，避免把背景噪声帧误判为在场。
SUBTITLE_MASK_TEMPORAL_NOISE_MULT = 2.0
# 帧级检测采样步长（秒）。越小定位越准，但越慢。
SUBTITLE_MASK_TEMPORAL_STEP = 0.5
# 相邻"在场"采样点合并成时间窗口的最小间距（秒）：小于该间距的相邻窗口合并。
SUBTITLE_MASK_TEMPORAL_MERGE_GAP = 0.6
# 打码窗口前后各扩展的余量（秒），避免字幕开头/结尾裁切不干净。
SUBTITLE_MASK_TEMPORAL_PAD = 0.25


def _low_percentile(values: list[float], p: float) -> float:
    """返回有序列表的低分位（如 25%）作为"背景噪声地板"的稳健估计。

    用线性插值在相邻元素间取分位；空列表返回 0。
    """
    if not values:
        return 0.0
    srt = sorted(values)
    n = len(srt)
    pos = p * (n - 1)
    lo = int(pos)
    hi = min(n - 1, lo + 1)
    frac = pos - lo
    return srt[lo] + (srt[hi] - srt[lo]) * frac


def _bimodal_threshold(values: list[float]) -> float:
    """Otsu 式双峰阈值：把密度值分成"背景"与"字幕"两簇，返回使簇内方差最小的分割点。

    若所有值几乎相等（单峰/无分割），回退到峰值的一小比例。
    """
    if not values:
        return 0.0
    lo, hi = min(values), max(values)
    if hi - lo < 1e-6:
        return hi
    # 归一化到 [0,1] 并分桶统计直方图
    nbins = min(256, max(16, len(values)))
    hist = [0] * nbins
    for v in values:
        idx = int((v - lo) / (hi - lo) * (nbins - 1) + 0.5)
        idx = max(0, min(nbins - 1, idx))
        hist[idx] += 1
    total = float(sum(hist))
    if total <= 0:
        return lo + (hi - lo) * 0.5
    # 前缀和/加权和
    sum_all = sum(v * hist[i] for i, v in enumerate((lo + (hi - lo) * i / (nbins - 1) for i in range(nbins))))
    w_b = 0.0
    s_b = 0.0
    best_var = -1.0
    best_t = lo
    for i in range(nbins):
        w_b += hist[i]
        if w_b <= 0:
            continue
        w_f = total - w_b
        if w_f <= 0:
            continue
        v = lo + (hi - lo) * i / (nbins - 1)
        s_b += v * hist[i]
        m_b = s_b / w_b
        m_f = (sum_all - s_b) / w_f
        var = w_b * w_f * (m_b - m_f) * (m_b - m_f)
        if var > best_var:
            best_var = var
            best_t = v
    return best_t


def detect_subtitle_temporal_windows(video: str, region: tuple[int, int, int, int],
                                     max_frames: int = 600) -> Optional[list[tuple]]:
    """帧级检测：判断字幕/水印在区域内实际出现的时间窗口列表。

    在指定 region (x, y, w, h) 内，按 SUBTITLE_MASK_TEMPORAL_STEP 步长扫描整段视频，
    对每个采样点判断区域内是否有文字/水印内容（区域内"金色/黄色 + 白色/浅色"字幕文字
    像素密度超过阈值即视为在场）。将连续的"在场"点合并为时间窗口，并前后各扩一点余量后返回。

    返回 [(start, end), ...] 秒级时间窗口（局部时间轴，从 0 开始）；
    检测失败或无字幕/水印时返回 None（由调用方回退为全程打码）。
    该方式不依赖 SRT，适用于任何片源字幕/水印的精细化打码。
    """
    x, y, w, h = region
    if w <= 0 or h <= 0:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    duration = ffprobe_duration(video)
    if not duration or duration <= 0:
        return None
    vw, vh = ffprobe_size(video)
    if vw <= 0 or vh <= 0:
        return None
    # 采样点数量封顶，防止超长视频采样过密导致过慢。
    step = SUBTITLE_MASK_TEMPORAL_STEP
    n = int(duration / step) + 1
    if n > max_frames:
        # 保持封顶采样数，等比例加大步长。
        step = duration / max_frames
        n = max_frames
    x0, x1 = max(0, x), min(x + w - 1, vw - 1)
    y0, y1 = max(0, y), min(y + h - 1, vh - 1)
    box_w = max(1, x1 - x0 + 1)
    box_h = max(1, y1 - y0 + 1)

    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        # 逐点采集：记录每个采样点区域内"金色/黄色 + 白色/浅色"字幕文字像素占比。
        # 字幕文字多为金色/黄色/白字，而画面背景/人物即便很杂也很少大片纯金/纯白像素，
        # 用该信号判断字幕是否在场远比 Canny 边缘可靠（边缘会被繁忙背景常年拉高）。
        present = []  # (t, score)
        for i in range(n):
            t = min(duration - 0.01, i * step)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            b = frame[y0:y1 + 1, x0:x1 + 1, 0].astype(np.int16)
            g = frame[y0:y1 + 1, x0:x1 + 1, 1].astype(np.int16)
            r = frame[y0:y1 + 1, x0:x1 + 1, 2].astype(np.int16)
            # 金色/黄色字幕（R 高、G 高、B 低，R/G 接近）
            gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & \
                   (g - b > 40) & (abs(r - g) < 110)
            # 白色/浅色字幕
            white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & \
                    (abs(g - b) < 45) & (abs(r - b) < 45)
            mask = gold | white
            density = float(mask.sum()) / float(box_w * box_h)
            present.append((t, density))
        if not present:
            return None
        scores = [s for _, s in present]
        peak = max(scores)
        if peak <= 1e-6:
            return None
        # 在场阈值：用"双峰(背景/字幕)分割"自适应确定，鲁棒地应对不同画面。
        # 密度值大致形成两个簇：背景帧(密度≈噪声地板，较低) 与 字幕帧(密度较高)。
        # 用 Otsu 式穷举找到使两类簇内方差最小的分割点，比固定倍率更稳：
        #   - 背景很杂时（噪声地板高），阈值自动抬高，避免把整段误判为在场；
        #   - 字幕较长/密度较高时，阈值自动落到字幕/背景的分界。
        thr = _bimodal_threshold(scores)
        # Otsu 只看两簇，当画面同时存在"长句字幕(高密度)"与"短句字幕(较低密度)"时，
        # 阈值会被高密度簇拉高，导致短句被漏检。额外用"背景噪声地板 + 峰值小比例"给出
        # 一个更低的下限，取两者较小值，从而也能捕获短句字幕；再保证不低于噪声地板
        # 的固定倍数，避免把背景噪声帧误判为在场。
        # 噪声地板用低分位（10%分位）估计，避免被"字幕在场帧"和"短句字幕"污染。
        noise_floor = _low_percentile(scores, 0.10)
        low_thr = noise_floor + (peak - noise_floor) * SUBTITLE_MASK_TEMPORAL_LOW_FRAC
        thr = min(thr, low_thr)
        thr = max(thr, noise_floor * SUBTITLE_MASK_TEMPORAL_NOISE_MULT)
        # 双峰分割可能偏低，额外保证不低于绝对下限（避免纯噪声帧被误判）。
        thr = max(thr, SUBTITLE_MASK_TEMPORAL_COLOR_RATIO)
        # 连续在场点 → 时间窗口（窗口内若个别点低于阈值但间距小，予以补齐）。
        in_on = False
        cur_start = 0.0
        last_on_t = -1e9
        windows = []
        for t, s in present:
            on = s >= thr
            if on:
                if not in_on:
                    cur_start = t
                    in_on = True
                last_on_t = t
            else:
                # 短暂掉线（间距小于 merge_gap）视为仍在场，保持窗口。
                if in_on and (t - last_on_t) <= SUBTITLE_MASK_TEMPORAL_MERGE_GAP:
                    continue
                if in_on:
                    windows.append((cur_start, last_on_t))
                    in_on = False
        if in_on:
            windows.append((cur_start, last_on_t))
        if not windows:
            return None
        # 合并间距过小的相邻窗口，并扩展余量、裁剪到时长内。
        merged = []
        for s, e in windows:
            if merged and s - merged[-1][1] <= SUBTITLE_MASK_TEMPORAL_MERGE_GAP:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append([s, e])
        result = []
        for s, e in merged:
            result.append((max(0.0, s - SUBTITLE_MASK_TEMPORAL_PAD),
                           min(duration, e + SUBTITLE_MASK_TEMPORAL_PAD)))
        return result
    finally:
        if cap is not None:
            cap.release()


# 空间精细化（仅字幕显示区域）检测参数：
# 在 temporal 已定位的每个时间窗口内，进一步找出该窗口字幕文字实际占用的
# 横向范围，只对这些小块区域打码，而不把整条横带都盖住。
# 单窗口内采样帧数上限（越多越稳，但越慢）。
SUBTITLE_MASK_SPATIAL_MAX_FRAMES = 5
# 子区域横向检测阈值（相对该窗口最大列内容得分的比例）。
SUBTITLE_MASK_SPATIAL_CONTRAST_RATIO = 0.12


def detect_subtitle_spatial_regions(video: str, region: tuple[int, int, int, int],
                                    temporal_windows: list[tuple]) -> Optional[list[tuple]]:
    """对每个时间窗口，在横带区域内进一步检测字幕文字实际占用的横向范围。

    region: 整体横带区域 (x, y, w, h)（源分辨率，temporal 检测所用同一区域）。
    temporal_windows: [(start, end), ...] 源时间窗口（秒）。

    返回 [(start, end, x, w), ...]：每个窗口对应的文字子区域 (x, w) 为该窗口
    字幕文字实际占用的横向范围（x 为绝对列坐标，w 为宽度，均源分辨率）。
    检测失败或无内容返回 None（由调用方回退为整条横带打码）。
    """
    x, y, w, h = region
    if w <= 0 or h <= 0 or not temporal_windows:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    vw, vh = ffprobe_size(video)
    if vw <= 0 or vh <= 0:
        return None
    x0, x1 = max(0, x), min(x + w - 1, vw - 1)
    y0, y1 = max(0, y), min(y + h - 1, vh - 1)
    band_w = max(1, x1 - x0 + 1)
    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        result = []
        for (s, e) in temporal_windows:
            # 时间窗口本身已含前后 PAD 余量（余量处可能无字幕），空间检测需在窗口
            # **内部**采样，避免采到无字幕的余量端点。收敛到窗口中心的核心区间。
            inner_s = s + SUBTITLE_MASK_TEMPORAL_PAD
            inner_e = e - SUBTITLE_MASK_TEMPORAL_PAD
            if inner_e <= inner_s:
                inner_s, inner_e = s, e
            mid = (inner_s + inner_e) / 2.0
            dur = max(0.05, inner_e - inner_s)
            # 采样帧数取上限（不因 dur 取整而缩水），保证能覆盖文字横向全貌。
            n = min(SUBTITLE_MASK_SPATIAL_MAX_FRAMES,
                    max(2, int(round(dur / 0.5)) + 1))
            times = [max(0.0, mid + (i - (n - 1) / 2.0) * (dur / max(1, n - 1)))
                     for i in range(n)]
            col_acc = np.zeros(band_w, dtype=np.float64)
            any_color = False
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                b = frame[y0:y1 + 1, x0:x1 + 1, 0].astype(np.int16)
                g = frame[y0:y1 + 1, x0:x1 + 1, 1].astype(np.int16)
                r = frame[y0:y1 + 1, x0:x1 + 1, 2].astype(np.int16)
                gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & \
                       (g - b > 40) & (abs(r - g) < 110)
                white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & \
                        (abs(g - b) < 45) & (abs(r - b) < 45)
                mask = gold | white
                if bool(mask.any()):
                    any_color = True
                col_acc += mask.sum(axis=0)
            if not any_color:
                # 该窗口未检出彩色字幕，用灰度边缘兜底定位文字横向范围。
                for t in times:
                    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        continue
                    gray = cv2.cvtColor(frame[y0:y1 + 1, x0:x1 + 1],
                                        cv2.COLOR_BGR2GRAY)
                    edges = cv2.Canny(gray, 60, 160)
                    col_acc += edges.sum(axis=0)
            peak = float(col_acc.max())
            if peak <= 1e-6:
                continue
            cols = np.where(col_acc > peak * SUBTITLE_MASK_SPATIAL_CONTRAST_RATIO)[0]
            if cols.size == 0:
                continue
            pad = max(8, int(w * 0.02))
            sx = max(0, x0 + int(cols.min()) - pad)
            ex = min(vw - 1, x0 + int(cols.max()) + pad)
            result.append((s, e, sx, ex - sx + 1))
        return result if result else None
    finally:
        if cap is not None:
            cap.release()


def _parse_subtitle_mask_config(raw: str | None) -> dict | None:
    """解析 --subtitle-mask 参数（JSON），未启用返回 None。"""
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    return cfg


def _mask_enable_expr(intervals: list[tuple]) -> str:
    """把区间列表合并为 enable 表达式。"""
    terms = [f"between(t,{s:.3f},{e:.3f})" for s, e in intervals]
    return "+".join(terms)


def _source_intervals_to_local_enable(src_intervals: list[tuple], seg_times: list[tuple]) -> str:
    """把源时间轴上的区间列表转换为切片局部时间轴（从 0 开始）的 enable 表达式。

    src_intervals: 源时间轴上的 [(start, end), ...]，如 SRT 字幕时段或帧级检测到的
        字幕/水印在场时段。
    seg_times: 按拼接顺序排列的源时间段 [(start, end), ...]，与 build_clip_subtitle 一致。
    返回局部 enable 表达式；该切片内无内容则返回 ""。
    """
    if not src_intervals:
        return ""
    intervals = []
    offset = 0.0
    for start, end in seg_times:
        for s0, e0 in src_intervals:
            s = max(s0, start)
            e = min(e0, end)
            if e > s:
                intervals.append((s - start + offset, e - start + offset))
        offset += max(0.0, end - start)
    if not intervals:
        return ""
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1] + 0.4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])
    return _mask_enable_expr(merged)


def _spatial_windows_to_local(src_windows: list[tuple], seg_times: list[tuple],
                              cfg: dict, width: int) -> list[tuple]:
    """把空间精细化窗口（源时间轴 + 源分辨率子区域）转换为切片局部坐标。

    src_windows: [(源_start, 源_end, 源_x, 源_w), ...]，源_x 为绝对列坐标（源分辨率）。
    seg_times: 切片源时间段 [(start, end), ...]。
    cfg: 打码配置（含 __detect_w/__detect_h 用于把源分辨率子区域等比缩放到切片分辨率）。
    width: 切片分辨率宽度。

    返回 [(局部_start, 局部_end, 局部_x, 局部_w), ...]，供 build_subtitle_mask_filter_multi 使用。
    """
    dw = int(cfg.get("__detect_w", 0))
    out = []
    for (s0, e0, sx, sw) in src_windows:
        if dw > 0 and dw != width:
            ax = int(round(sx * width / dw))
            aw = max(1, int(round(sw * width / dw)))
        else:
            ax = sx
            aw = sw
        if ax >= width or ax + aw <= 0:
            continue
        offset = 0.0
        for start, end in seg_times:
            ls = max(s0, start)
            le = min(e0, end)
            if le > ls:
                out.append((ls - start + offset, le - start + offset, ax, aw))
            offset += max(0.0, end - start)
    # 去重/合并相邻（同子区域）局部区间
    out.sort()
    result = []
    for s, e, x, w in out:
        if result and abs(result[-1][0] - s) < 0.01 and result[-1][2] == x and result[-1][3] == w:
            result[-1] = (result[-1][0], max(result[-1][1], e), x, w)
        else:
            result.append((s, e, x, w))
    return result


def build_subtitle_mask_enable(src_srt: str, seg_times: list[tuple]) -> str:
    """根据切片源时间段，从源 SRT 生成打码区间（局部时间轴，从 0 开始）。

    seg_times: 按拼接顺序排列的源时间段 [(start, end), ...]，与 build_clip_subtitle 一致。
    生成的区间时间轴与切片成品一致（从 0 开始），可直接用于 overlay/crop 的 enable。
    返回 "" 表示该切片内无字幕（无需打码）。
    """
    records = read_srt(src_srt)
    if not records:
        return ""
    return _source_intervals_to_local_enable(
        [(float(r["start"]), float(r["end"])) for r in records], seg_times)


def _subtitle_mask_area(cfg: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """根据配置计算打码区域 (x, y, w, h)，均为整数像素。

    支持两种定位方式：
      - 默认比例定位：底部横带，width_ratio / height_ratio / bottom_ratio 相对视频宽高。
      - 绝对定位：显式提供 x / y / width / height 时直接使用（可覆盖任意位置）。
    返回的区域会被裁剪回视频边界内。
    """
    if width <= 0 or height <= 0:
        return 0, 0, 0, 0

    def _f(key, default):
        try:
            v = cfg.get(key)
            if v is None or v == "":
                return default
            return float(v)
        except (TypeError, ValueError):
            return default

    if "x" in cfg and "y" in cfg and ("width" in cfg or "w" in cfg) and ("height" in cfg or "h" in cfg):
        x = int(_f("x", 0))
        y = int(_f("y", 0))
        w = int(_f("width", _f("w", 0)))
        h = int(_f("height", _f("h", 0)))
        # 若区域是按某个检测分辨率得到的，而当前切片分辨率不同（如去重/转场裁切），
        # 按比例等比缩放到当前分辨率，避免打码区域错位。
        dw = int(_f("__detect_w", 0))
        dh = int(_f("__detect_h", 0))
        if dw > 0 and dh > 0 and (dw != width or dh != height):
            x = int(round(x * width / dw))
            y = int(round(y * height / dh))
            w = int(round(w * width / dw))
            h = int(round(h * height / dh))
    else:
        w = int(width * _f("width_ratio", SUBTITLE_MASK_WIDTH_RATIO))
        h = int(height * _f("height_ratio", SUBTITLE_MASK_HEIGHT_RATIO))
        x = int((width - w) / 2)
        y = int(height - h - height * _f("bottom_ratio", SUBTITLE_MASK_BOTTOM_RATIO))

    # 边界裁剪
    if w <= 0 or h <= 0:
        return 0, 0, 0, 0
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = min(w, width - x)
    h = min(h, height - y)
    return x, y, w, h


def build_subtitle_mask_filter(cfg: dict, enable: str) -> str:
    """构造源字幕打码 filter_complex 片段（基于 [0:v] 输入，输出标签 [masked]）。

    打码样式：delogo（去字幕/去水印，智能插值，默认）/ mosaic（马赛克）/
    blur（模糊）/ fill（纯色块）。
    enable 非空时仅在字幕时段生效；为空表示全程打码。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT
    # 区域坐标在调用方预先按实际分辨率计算好，避免 filter 里写表达式
    x = int(cfg.get("__x", 0))
    y = int(cfg.get("__y", 0))
    w = int(cfg.get("__w", 0))
    h = int(cfg.get("__h", 0))
    if w <= 0 or h <= 0:
        return ""
    en = f":enable='{enable}'" if enable else ""

    if style == "delogo":
        # delogo 智能插值：用区域周围像素补平字幕，接近"去水印/去字幕"效果，视觉最自然。
        # 注：部分 ffmpeg 构建（如 Alpine 5.1）的 delogo 未编译 band 选项，这里只传 x/y/w/h。
        return f"[0:v]delogo=x={x}:y={y}:w={w}:h={h}{en}[vout]"
    if style == "mosaic":
        block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
        block = max(2, min(64, block))
        bw = max(1, w // block)
        bh = max(1, h // block)
        return (
            f"[0:v]split[src][sub];"
            f"[sub]crop={w}:{h}:{x}:{y},scale={bw}:{bh},scale={w}:{h}"
            f":flags=neighbor[masked];"
            f"[src][masked]overlay={x}:{y}{en}[vout]"
        )
    if style == "blur":
        radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
        radius = max(2, min(64, radius))
        return (
            f"[0:v]split[src][sub];"
            f"[sub]crop={w}:{h}:{x}:{y},boxblur={radius}:1[masked];"
            f"[src][masked]overlay={x}:{y}{en}[vout]"
        )
    # fill：纯色块直接盖住
    color = str(cfg.get("color") or "black")
    return f"[0:v]drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill{en}[vout]"


def build_subtitle_mask_filter_multi(cfg: dict, windows: list[tuple],
                                     y: int, h: int, width: int) -> str:
    """构造「仅字幕显示区域」多窗口打码 filter_complex（基于 [0:v]，输出 [vout]）。

    windows: [(local_s, local_e, x, w), ...]，局部时间轴（从 0 开始）与切片分辨率
        坐标；每个窗口只在各自时间段、各自横向子区域打码，而不是整条横带都盖住。
        x 为切片分辨率下的绝对列坐标。
    y/h: 横带区域在切片分辨率的纵向位置与高度（各窗口纵向一致，字幕单行高度固定）。
    width: 视频宽度（用于边界裁剪）。

    各样式实现：
      delogo 直接串联多个 delogo（各带 enable）；
      mosaic/blur 用多路 split+crop+overlay 分支链式叠加；
      fill 串联多个 drawbox（各带 enable）。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT

    def _clip(x, w, width):
        x = max(0, x)
        w = max(1, min(w, width - x))
        return x, w

    items = []
    for (s, e, x, w) in windows:
        x, w = _clip(x, w, width)
        if w <= 0:
            continue
        items.append((max(0.0, s), max(0.0, e), x, w))
    if not items:
        return ""

    # delogo 要求区域不贴边（需留至少 1px 边界用于周围像素插值），否则会报
    # "Logo area is outside of the frame" 导致转码失败；对 delogo 子区域做边界钳制。
    if style == "delogo":
        for i, (s, e, x, w) in enumerate(items):
            if x < 1:
                w = max(1, w - (1 - x))
                x = 1
            if x + w > width - 1:
                w = max(1, (width - 1) - x)
            items[i] = (s, e, x, w)
        chain = []
        for s, e, x, w in items:
            en = f"between(t,{s:.3f},{e:.3f})"
            chain.append(f"delogo=x={x}:y={y}:w={w}:h={h}:enable='{en}'")
        return "[0:v]" + ",".join(chain) + "[vout]"
    if style == "fill":
        color = str(cfg.get("color") or "black")
        chain = []
        for s, e, x, w in items:
            en = f"between(t,{s:.3f},{e:.3f})"
            chain.append(
                f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:enable='{en}'")
        return "[0:v]" + ",".join(chain) + "[vout]"
    # mosaic / blur：多路 split + 逐窗口 crop/scale + 链式 overlay
    block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
    block = max(2, min(64, block))
    radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
    radius = max(2, min(64, radius))
    n = len(items)
    split = f"[0:v]split={n + 1}[base]" + "".join(f"[w{i}]" for i in range(n)) + ";"
    parts = []
    for i, (s, e, x, w) in enumerate(items):
        if style == "mosaic":
            bw = max(1, w // block)
            bh = max(1, h // block)
            op = f"scale={bw}:{bh},scale={w}:{h}:flags=neighbor"
        else:
            op = f"boxblur={radius}:1"
        parts.append(f"[w{i}]crop={w}:{h}:{x}:{y},{op}[m{i}];")
    prev = "[base]"
    for i, (s, e, x, w) in enumerate(items):
        en = f"between(t,{s:.3f},{e:.3f})"
        if i < n - 1:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}:enable='{en}'[v{i + 1}];")
            prev = f"[v{i + 1}]"
        else:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}:enable='{en}'[vout]")
    return split + "".join(parts)


def apply_subtitle_mask(video_in: str, video_out: str, cfg: dict,
                        enable: str = "",
                        spatial_windows: Optional[list[tuple]] = None,
                        seg_times: Optional[list[tuple]] = None,
                        threads: int = 1, encoder: str = "libx264") -> None:
    """对成品视频执行一次源字幕打码（固定区域 + 时间轴驱动）。

    cfg: 打码配置 dict，至少含 enabled 与 style；区域定位字段（比例或绝对坐标）。
    enable: 打码时间轴表达式（局部时间坐标）。空字符串表示全程打码；
        由调用方根据切片源时间段从源 SRT 计算好传入（build_subtitle_mask_enable）。
    spatial_windows: 空间精细化（仅字幕显示区域打码）窗口列表，元素为
        (源_start, 源_end, 源_x, 源_w)。每个窗口只在各自时间段、各自字幕文字实际
        占用的横向子区域打码，而不是整条横带都盖住。提供了则以它为准（忽略 enable）。
    seg_times: 切片源时间段 [(start, end), ...]，用于把 spatial_windows 的源时间
        轴转换为切片局部时间轴。
    """
    width, height = ffprobe_size(video_in)
    if width <= 0 or height <= 0:
        # 拿不到分辨率时直接复制，避免生成非法 filter
        shutil.copy(video_in, video_out)
        return
    x, y, w, h = _subtitle_mask_area(cfg, width, height)
    if w <= 0 or h <= 0:
        shutil.copy(video_in, video_out)
        return
    # delogo 滤镜要求区域完全在画面内且不贴边（需留至少 1px 边界用于周围像素插值）：
    #   x>=1, y>=1, x+w<=width-1, y+h<=height-1。
    # 否则会报 "Logo area is outside of the frame" 导致整次转码失败。
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT
    if style == "delogo":
        if x < 1:
            w = max(1, w - (1 - x)); x = 1
        if y < 1:
            h = max(1, h - (1 - y)); y = 1
        if x + w > width - 1:
            w = max(1, (width - 1) - x)
        if y + h > height - 1:
            h = max(1, (height - 1) - y)
    cfg["__x"], cfg["__y"], cfg["__w"], cfg["__h"] = x, y, w, h

    # 空间精细化：仅对字幕文字实际占用的子区域打码。
    if spatial_windows:
        local = _spatial_windows_to_local(spatial_windows, seg_times or [], cfg, width)
        fc = build_subtitle_mask_filter_multi(cfg, local, y, h, width)
    else:
        fc = build_subtitle_mask_filter(cfg, enable)
    if not fc:
        shutil.copy(video_in, video_out)
        return

    cmd = [
        "ffmpeg", "-y", "-threads", str(threads), "-i", video_in,
        "-filter_complex", fc,
        "-map", "[vout]", "-map", "0:a:0?",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", video_out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("cutlist")
    parser.add_argument("output_dir")
    parser.add_argument("--mode", default="fast", choices=["fast", "dedupe", "scrub"])
    parser.add_argument("--intervals", default=None)
    parser.add_argument(
        "--cpu-percent",
        type=int,
        default=DEFAULT_CPU_PERCENT,
        help=f"CPU 资源分配比例 (%%，默认 {DEFAULT_CPU_PERCENT})，限制 ffmpeg 编码线程数",
    )
    parser.add_argument(
        "--watermark",
        default=None,
        help="动态文字水印配置 JSON（{\"text\":..., \"font_size\":..., \"opacity\":..., \"position\":...}）",
    )
    parser.add_argument(
        "--encoder",
        default=None,
        help="视频编码器（h264_nvenc/hevc_nvenc/h264_videotoolbox/hevc_videotoolbox/libx264），不填自动探测",
    )
    parser.add_argument(
        "--vert2horiz",
        default=None,
        help="竖屏转横屏预处理配置 JSON（{\"enabled\":true, \"mode\":\"fixed|dynamic\", ...}），切片前把竖屏素材转成横屏",
    )
    parser.add_argument(
        "--badges",
        default=None,
        help="图片角标配置 JSON 数组（[{\"path\":本地图片, \"position\":\"top-left\", \"width\":可选, \"offset\":可选偏移, \"opacity\":可选透明度}]），多角标全程叠加在视频指定位置",
    )
    parser.add_argument(
        "--badge-default-width",
        type=int,
        default=0,
        help="角标默认宽度（px，0=保持原图尺寸）；角标未单独设置 width 时生效",
    )
    parser.add_argument(
        "--text-overlays",
        default=None,
        help="固定文字角标配置 JSON 数组（[{\"text\":文字内容, \"position\":\"left|bottom-left|top-right\", \"font_size\":可选字号, \"color\":可选字体色, \"border_color\":可选描边色, \"vertical\":可选竖排, \"offset\":可选偏移}]），全程叠加在视频指定位置",
    )
    parser.add_argument(
        "--subtitle",
        default=None,
        help="源视频完整 SRT 字幕文件路径（可选）。开启后按每个切片的源时间段截取对应字幕并烧录到成品视频",
    )
    parser.add_argument(
        "--subtitle-font-ratio",
        type=float,
        default=None,
        help="字幕字号（相对输出视频高度的比例，可选，默认 0.20→FontSize 20，约占画面 5%）。越大字幕越清晰易读",
    )
    parser.add_argument(
        "--subtitle-spacing",
        type=int,
        default=None,
        help="字幕字间距（ASS Spacing 像素，可选，默认 0 更紧凑）。调小/为负可让字幕文字更紧凑，调大则字距变宽",
    )
    parser.add_argument(
        "--subtitle-style",
        default=None,
        help="字幕样式（default=白字黑边+半透明黑底；custom=自定义字体色/边框色且无底色，可选，默认 default）",
    )
    parser.add_argument(
        "--subtitle-color",
        default=None,
        help="自定义字幕样式下的字体颜色（CSS 十六进制 #RRGGBB，可选）",
    )
    parser.add_argument(
        "--subtitle-border-color",
        default=None,
        help="自定义字幕样式下的边框颜色（CSS 十六进制 #RRGGBB，可选）",
    )
    parser.add_argument(
        "--dedupe-config",
        default=None,
        help="去重档位配置 JSON（{\"preset\":\"light|standard|heavy\"}，默认 standard）。"
             "未传时去重模式回退到 preset=standard 的新默认效果",
    )
    parser.add_argument(
        "--subtitle-mask",
        default=None,
        help="源视频字幕打码配置 JSON（{\"enabled\":true, \"style\":\"delogo|mosaic|blur|fill\", \"width_ratio\":..., \"height_ratio\":..., \"bottom_ratio\":..., \"temporal\":bool, \"spatial\":bool, \"srt\":打码时间轴SRT路径}）。默认 delogo（去水印），开启后自动检测字幕位置。temporal=帧级精细化（只在出现时段打码），spatial=仅字幕显示区域打码（需 temporal 开启）。独立开关，仅打掉片源自带字幕",
    )
    args = parser.parse_args()

    threads = cpu_threads_for_percent(args.cpu_percent)
    print(f"CPU 分配: {args.cpu_percent}%% -> ffmpeg 线程数 {threads} (核数 {os.cpu_count() or '?'})", file=sys.stderr)

    encoder = detect_best_encoder(args.encoder)
    print(f"编码器: {encoder}", file=sys.stderr)

    if not os.path.isfile(args.source):
        print(f"Source video not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    # 竖屏转横屏预处理：开启时若素材为竖屏，先转成横屏再切片
    vert2horiz_cfg = parse_vert2horiz_config(args.vert2horiz)
    source_path = args.source
    if vert2horiz_cfg:
        source_path = apply_vert2horiz(source_path, vert2horiz_cfg)

    # 字幕字号：字号本身按输出画面高度比例自适应（约占画面 5%），
    # 横屏/竖屏无需区别对待；用户显式指定 --subtitle-font-ratio 时以用户值为准，
    # 未指定时 burn_subtitle 内部统一用 SUBTITLE_FONT_RATIO。
    subtitle_font_ratio = args.subtitle_font_ratio
    # 字幕字间距：用户显式指定 --subtitle-spacing 时以用户值为准，未指定时用默认值
    subtitle_spacing = args.subtitle_spacing

    os.makedirs(args.output_dir, exist_ok=True)
    cuts = read_cutlist(args.cutlist)
    intervals = read_intervals(args.intervals) if args.mode == "scrub" else []

    # 一键切片整片兜底：候选片段为空时，后端会下发空 cutlist。
    # 非 scrub 模式下这里回退为「整片切片」，保证自动化流程一定出片。
    if not cuts and args.mode != "scrub":
        dur = ffprobe_duration(args.source)
        if dur and dur > 0:
            cuts = [(0.0, dur, "clip_01")]
            print("候选片段为空，一键切片回退为整片切片", file=sys.stderr)

    if args.mode == "scrub":
        segments = subtract_intervals(cuts, intervals)
    else:
        segments = [(s, e, name, idx) for idx, (s, e, name) in enumerate(cuts)]

    if not segments:
        print("PROGRESS:100")
        print("No valid cut segments found", file=sys.stderr)
        # 清理竖屏转横屏临时文件
        if source_path != args.source and os.path.isfile(source_path):
            try:
                os.unlink(source_path)
            except OSError:
                pass
        sys.exit(0)

    vf = None
    af = None
    if args.mode == "dedupe":
        # 去重模式：默认采用 standard 档（含老电视质感的完整四层去重），
        # 可通过 --dedupe-config 的 preset 字段指定 light/standard/heavy。
        preset = "standard"
        if args.dedupe_config:
            try:
                dedupe_cfg = json.loads(args.dedupe_config)
            except (ValueError, TypeError):
                dedupe_cfg = {}
            if isinstance(dedupe_cfg, dict) and dedupe_cfg.get("preset"):
                preset = str(dedupe_cfg["preset"]).lower()
        w, h = ffprobe_resolution(source_path)
        vf, af = build_dedupe_filter(preset, width=w, height=h)
        print(f"去重档位: {preset}", file=sys.stderr)

    # 动态文字水印：开启后在去重/普通滤镜基础上叠加 drawtext
    watermark = None
    if args.watermark:
        try:
            watermark = json.loads(args.watermark)
        except (ValueError, TypeError):
            watermark = None
    if watermark:
        wm_filter = build_watermark_filter(watermark)
        vf = f"{vf},{wm_filter}" if vf else wm_filter
        print(f"动态文字水印已开启: {watermark.get('text', '')}", file=sys.stderr)

    # 图片角标：解析并缓存本地图片路径（Worker/后端已下载到本地）
    badges = []
    if args.badges:
        try:
            raw_badges = json.loads(args.badges)
            if isinstance(raw_badges, list):
                badges = raw_badges
        except (ValueError, TypeError):
            badges = []
    if badges:
        valid_paths = [b.get("path") for b in badges if b.get("path") and os.path.isfile(b["path"])]
        print(f"图片角标已开启: {len(valid_paths)} 个", file=sys.stderr)

    # 固定文字角标：解析并准备绘制（最左侧/左下角/右上角等位置）
    text_overlays = []
    if args.text_overlays:
        try:
            raw_texts = json.loads(args.text_overlays)
            if isinstance(raw_texts, list):
                text_overlays = [o for o in raw_texts if isinstance(o, dict)]
        except (ValueError, TypeError):
            text_overlays = []
    if text_overlays:
        print(f"固定文字角标已开启: {len(text_overlays)} 条", file=sys.stderr)

    # 源视频字幕打码：打掉片源自带字幕（独立开关，不依赖 ASR 字幕烧录）。
    # 时间轴优先用 --subtitle-mask 里携带的 srt，其次回退到 args.subtitle。
    subtitle_mask = _parse_subtitle_mask_config(args.subtitle_mask)
    if subtitle_mask:
        if not subtitle_mask.get("srt") and args.subtitle:
            subtitle_mask["srt"] = args.subtitle
        style = subtitle_mask.get("style") or SUBTITLE_MASK_STYLE_DEFAULT
        temporal = bool(subtitle_mask.get("temporal"))
        spatial = bool(subtitle_mask.get("spatial"))
        print(f"源字幕打码已开启: style={style}, temporal={temporal}, spatial={spatial}", file=sys.stderr)
        if not temporal:
            print("提示: temporal=false 会按检测到的字幕区域全程打码（字幕/水印不在的时段也会被马赛克）。"
                  "若字幕只在几帧出现，建议开启 temporal=true 启用帧级检测。", file=sys.stderr)
        # 自动检测字幕真实位置：字幕常在居中偏下而非底部，固定底部横带会打偏。
        # 用 OpenCV 在字幕出现的时刻采样帧，检测文字横带位置；检测成功则覆盖默认区域。
        detect_srt = subtitle_mask.get("srt") or ""
        detected = detect_subtitle_region(source_path, detect_srt)
        if detected:
            dx, dy, dw, dh = detected
            subtitle_mask["x"] = dx
            subtitle_mask["y"] = dy
            subtitle_mask["width"] = dw
            subtitle_mask["height"] = dh
            # 记录检测时的分辨率，供 apply_subtitle_mask 按切片分辨率等比缩放
            detect_w, detect_h = ffprobe_size(source_path)
            subtitle_mask["__detect_w"] = detect_w
            subtitle_mask["__detect_h"] = detect_h
            print(f"源字幕打码自动定位: ({dx},{dy},{dw},{dh}) @ {detect_w}x{detect_h}", file=sys.stderr)
        else:
            print("源字幕打码自动定位失败，回退默认区域（底部横带）", file=sys.stderr)

        # 精细化（temporal）模式：在检测出的区域内按时间采样判断字幕/水印实际
        # 在哪些时段出现，只在出现时打码，其余画面零改动。不依赖 SRT，适用于
        # 任意片源字幕/水印；检测失败时回退到 SRT 时间轴或全程打码。
        if subtitle_mask.get("temporal"):
            region = (int(subtitle_mask.get("x", 0)), int(subtitle_mask.get("y", 0)),
                      int(subtitle_mask.get("width", 0)), int(subtitle_mask.get("height", 0)))
            # 优先用已检测到的实际区域；若区域检测失败，用默认比例区域兜底。
            if region[2] <= 0 or region[3] <= 0:
                w0, h0 = ffprobe_size(source_path)
                region = _subtitle_mask_area(subtitle_mask, w0, h0)
            tw = detect_subtitle_temporal_windows(source_path, region)
            if tw:
                subtitle_mask["__temporal_windows"] = tw
                print(f"源字幕打码帧级检测: {len(tw)} 个出现时段", file=sys.stderr)
                # 空间精细化（仅字幕显示区域打码）：在每个出现时段内进一步检测
                # 字幕文字实际占用的横向范围，只对这些小块区域打码（需 temporal 开启）。
                if subtitle_mask.get("spatial"):
                    spatial = detect_subtitle_spatial_regions(source_path, region, tw)
                    if spatial:
                        subtitle_mask["__spatial_windows"] = spatial
                        print(f"源字幕打码空间精细化: {len(spatial)} 个文字子区域", file=sys.stderr)
                    else:
                        print("源字幕打码空间精细化未命中，回退整条横带打码", file=sys.stderr)
            else:
                print("源字幕打码帧级检测未命中，回退 SRT 时间轴或全程打码", file=sys.stderr)

    # Group segments by original cut index for scrub mode.
    groups = {}
    for start, end, name, idx in segments:
        groups.setdefault(idx, []).append((start, end, name))

    # 字幕开启时，预计算源视频的语音（非静音）区间，用于"只在说话时显示字幕"。
    # 静音/停顿期间字幕自动隐藏，避免字幕一直挂在屏幕上。
    # detect_speech_windows 失败返回 [] 时回退为整段都显示，不影响烧录。
    speech_windows = detect_speech_windows(source_path) if args.subtitle else []

    try:
        outputs = []
        total = len(groups)
        processed = 0
        for idx in sorted(groups):
            group = groups[idx]
            name = safe_name(group[0][2])
            out_path = os.path.join(args.output_dir, name)
            parts = []
            with tempfile.TemporaryDirectory() as tmp:
                for i, (start, end, _) in enumerate(group):
                    part = os.path.join(tmp, f"part_{i}.mp4")
                    slice_segment(source_path, start, end, part, vf=vf, af=af, threads=threads, encoder=encoder)
                    parts.append(part)
                concat_segments(parts, out_path, threads=threads, encoder=encoder)
                seg_times = [(s, e) for s, e, _ in group]
                # 源字幕打码：打掉片源自带字幕（在烧录自己的新字幕之前）
                if subtitle_mask:
                    mask_out = out_path + ".masked.mp4"
                    # 精细化（temporal）模式：优先用帧级检测到的"字幕/水印出现时段"，
                    # 把源时间轴窗口转为切片局部时间轴，只在出现时打码。
                    tw = subtitle_mask.get("__temporal_windows") or []
                    # 空间精细化（仅字幕显示区域打码）：在每个出现时段内只对字幕文字
                    # 实际占用的横向子区域打码，而不把整条横带都盖住（需 temporal 开启）。
                    spatial = subtitle_mask.get("__spatial_windows") or []
                    # 普通/快速模式（temporal 与 spatial 均关闭）：在检测出的字幕区域
                    # 全程（至始至终）打码，不再按 SRT 时间轴驱动——否则 SRT 间隙/缺失会
                    # 导致"有时能打有时不能打"，且不符合"区域至始至终盖住"的预期。
                    if spatial:
                        apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                            spatial_windows=spatial,
                                            seg_times=seg_times,
                                            threads=threads, encoder=encoder)
                        os.replace(mask_out, out_path)
                    elif tw:
                        mask_enable = _source_intervals_to_local_enable(tw, seg_times)
                        # 精细化：仅在字幕出现时段打码；该切片内无字幕出现则不打码。
                        if mask_enable:
                            apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                                enable=mask_enable,
                                                threads=threads, encoder=encoder)
                            os.replace(mask_out, out_path)
                    else:
                        # 普通/快速模式：检测区域内全程打码（至始至终）。
                        apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                            enable="",
                                            threads=threads, encoder=encoder)
                        os.replace(mask_out, out_path)
                # 字幕烧录：开启后按该切片的源时间段从源 SRT 截取并烧录到成品
                if args.subtitle:
                    sub_srt = os.path.join(tmp, "clip_subtitle.srt")
                    build_clip_subtitle(args.subtitle, seg_times, sub_srt, speech_windows)
                    sub_out = out_path + ".sub.mp4"
                    burn_subtitle(out_path, sub_srt, sub_out, threads=threads, encoder=encoder,
                                  font_ratio=subtitle_font_ratio,
                                  spacing=subtitle_spacing,
                                  style=args.subtitle_style,
                                  font_color=args.subtitle_color,
                                  border_color=args.subtitle_border_color)
                    os.replace(sub_out, out_path)
            # 图片角标：切片完成后在成品上叠加角标（全程覆盖视频指定位置）
            if badges:
                badge_out = out_path + ".badge.mp4"
                apply_badges(
                    out_path, badge_out, badges,
                    threads=threads, encoder=encoder,
                    default_width=args.badge_default_width,
                )
                os.replace(badge_out, out_path)
            # 固定文字角标：在图片角标之后再叠加文字（文字常叠在角标之上层）
            if text_overlays:
                txt_out = out_path + ".textov.mp4"
                apply_text_overlays(
                    out_path, txt_out, text_overlays,
                    threads=threads, encoder=encoder,
                )
                os.replace(txt_out, out_path)
            duration = ffprobe_duration(out_path)
            outputs.append((name, duration))
            processed += 1
            print(f"PROGRESS:{int(processed * 100 / total)}")
            print(f"OUTPUT:{name}:{duration:.3f}")

        print("PROGRESS:100")
    finally:
        # 清理竖屏转横屏临时文件
        if source_path != args.source and os.path.isfile(source_path):
            try:
                os.unlink(source_path)
            except OSError:
                pass


def parse_vert2horiz_config(raw: str) -> dict | None:
    """解析 --vert2horiz 参数（后端下发的 JSON 配置），未启用返回 None。"""
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    return cfg


def apply_vert2horiz(source: str, cfg: dict) -> str:
    """若素材为竖屏，先执行竖屏转横屏预处理，返回转码后的临时文件路径。

    支持 fixed（固定裁切，快速）与 dynamic（动态人脸跟踪）两种模式；
    横屏/方形素材不做处理，直接返回原路径。
    """
    if vert2horiz_crop is None:
        raise RuntimeError(
            "竖屏转横屏已开启，但未安装 OpenCV（vert2horiz_crop 依赖）。"
            "请安装 opencv-python-headless 后重试。"
        )
    src_w, src_h, fps, _total = vert2horiz_crop.get_video_info(source)
    # 仅竖屏素材需要转换（高 > 宽）
    if src_h <= src_w:
        print(f"素材为横屏/方形（{src_w}x{src_h}），跳过竖屏转横屏预处理", file=sys.stderr)
        return source

    mode = (cfg.get("mode") or "fixed").lower()
    if mode not in ("fixed", "dynamic"):
        mode = "fixed"
    ratio = float(cfg.get("ratio") or (9 / 16))
    output_size = cfg.get("output_size") or "1280x720"
    detect_interval = int(cfg.get("detect_interval") or 2)
    smooth_window = int(cfg.get("smooth_window") or 15)
    # 最小移动阈值（源画面像素）：越大越平稳、越小越跟手；默认取引擎侧默认值
    min_step = int(cfg.get("min_step") or vert2horiz_crop.MIN_STEP_DEFAULT)
    # 人脸舒适区边距（占人脸高度的比例）：人脸头像大部分仍在画面内时保持窗口不动，
    # 抑制频繁移动造成的抖动；默认取引擎侧默认值
    face_margin = float(cfg.get("face_margin") or vert2horiz_crop.FACE_MARGIN_DEFAULT)

    # 输出路径加进程唯一后缀：同一任务可能被多个 Worker 并发认领执行（长任务
    # 超过 Redis 认领超时后被重新认领），若多个引擎进程写同一固定路径会互相
    # 覆盖导致文件损坏（moov atom missing）。各进程写各自文件，互不干扰。
    out_path = f"{source}.vert2horiz-{os.getpid()}.mp4"
    print(f"检测到竖屏素材（{src_w}x{src_h}），执行竖屏转横屏预处理（mode={mode}）…", file=sys.stderr)

    # 人脸检测器在 vert2horiz_crop 内部创建（动态/固定共用）
    detector = vert2horiz_crop.FaceDetector()

    if mode == "dynamic":
        faces, _positions = vert2horiz_crop.analyze_faces(
            source,
            detect_interval=detect_interval,
            smooth_window=smooth_window,
            detector=detector,
        )
        crop_params = vert2horiz_crop.generate_dynamic_crop_params(
            faces, src_w, src_h, ratio, min_step=min_step, face_margin=face_margin
        )
        vert2horiz_crop.apply_dynamic_crop(
            source, out_path, crop_params, fps, output_size, min_step=min_step
        )
    else:
        crop_params = vert2horiz_crop.generate_fixed_crop_params(
            detector, source, src_w, src_h, ratio
        )
        vert2horiz_crop.apply_fixed_crop(source, out_path, crop_params, output_size)

    print(f"竖屏转横屏预处理完成: {out_path}（{output_size}）", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    main()
