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
  4. SEGMENT-WISE detection — the video is split into time segments (default 4),
     each segment detects its own watermark region(s) independently. A watermark
     that MOVES over time (e.g. bottom-right first, top-left later) is now caught
     in every segment instead of only at its first detected position.
  5. Multi-region masking — all high-confidence regions in a segment are masked,
     not just the best one, so multiple logos/text marks are handled at once.
  6. Richer mask building — multi-scale Canny + local background difference
     (Gaussian blur subtraction) so semi-transparent text interiors are covered.
  7. High-quality CPU inpainting via the remove-ai-watermarks region eraser:
       backend=auto  -> LaMa-ONNX > MI-GAN-ONNX > cv2   (all CPU, no GPU needed)
     Falls back to OpenCV TELEA when the package is unavailable.

Pipeline:
  1. Sample ~60 frames evenly across the video
  2. Split sampled frames into time segments; detect watermark region(s) per segment
  3. Build a per-frame mask plan (with smooth transition at segment boundaries)
  4. Remove watermark with the selected backend (default: RAiW auto)
  5. Reassemble frames + original audio with ffmpeg

Usage:
  python watermark_remover.py input.mp4
  python watermark_remover.py input.mp4 -o clean.mp4
  python watermark_remover.py input.mp4 -r 10,5,120,60    # manual region x,y,w,h
  python watermark_remover.py input.mp4 --backend lama    # force LaMa-ONNX (CPU)
  python watermark_remover.py input.mp4 --backend migan   # force MI-GAN-ONNX (CPU)
  python watermark_remover.py input.mp4 --segments 6      # finer time segmentation

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


