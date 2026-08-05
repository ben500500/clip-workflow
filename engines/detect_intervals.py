#!/usr/bin/env python3
"""Interval detection engine using ffmpeg filters.

Modes:
  credits  - trailing black segments (blackdetect)
  static   - frozen frames (freezedetect)
  watermark/custom - no generic detector, returns empty result

Prints the path of a JSON result file to stdout. The JSON contains
{"intervals": [...]} with start_time/end_time/confidence/label fields.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile


DEFAULTS = {
    "scan_window": 6.0,
    "frame_interval": 0.5,
    "static_threshold": 5,
    "min_static_duration": 9,
}


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


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


def run_ffmpeg_detect(video, vf):
    cmd = [
        "ffmpeg", "-i", video, "-vf", vf, "-an", "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    return proc.stderr


def parse_blackdetect(stderr):
    intervals = []
    pattern = re.compile(r"black_start:(\S+) black_end:(\S+)")
    for line in stderr.splitlines():
        m = pattern.search(line)
        if m:
            start = float(m.group(1))
            end = float(m.group(2))
            if end - start > 0.3:
                intervals.append((start, end))
    return intervals


def parse_freezedetect(stderr):
    intervals = []
    start = None
    for line in stderr.splitlines():
        sm = re.search(r"lavfi\.freezedetect_start=(\S+)", line)
        em = re.search(r"lavfi\.freezedetect_end=(\S+)", line)
        if sm:
            start = float(sm.group(1))
        if em and start is not None:
            intervals.append((start, float(em.group(1))))
            start = None
    return intervals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Input video not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(args.config)
    duration = ffprobe_duration(args.input)
    intervals = []

    if args.mode == "credits":
        stderr = run_ffmpeg_detect(args.input, "blackdetect=d=0.5:pix_th=0.10")
        blacks = parse_blackdetect(stderr)
        if blacks:
            last_start, last_end = max(blacks, key=lambda x: x[1])
            scan_window = float(cfg.get("scan_window", 6.0))
            if duration <= 0 or last_start >= duration - scan_window * 2:
                intervals.append({
                    "interval_type": "credits",
                    "start_time": round(last_start, 3),
                    "end_time": round(min(last_end, duration) if duration > 0 else last_end, 3),
                    "confidence": 0.85,
                    "label": "片尾字幕/黑场",
                    "enabled": True,
                })
    elif args.mode == "static":
        stderr = run_ffmpeg_detect(args.input, "freezedetect=n=-50dB:d=2")
        frozen = parse_freezedetect(stderr)
        min_dur = float(cfg.get("min_static_duration", 9))
        for start, end in frozen:
            if end - start >= min_dur:
                intervals.append({
                    "interval_type": "static",
                    "start_time": round(start, 3),
                    "end_time": round(end, 3),
                    "confidence": 0.7,
                    "label": "画面静止",
                    "enabled": True,
                })
    else:
        print(f"Mode '{args.mode}' has no generic detector; returning empty result", file=sys.stderr)

    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="detect_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"intervals": intervals}, f, ensure_ascii=False)
    print(out_path)


if __name__ == "__main__":
    main()
