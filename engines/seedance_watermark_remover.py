#!/usr/bin/env python3
"""
Seedance 2.0 Watermark Remover (quality-enhanced)
==================================================
Removes the "AI生成" (AI-Generated) watermark added by Seedance 2.0 video generation,
and any static corner/edge-positioned logo or text watermark.

Quality improvements over the baseline:
  1. MEDIAN frame instead of mean frame — static/semi-transparent watermarks stay
     crisp while moving content (people, water, foliage) is suppressed, so faint
     watermarks are far easier to detect and mask.
  2. Wider detection bands — scans the four corners (25% h × 30% w) plus the top /
     bottom center stripes, so off-corner and vertical-video watermarks are found.
  3. Multi-scale Canny (low/mid/high thresholds unioned) + temporal stability
     scoring, far more robust to faint / semi-transparent marks.
  4. High-quality CPU inpainting via the remove-ai-watermarks region eraser:
       backend=auto  -> LaMa-ONNX > MI-GAN-ONNX > cv2   (all CPU, no GPU needed)
     Falls back to OpenCV TELEA when the package is unavailable.

Pipeline:
  1. Sample ~60 frames and compute a median frame
  2. Auto-detect the watermark region (or use a manual region via -r)
  3. Build a precise text mask via multi-scale Canny on the watermark region
  4. Remove watermark with the selected backend (default: RAiW auto)
  5. Reassemble frames + original audio with ffmpeg

Usage:
  python watermark_remover.py input.mp4
  python watermark_remover.py input.mp4 -o clean.mp4
  python watermark_remover.py input.mp4 -r 10,5,120,60    # manual region x,y,w,h
  python watermark_remover.py input.mp4 --backend lama    # force LaMa-ONNX (CPU)
  python watermark_remover.py input.mp4 --backend migan   # force MI-GAN-ONNX (CPU)

Requirements:
  pip install opencv-python-headless numpy
  pip install remove-ai-watermarks[lama,migan]   # optional, for high-quality CPU fill
  ffmpeg must be installed and on PATH
"""

import cv2
import numpy as np
import subprocess
import sys
import os
import argparse
import tempfile
import shutil


# ──────────────────────────────────────────────────────────────
# 高质量修补后端加载（复用 remove-ai-watermarks 的 CPU 模型）
# ──────────────────────────────────────────────────────────────

def _load_raiw_fill():
    """Load the RAiW region eraser (LaMa-ONNX / MI-GAN-ONNX / cv2) if available.

    Returns a callable ``fill(frame_bgr, mask)`` that writes masked pixels, or None.
    """
    try:
        from remove_ai_watermarks.watermark_registry import fill
        return fill
    except Exception:
        try:
            from remove_ai_watermarks.region_eraser import erase
            from remove_ai_watermarks.watermark_registry import resolve_backend
            def _fill(frame_bgr, mask, _erase=erase, _resolve=resolve_backend):
                return _erase(frame_bgr, mask=mask, backend=_resolve("auto"))
            return _fill
        except Exception:
            return None


_RAIW_FILL = None


def _get_raiw_fill():
    global _RAIW_FILL
    if _RAIW_FILL is None:
        _RAIW_FILL = _load_raiw_fill()
    return _RAIW_FILL


# ──────────────────────────────────────────────────────────────
# 中位数帧 + 多尺度 Canny 检测
# ──────────────────────────────────────────────────────────────

def _multi_canny(gray):
    """Union of several Canny thresholds, so both sharp and faint edges survive."""
    edges = np.zeros_like(gray)
    for th1, th2 in ((15, 40), (30, 80), (60, 150)):
        e = cv2.Canny(gray, th1, th2)
        edges = cv2.bitwise_or(edges, e)
    return edges