def _onnx_model_ready(repo_name: str) -> bool:
    """检查 HuggingFace 仓库模型是否已完整下载到本地缓存。

    remove-ai-watermarks 的 LaMa/MI-GAN 首次使用会从 HuggingFace 下载模型
    （LaMa ~200MB / MI-GAN ~28MB）。服务器无法访问 huggingface.co 时，
    每次 fill 调用都会尝试下载并超时（10s+），逐帧拖慢导致任务看似卡死。
    因此在使用这些后端前先确认模型缓存完整（blobs 下存在非 .incomplete 文件）。
    """
    import os

    hf_home = os.environ.get(
        "HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    )
    hub_name = "models--" + repo_name.replace("/", "--")
    hub_dir = os.path.join(hf_home, "hub", hub_name, "blobs")
    try:
        if not os.path.isdir(hub_dir):
            return False
        for blob in os.listdir(hub_dir):
            if not blob.endswith(".incomplete"):
                return True
    except OSError:
        return False
    return False


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
    Scan wide corner bands plus the top/bottom center stripes for watermarks.

    Returns a list of ALL high-confidence regions (not just the best one), so a
    video with several static logos/text marks can be handled in one pass.
    Overlapping candidates are deduplicated (keep the highest-scoring box).

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

    candidates = []
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

        if edge_density > 0.003:
            ys, xs = np.where(edges > 0)
            if len(xs) > 20:
                pad = 10
                x = max(0, c1 + int(xs.min()) - pad)
                y = max(0, r1 + int(ys.min()) - pad)
                w = min(width - x, int(xs.max() - xs.min()) + 1 + 2 * pad)
                h = min(height - y, int(ys.max() - ys.min()) + 1 + 2 * pad)
                candidates.append((score, (x, y, w, h)))

    # 按得分降序，去重叠（IoU > 0.3 视为同一区域，保留高分）
    candidates.sort(key=lambda t: -t[0])
    picked = []
    for score, box in candidates:
        overlap = False
        for _, pbox in picked:
            x1, y1, w1, h1 = box
            x2, y2, w2, h2 = pbox
            ix = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
            iy = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
            inter = ix * iy
            union = w1 * h1 + w2 * h2 - inter
            if union > 0 and inter / union > 0.3:
                overlap = True
                break
        if not overlap:
            picked.append((score, box))

    # 只保留置信度足够高的候选（得分前 3 名即可，避免误检引入过多修补区）
    picked = picked[:3]
    return [box for _, box in picked]


def _build_mask(median_frame_bgr, region_xywh, frame_shape):
    """
    Build a sparse text mask using multi-scale Canny + local background difference
    on the median frame.

    - Canny traces sharp letter strokes
    - local background difference (Gaussian blur subtraction) catches the interior
      of semi-transparent text that Canny alone misses
    Falls back to full-rect if nothing is found (very faint watermark).
    """
    x, y, w, h = region_xywh
    H, W = frame_shape[:2]
    roi_gray = cv2.cvtColor(median_frame_bgr[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)

    # Canny 边缘：捕捉文字笔画锐利边缘
    edges = _multi_canny(roi_gray)

    # 局部背景差分：半透明水印文字与局部模糊背景差异明显，捕捉文字内部
    blur = cv2.GaussianBlur(roi_gray, (0, 0), 5)
    diff = cv2.absdiff(roi_gray, blur)
    _, diff_mask = cv2.threshold(diff, 12, 255, cv2.THRESH_BINARY)

    combined = cv2.bitwise_or(edges, diff_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    combined = cv2.dilate(combined, kernel, iterations=2)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(combined)
    clean = np.zeros_like(combined)
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

    # 离线/模型未下载保护：LaMa/MI-GAN 模型文件不存在时，auto 模式直接降级
    # cv2。否则每帧 fill 都会尝试从 HuggingFace 下载模型并超时（10s+），
    # 逐帧拖慢导致任务看似卡死在 90%。
    effective_backend = backend
    if backend in ("auto", "lama", "migan"):
        lama_ok = _onnx_model_ready("Carve/LaMa-ONNX")
        migan_ok = _onnx_model_ready("andraniksargsyan/migan")
        if backend == "auto":
            if lama_ok or migan_ok:
                effective_backend = "lama" if lama_ok else "migan"
            else:
                effective_backend = "cv2"
                print(
                    "  [info] LaMa/MI-GAN 模型未下载（离线环境），auto 降级 cv2 TELEA",
                    flush=True,
                )
        elif backend == "lama" and not lama_ok:
            effective_backend = "cv2"
            print("  [warn] LaMa 模型未下载，降级 cv2 TELEA", flush=True)
        elif backend == "migan" and not migan_ok:
            effective_backend = "cv2"
            print("  [warn] MI-GAN 模型未下载，降级 cv2 TELEA", flush=True)

    def _inpaint(frame_bgr, mask):
        try:
            if fill is not None:
                return fill(frame_bgr, mask=mask, backend=effective_backend)
        except Exception as e:
            print(f"  [warn] {effective_backend} fill failed ({e}); falling back to cv2 TELEA", flush=True)
        return _inpaint_telea(frame_bgr, mask)

    return _inpaint


def remove_watermark(input_path, output_path, manual_region=None, backend="auto",
                     segments=4):
    cap = cv2.VideoCapture(input_path)
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {width}x{height} @ {fps:.2f} fps | {total} frames")

    # ── sample frames evenly across the whole video ────────────────────────────
    print("Sampling frames for watermark detection...")
    print("PROGRESS:5")
    sample_frames = []
    sample_idx = []   # 记录采样帧的原始帧号，用于把采样帧映射回真实帧号
    step = max(1, total // 60)
    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, f = cap.read()
        if ret:
            sample_frames.append(f)
            sample_idx.append(i)
        if len(sample_frames) >= 60:
            break

    if not sample_frames:
        print("Error: could not read any frames.")
        cap.release()
        return False

    stack = np.stack(sample_frames)              # uint8, keeps memory bounded

    # ── build per-segment mask plan ────────────────────────────────────────────
    # 将采样帧按时序均分成 N 段，每段独立检测水印区域并建 mask。
    # 这样“先右下、后左上”的移动水印会在不同时段分别被检测到。
    n_seg = max(1, min(segments, len(sample_frames)))
    # 保证每段至少 3 帧采样（median/std 需要足够样本），短视频自动降段
    n_seg = min(n_seg, max(1, len(sample_frames) // 3))
    seg_size = max(1, len(sample_frames) // n_seg)
    print(f"Segment-wise detection: {n_seg} segments")

    seg_plans = []   # 每段: {start_idx, end_idx, masks: [(box, mask), ...]}
    if manual_region:
        x, y, w, h = manual_region
        print(f"Using manual region: x={x} y={y} w={w} h={h}")
        # 手动区域应用于全片所有段
        global_mask = _build_mask(stack.mean(axis=0).astype(np.uint8),
                                  (x, y, w, h), (height, width))
        for si in range(n_seg):
            seg_plans.append({
                "start": si * seg_size,
                "end": min((si + 1) * seg_size, len(sample_frames)),
                "masks": [((x, y, w, h), global_mask)],
            })
    else:
        any_detected = False
        for si in range(n_seg):
            s0 = si * seg_size
            s1 = min((si + 1) * seg_size, len(sample_frames))
            seg_frames = stack[s0:s1]
            if len(seg_frames) < 3:
                continue
            seg_median = np.median(seg_frames, axis=0).astype(np.uint8)
            std_map = np.std(seg_frames.astype(np.float32), axis=0).mean(axis=2)
            boxes = _auto_detect(seg_median, width, height, std_map)
            masks = []
            for box in boxes:
                m = _build_mask(seg_median, box, (height, width))
                masks.append((box, m))
            seg_plans.append({
                "start": s0,
                "end": s1,
                "masks": masks,
            })
            if masks:
                any_detected = True
            print(f"  seg{si}: {len(masks)} region(s) "
                  + ", ".join(f"({b[0]},{b[1]},{b[2]},{b[3]})" for b, _ in masks))

        if not any_detected:
            print("Error: auto-detection failed. Try -r x,y,w,h to specify the region manually.")
            cap.release()
            return False
    print("PROGRESS:20")

    # 把采样段边界映射到真实帧号，构建 [frame_start, frame_end) -> masks 计划
    frame_plans = []   # (start_frame, end_frame, masks)
    for sp in seg_plans:
        if not sp["masks"]:
            continue
        fs = sample_idx[sp["start"]]
        fe = sample_idx[sp["end"] - 1] + 1 if sp["end"] > sp["start"] else fs + 1
        # 下一段的开始帧与当前段的结束帧之间由边界填充（避免空白帧）
        frame_plans.append((fs, fe, sp["masks"]))
    # 排序并填补段间缝隙：把上一段的 masks 延伸到下一段的起始帧之前
    frame_plans.sort(key=lambda p: p[0])
    filled = []
    for i, (fs, fe, masks) in enumerate(frame_plans):
        if i == 0:
            filled.append((0, fe, masks))
        else:
            prev_fe = filled[-1][1]
            filled.append((prev_fe, fe, masks))
    # 最后一段延伸到末尾
    if filled:
        filled[-1] = (filled[-1][0], total, filled[-1][2])
    frame_plans = filled

    def _masks_for_frame(i):
        for fs, fe, masks in frame_plans:
            if fs <= i < fe:
                return masks
        return frame_plans[-1][2] if frame_plans else []

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
            masks = _masks_for_frame(i)
            for box, mask in masks:
                try:
                    frame = inpaint(frame, mask)
                except Exception as e:
                    print(f"  [warn] frame {i} inpaint failed ({e})", flush=True)
            cv2.imwrite(os.path.join(frames_dir, f"{i:06d}.png"), frame)
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
    parser.add_argument(
        "--segments",
        type=int,
        default=4,
        help="Number of time segments for segment-wise watermark detection "
             "(default 4; raise it for watermarks that move during the video)",
    )
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

    ok = remove_watermark(args.input, output, manual_region=region, backend=backend,
                          segments=max(1, args.segments))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
