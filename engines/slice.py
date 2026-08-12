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


def _fc_match_sc_font() -> str:
    """用 fontconfig 的 fc-match 动态解析 "Noto Sans CJK SC" 的真实字体路径。

    自适应 Debian/Alpine 等不同发行版，返回匹配字体的绝对路径；无 fc-match 或
    匹配失败时返回空串。通过缓存避免重复调用外部进程。
    """
    if _SC_FONTFILE_CACHE["path"] is not None:
        return _SC_FONTFILE_CACHE["path"]
    try:
        proc = subprocess.run(
            [_FCMATCH_CMD, "-f", "%{file}\n", "Noto Sans CJK SC"],
            capture_output=True, text=True, timeout=5,
        )
        path = (proc.stdout or "").strip().splitlines()
        if path and os.path.isfile(path[0]):
            _SC_FONTFILE_CACHE["path"] = path[0]
            return path[0]
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
                if "sc" in combined or "simplified" in combined:
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
    if any(os.path.isfile(f) for f in _TEXT_TTC_CANDIDATES):
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
# 字幕字间距（ASS Spacing，单位像素）。默认 0 更紧凑；用户反馈原字体自带字距偏宽，
# 调小（如 -1）让字幕文字更紧凑；通过配置项开放调节。
SUBTITLE_SPACING = 0
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
        vf = "setpts=PTS/1.04,eq=saturation=0.95:brightness=0.01,unsharp=5:5:0.8:5:5:0.0"
        af = "atempo=1.04"

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
                # 字幕烧录：开启后按该切片的源时间段从源 SRT 截取并烧录到成品
                if args.subtitle:
                    sub_srt = os.path.join(tmp, "clip_subtitle.srt")
                    seg_times = [(s, e) for s, e, _ in group]
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
