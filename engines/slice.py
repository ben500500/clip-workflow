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
BADGE_POSITIONS = {
    # 左上 / 中上 / 右上 / 左下 / 中下 / 右下
    "top-left":      ("10", "10"),
    "top-center":    ("(W-w)/2", "10"),
    "top-right":     ("W-w-10", "10"),
    "bottom-left":   ("10", "H-h-10"),
    "bottom-center": ("(W-w)/2", "H-h-10"),
    "bottom-right":  ("W-w-10", "H-h-10"),
}


def build_badges_overlay_args(badges: list, threads: int, encoder: str) -> list[str]:
    """构造在成品视频上叠加多角标的 ffmpeg 命令参数（-filter_complex 多输入）。

    返回完整的 ffmpeg 参数（含 -y、主视频输入、各角标 -i、filter_complex、
    overlay 叠加、编码输出到 -o）。调用方只需追加输出路径。
    角标全程叠加在视频指定位置上（不随时间消失），支持多角标。
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
        width = int(badge.get("width") or 0)
        scale = f"scale={width}:-1" if width > 0 else "null"
        parts.append(f"[{i + 1}:v]{scale},format=rgba[badge{i}]")

    current = "[0:v]"
    for i in range(num):
        position = (valid[i].get("position") or "top-left").lower()
        if position not in BADGE_POSITIONS:
            position = "top-left"
        x_expr, y_expr = BADGE_POSITIONS[position]
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


def apply_badges(src, out, badges, threads=1, encoder="libx264"):
    """对成品视频执行一次角标 overlay 叠加，产出新文件。"""
    badge_args = build_badges_overlay_args(badges, threads, encoder)
    if not badge_args:
        # 无有效角标，直接复制
        shutil.copy(src, out)
        return
    cmd = ["ffmpeg", "-y", "-threads", str(threads), "-i", src] + badge_args + [out]
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

    # 字体：优先中文字体（若容器内安装了），否则用 DejaVuSans（容器内通常自带）
    font_candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    fontfile = next((f for f in font_candidates if os.path.isfile(f)), "")
    font_opt = f":fontfile={fontfile}" if fontfile else ""

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
        help="图片角标配置 JSON 数组（[{\"path\":本地图片, \"position\":\"top-left\", \"width\":可选}]），多角标全程叠加在视频指定位置",
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

    # Group segments by original cut index for scrub mode.
    groups = {}
    for start, end, name, idx in segments:
        groups.setdefault(idx, []).append((start, end, name))

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
            # 图片角标：切片完成后在成品上叠加角标（全程覆盖视频指定位置）
            if badges:
                badge_out = out_path + ".badge.mp4"
                apply_badges(out_path, badge_out, badges, threads=threads, encoder=encoder)
                os.replace(badge_out, out_path)
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
            faces, src_w, src_h, ratio
        )
        vert2horiz_crop.apply_dynamic_crop(source, out_path, crop_params, fps, output_size)
    else:
        crop_params = vert2horiz_crop.generate_fixed_crop_params(
            detector, source, src_w, src_h, ratio
        )
        vert2horiz_crop.apply_fixed_crop(source, out_path, crop_params, output_size)

    print(f"竖屏转横屏预处理完成: {out_path}（{output_size}）", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    main()
