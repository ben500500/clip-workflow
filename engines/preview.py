#!/usr/bin/env python3
"""Extract preview frames from a video using ffmpeg.

Usage:
  preview.py <source> <output_dir> [--frames N]

Prints OUTPUT:<name>:<duration> and PROGRESS:<pct> lines to stdout.
"""
import argparse
import os
import subprocess
import sys


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output_dir")
    parser.add_argument("--frames", type=int, default=6)
    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"Source video not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    duration = ffprobe_duration(args.source)
    frames = max(1, min(args.frames, 20))
    for i in range(frames):
        t = duration * (i + 1) / (frames + 1) if duration > 0 else i + 1
        out_name = f"frame_{i + 1:02d}.jpg"
        out_path = os.path.join(args.output_dir, out_name)
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", args.source,
                "-frames:v", "1", "-q:v", "2", out_path,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            check=False,
        )
        print(f"PROGRESS:{int((i + 1) * 100 / frames)}")
        if os.path.isfile(out_path):
            print(f"OUTPUT:{out_name}:0")


if __name__ == "__main__":
    main()
