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


def slice_segment(src, start, end, out, vf=None, af=None, threads=1):
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
    ]
    if vf:
        cmd += ["-vf", vf]
    if af:
        cmd += ["-af", af]
    cmd.append(out)
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def concat_segments(parts, out, threads=1):
    if len(parts) == 1:
        # 单段时无需重新编码（水印已在 slice_segment 阶段叠加）
        shutil.move(parts[0], out)
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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        out,
    ]
    run_ffmpeg(cmd, threads=threads)


def safe_name(name: str) -> str:
    name = os.path.basename(name)
    if not name.endswith(".mp4"):
        name += ".mp4"
    return name


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
    args = parser.parse_args()

    threads = cpu_threads_for_percent(args.cpu_percent)
    print(f"CPU 分配: {args.cpu_percent}%% -> ffmpeg 线程数 {threads} (核数 {os.cpu_count() or '?'})", file=sys.stderr)

    if not os.path.isfile(args.source):
        print(f"Source video not found: {args.source}", file=sys.stderr)
        sys.exit(1)

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

    # Group segments by original cut index for scrub mode.
    groups = {}
    for start, end, name, idx in segments:
        groups.setdefault(idx, []).append((start, end, name))

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
                slice_segment(args.source, start, end, part, vf=vf, af=af, threads=threads)
                parts.append(part)
            concat_segments(parts, out_path, threads=threads)
        duration = ffprobe_duration(out_path)
        outputs.append((name, duration))
        processed += 1
        print(f"PROGRESS:{int(processed * 100 / total)}")
        print(f"OUTPUT:{name}:{duration:.3f}")

    print("PROGRESS:100")


if __name__ == "__main__":
    main()