def _auto_detect(median_frame, width, height, std_map=None):
    """
    Scan wide corner bands plus the top/bottom center stripes for the watermark.

    Scoring: edge_density × temporal_stability
      - edge_density: fraction of (multi-scale) Canny edge pixels in the median frame
      - temporal_stability: 1 / (1 + temporal_std) — static watermarks score high,
        moving content (people, water, foliage) scores low
    """
    gray = cv2.cvtColor(median_frame, cv2.COLOR_BGR2GRAY)

    corner_h = max(80, int(height * 0.25))
    corner_w = max(160, int(width * 0.30))
    stripe_h = max(40, int(height * 0.15))
    bands = [
        (0, 0, corner_h, corner_w),                                  # top-left
        (0, width - corner_w, corner_h, width),                      # top-right
        (height - corner_h, 0, height, corner_w),                    # bottom-left
        (height - corner_h, width - corner_w, height, width),        # bottom-right
        (0, 0, stripe_h, width),                                     # top center stripe
        (height - stripe_h, 0, height, width),                       # bottom center stripe
    ]

    best, best_score = None, 0
    for r1, c1, r2, c2 in bands:
        roi = gray[r1:r2, c1:c2]
        edges = _multi_canny(roi)
        edge_density = edges.mean() / 255.0
        if std_map is not None:
            temporal_std = std_map[r1:r2, c1:c2].mean()
            stability = 1.0 / (1.0 + temporal_std)
        else:
            stability = 1.0
        score = edge_density * stability

        if score > best_score and edge_density > 0.003:
            ys, xs = np.where(edges > 0)
            if len(xs) > 20:
                best_score = score
                pad = 10
                x = max(0, c1 + int(xs.min()) - pad)
                y = max(0, r1 + int(ys.min()) - pad)
                w = min(width - x, int(xs.max() - xs.min()) + 1 + 2 * pad)
                h = min(height - y, int(ys.max() - ys.min()) + 1 + 2 * pad)
                best = (x, y, w, h)

    return best


def _build_mask(median_frame_bgr, region_xywh, frame_shape):
    """
    Build a sparse text mask using multi-scale Canny on the median frame.
    Falls back to full-rect if Canny finds nothing (very faint watermark).
    """
    x, y, w, h = region_xywh
    H, W = frame_shape[:2]
    roi_gray = cv2.cvtColor(median_frame_bgr[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    edges = _multi_canny(roi_gray)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(edges, kernel, iterations=2)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dilated)
    clean = np.zeros_like(dilated)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 50:
            clean[labels == i] = 255
    if clean.sum() == 0:
        clean = np.full((h, w), 255, dtype=np.uint8)
    mask = np.zeros((H, W), dtype=np.uint8)
    mask[y:y + h, x:x + w] = clean
    return mask


# ──────────────────────────────────────────────────────────────
# 修补
# ──────────────────────────────────────────────────────────────

def _inpaint_telea(frame_bgr, mask):
    """Fast OpenCV TELEA inpainting — no deps, works on uniform backgrounds."""
    return cv2.inpaint(frame_bgr, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)


def _make_inpaint(backend: str):
    """Build a per-frame inpaint callable.

    backend: auto / lama / migan / cv2.
      - auto -> RAiW resolve (LaMa > MI-GAN > cv2) when available, else cv2
      - lama / migan -> RAiW LaMa-ONNX / MI-GAN-ONNX (CPU), falls back to cv2
      - cv2 -> OpenCV TELEA
    """
    fill = _get_raiw_fill()

    def _inpaint(frame_bgr, mask):
        try:
            if fill is not None:
                return fill(frame_bgr, mask=mask, backend=backend)
        except Exception as e:
            print(f"  [warn] {backend} fill failed ({e}); falling back to cv2 TELEA", flush=True)
        return _inpaint_telea(frame_bgr, mask)

    return _inpaint


def remove_watermark(input_path, output_path, manual_region=None, backend="auto"):
    cap = cv2.VideoCapture(input_path)
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {width}x{height} @ {fps:.2f} fps | {total} frames")

    # ── sample frames → median frame ─────────────────────────────────────────
    print("Sampling frames for watermark detection...")
    print("PROGRESS:5")
    sample_frames = []
    step = max(1, total // 60)
    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, f = cap.read()
        if ret:
            sample_frames.append(f)
        if len(sample_frames) >= 60:
            break

    if not sample_frames:
        print("Error: could not read any frames.")
        cap.release()
        return False

    stack = np.stack(sample_frames)              # uint8, keeps memory bounded
    median_frame = np.median(stack, axis=0).astype(np.uint8)

    # ── detect / use manual region ───────────────────────────────────────────
    if manual_region:
        x, y, w, h = manual_region
        print(f"Using manual region: x={x} y={y} w={w} h={h}")
    else:
        std_map = np.std(stack.astype(np.float32), axis=0).mean(axis=2)
        region = _auto_detect(median_frame, width, height, std_map)
        if region is None:
            print("Error: auto-detection failed. Try -r x,y,w,h to specify the region manually.")
            cap.release()
            return False
        x, y, w, h = region
        print(f"Detected watermark region: x={x} y={y} w={w} h={h}")
    print("PROGRESS:20")

    mask = _build_mask(median_frame, (x, y, w, h), (height, width))
    print(f"Mask: {int(mask.sum() // 255)} pixels")

    inpaint = _make_inpaint(backend)

    # ── process frames ────────────────────────────────────────────────────────
    frames_dir = tempfile.mkdtemp(prefix="seedance_wm_")
    print(f"Inpainting {total} frames (backend={backend})...")
    print("PROGRESS:30")

    ret_code = 1
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for i in range(total):
            ret, frame = cap.read()
            if not ret:
                break
            result = inpaint(frame, mask)
            cv2.imwrite(os.path.join(frames_dir, f"{i:06d}.png"), result)
            if (i + 1) % 30 == 0 or i == total - 1:
                pct = 30 + int((i + 1) / total * 60)
                print(f"  {i+1}/{total}", flush=True)
                print(f"PROGRESS:{pct}", flush=True)
        cap.release()
        print()

        # ── reassemble with original audio ────────────────────────────────────
        print("Reassembling video with original audio...")
        print("PROGRESS:92")
        cmd = [
            "ffmpeg",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "%06d.png"),
            "-i", input_path,
            "-map", "0:v",
            "-map", "1:a?",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path, "-y",
        ]
        ret_code = subprocess.run(cmd, capture_output=True).returncode

    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    if ret_code == 0:
        in_mb  = os.path.getsize(input_path)  / 1024 / 1024
        out_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"\nDone.  {in_mb:.1f} MB  →  {out_mb:.1f} MB")
        print("PROGRESS:100")
        print(f"Output: {output_path}")
        return True
    else:
        print("Error: ffmpeg reassembly failed.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Remove Seedance 2.0 'AI生成' watermark / any static logo watermark from videos."
    )
    parser.add_argument("input",           help="Input video file")
    parser.add_argument("-o", "--output",  help="Output path (default: <input>_clean.mp4)")
    parser.add_argument(
        "-r", "--region",
        help="Manual watermark region as x,y,w,h — skips auto-detection",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "lama", "migan", "cv2"],
        default="auto",
        help="Inpaint backend. auto: RAiW LaMa-ONNX > MI-GAN-ONNX > cv2 (CPU). "
             "lama/migan: force the high-quality RAiW ONNX model (CPU, requires "
             "remove-ai-watermarks[lama]/[migan]). cv2: classical OpenCV TELEA.",
    )
    # 兼容旧调用：--lama 等价于 --backend lama
    parser.add_argument("--lama", action="store_true", help="Shorthand for --backend lama")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}")
        sys.exit(1)

    output = args.output or os.path.splitext(args.input)[0] + "_clean.mp4"

    region = None
    if args.region:
        try:
            region = tuple(int(v) for v in args.region.split(","))
            assert len(region) == 4
        except Exception:
            print("Error: --region must be four comma-separated integers: x,y,w,h")
            sys.exit(1)

    backend = args.backend
    if args.lama:
        backend = "lama"

    ok = remove_watermark(args.input, output, manual_region=region, backend=backend)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
