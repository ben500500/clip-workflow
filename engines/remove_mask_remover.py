#!/usr/bin/env python3
"""
Remove Mask 去水印引擎 —— 基于 ben500500/remove-mask 的「ROI + cv2.inpaint(TELEA)」方案

原理（沿用 remove-mask 仓库《去水印经验总结》思路）：
1. 不区分“哪些像素是水印”：直接把整个水印 ROI 矩形当掩码
2. cv2.INPAINT_TELEA 快速行进法从 ROI 边界向内插值填充（对文字水印优于 NS）
3. 按视频文件名匹配内置 ROI（基于全视频时序分析 + OCR 确认的水印框 + buffer）
4. 覆盖 TL / BR（Seedance 水印规律固定出现在左上 + 右下角）
5. 参数保真：保留原始分辨率/帧率/编码，音频流复制零损耗

v7 核心升级（同步 ben500500/remove-mask 上游更新）：
**处理前自动分析任意视频**，不再局限于固定视频：
  ① 抽帧分析 → ② 自动检测水印带（半透明白色像素 + y/x 聚类）
  → ③ 生成最佳处理方案（检测不到时回退全角大框） → ④ 执行处理
  保留预置 ROI（已知 5 视频，含新增“爷孙重逢”）与 --scope/--mode 兼容；
  新增 --analyze-only（只分析）与 --auto（强制自动检测，跳过预置 ROI）。

两种去水印模式（--mode 切换，同步 ben500500/remove-mask 上游更新）：
- inpaint（默认）：ROI + cv2.inpaint(TELEA) 插值修复，保留原始构图，水印区域被插值填充
- crop：裁切去水印，把包含水印的上下两条水平带裁掉，保留中间无字区域后等比放大回
  原始分辨率、左右对称居中裁回原始宽度。画面无修复痕迹但构图有裁剪/放大。
  适合画面上下无重要内容、宁可损失一点构图也不愿看到修复痕迹的场景。

CLI:
  python remove_mask_remover.py <输入视频> -o <输出视频> [options]

选项:
  -r, --region  x,y,w,h    手动指定水印区域（覆盖文件名匹配；x=列 y=行 w=宽 h=高）
  --scope      small|large 水印 ROI 范围（默认 small：收紧贴合水印文字；large：整角大框）
  --mode       inpaint|crop 去水印模式（默认 inpaint：ROI+插值修复；crop：裁切去水印）
  --radius      N          修补半径（默认 3，仅 inpaint 模式生效）
  --iterations  N          修补迭代次数（默认 1，仅 inpaint 模式生效）
  --source-name NAME       原始文件名（用于匹配内置 ROI；默认取输入文件 basename）
  --analyze-only           只做自动水印分析，输出检测报告后退出（不执行处理）
  --auto                   强制走自动检测（跳过预置 ROI），适合自定义新视频

进度约定：向 stdout 输出 PROGRESS:<pct>（与 clip-workflow watermark_runner 一致）。
"""

import argparse
import os
import subprocess
import sys

import cv2
import numpy as np

# remove-mask 经验库（ROI 表）共享模块，与其它引擎共用同一份确认过的水印位置
from remove_mask_rois import build_mask, match_rois, resolve_rois


# ============================================================
# 自动水印分析模块（同步 remove-mask 上游 v7）
# ============================================================

def _load_sampled_frames(video_path, step=2, max_frames=200):
    """均匀抽帧，用于快速分析（不读全片）。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, 0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frames = []
    n = min(total, max_frames * step)
    for i in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, f = cap.read()
        if ret:
            frames.append(f)
    cap.release()
    return np.stack(frames) if frames else None, total


def _semi_white_mask(frame):
    """半透明白色水印像素：min 通道中高 + 低饱和 + 局部比背景亮。"""
    f = frame.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    ming = np.minimum(np.minimum(r, g), b)
    sat = np.maximum(np.maximum(r, g), b) - ming
    gg = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = cv2.medianBlur(gg.astype(np.uint8), 15).astype(np.float32)
    diff = gg - bg
    sw = ((ming > 90) & (sat < 40) & (diff > 6)).astype(np.uint8)
    sw = cv2.morphologyEx(sw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    sw = cv2.dilate(sw, np.ones((3, 3), np.uint8), iterations=1)
    return sw


def _detect_text_bands(video_path, step=2, max_frames=200):
    """逐帧检测贴边水平文字带，返回 (top_boxes, bottom_boxes, N, H, W)。"""
    frames, total = _load_sampled_frames(video_path, step, max_frames)
    if frames is None:
        return None
    N = frames.shape[0]
    H, W = frames.shape[1], frames.shape[2]
    boxes_top, boxes_bottom = [], []
    for i in range(N):
        sw = _semi_white_mask(frames[i])
        for boxes, (z0, z1) in ((boxes_top, (0, int(H * 0.22))),
                                (boxes_bottom, (int(H * 0.78), H))):
            rsum = sw[z0:z1].sum(axis=1)
            thr = max(4, rsum.max() * 0.25)
            m = rsum >= thr
            runs = []
            j = 0
            while j < len(m):
                if m[j]:
                    k = j
                    while k < len(m) and m[k]:
                        k += 1
                    runs.append((j + z0, k - 1 + z0))
                    j = k
                else:
                    j += 1
            for (ry0, ry1) in runs:
                if (ry1 - ry0) < 8 or (ry1 - ry0) > 140:
                    continue
                sub = sw[ry0:ry1 + 1, :]
                csum = sub.sum(axis=0)
                thr_c = max(3, csum.max() * 0.25)
                m2 = csum >= thr_c
                runs2 = []
                j = 0
                while j < len(m2):
                    if m2[j]:
                        k = j
                        while k < len(m2) and m2[k]:
                            k += 1
                        runs2.append((j, k - 1))
                        j = k
                    else:
                        j += 1
                for (cx0, cx1) in runs2:
                    if (cx1 - cx0) < 30 or (cx1 - cx0) > W * 0.6:
                        continue
                    boxes.append((ry0, ry1, cx0, cx1))
    return boxes_top, boxes_bottom, N, H, W


def _cluster_boxes(boxes, N, H, W, bin_h=12):
    """对候选框聚类：y 直方图峰值分带 + 带内 x 聚类。"""
    if len(boxes) < max(4, N * 0.03):
        return []
    boxes = np.array(boxes, dtype=np.float32)
    cy = (boxes[:, 0] + boxes[:, 1]) / 2
    cx = (boxes[:, 2] + boxes[:, 3]) / 2

    # 1) y 直方图峰值聚类（bin=12px）
    hist_y, edges = np.histogram(cy, bins=H // bin_h, range=[0, H])
    hist_y = cv2.GaussianBlur(
        hist_y.astype(np.float32).reshape(-1, 1), (5, 1), 0).ravel()

    out = []
    for _ in range(4):
        pk = np.argmax(hist_y)
        if hist_y[pk] < max(3, N * 0.03):
            break
        yc = (edges[pk] + edges[pk + 1]) / 2
        in_band = np.abs(cy - yc) < bin_h * 2.5
        sel = boxes[in_band]
        if len(sel) < max(3, N * 0.03):
            hist_y[max(0, pk - 2):pk + 3] = 0
            continue
        y0 = int(np.percentile(sel[:, 0], 5))
        y1 = int(np.percentile(sel[:, 1], 95))
        if (y1 - y0) < 10 or (y1 - y0) > 170:
            hist_y[max(0, pk - 2):pk + 3] = 0
            continue

        # 2) 带内按 x 中心聚类（gap=25px）
        bcx = cx[in_band]
        bx = boxes[in_band]
        x_order = np.argsort(bcx)
        x_bands = []
        cur = []
        for idx in x_order:
            if not cur:
                cur = [idx]
            else:
                if bcx[idx] - bcx[cur[-1]] <= 25:
                    cur.append(idx)
                else:
                    x_bands.append(cur)
                    cur = [idx]
        if cur:
            x_bands.append(cur)
        for xb in x_bands:
            if len(xb) < max(3, N * 0.02):
                continue
            bx2 = bx[xb]
            x0 = int(np.percentile(bx2[:, 2], 5))
            x1 = int(np.percentile(bx2[:, 3], 95))
            if (x1 - x0) < 30:
                continue
            orig_idx = np.where(in_band)[0]
            score = len(set(orig_idx[i] for i in xb)) / N
            out.append((y0, y1, x0, x1, score))
        hist_y[max(0, pk - 2):pk + 3] = 0
    return out


def _merge_bands(bands):
    """把同一 top/bottom 带内的多个候选框合并成完整覆盖框。"""
    if not bands:
        return []
    bands = sorted(bands, key=lambda b: (b[0] + b[1]) / 2)
    groups = []
    for b in bands:
        placed = False
        for g in groups:
            gy0 = min(x[0] for x in g)
            gy1 = max(x[1] for x in g)
            if b[0] <= gy1 and b[1] >= gy0:
                g.append(b)
                placed = True
                break
        if not placed:
            groups.append([b])
    merged = []
    for g in groups:
        y0 = min(x[0] for x in g)
        y1 = max(x[1] for x in g)
        x0 = min(x[2] for x in g)
        x1 = max(x[3] for x in g)
        score = max(x[4] for x in g)
        merged.append((y0, y1, x0, x1, score))
    return merged


def analyze_video(video_path):
    """自动分析任意视频，检测水印带。

    返回 dict：
      {
        'found': True/False,
        'top':  [(y0,y1,x0,x1,score), ...] 或 [],
        'bottom': [(y0,y1,x0,x1,score), ...] 或 [],
        'H': 高, 'W': 宽, 'N': 采样帧数,
        'fallback': 是否回退全角大框,
        'report': 人类可读分析报告(str)
      }
    """
    det = _detect_text_bands(video_path)
    if det is None:
        return {'found': False, 'top': [], 'bottom': [], 'H': 0, 'W': 0,
                'N': 0, 'fallback': True, 'report': '无法读取视频'}
    boxes_top, boxes_bottom, N, H, W = det

    top = _cluster_boxes(boxes_top, N, H, W)
    bottom = _cluster_boxes(boxes_bottom, N, H, W)
    # 过滤：丢弃低置信度候选（score = 覆盖帧比例，需 ≥ 15%）
    MIN_SCORE = 0.15
    top = [b for b in top if b[4] >= MIN_SCORE]
    bottom = [b for b in bottom if b[4] >= MIN_SCORE]
    # 过滤掉非贴边（中心不靠近上下边缘）
    top = [b for b in top if (b[0] + b[1]) / 2 <= H * 0.24]
    bottom = [b for b in bottom if (b[0] + b[1]) / 2 >= H * 0.76]

    top = _merge_bands(top)
    bottom = _merge_bands(bottom)

    # 同一侧多个候选时，优先保留置信度最高的 1-2 个；
    # bottom 偏向最贴底（y 大），top 偏向最贴顶（y 小）
    if top:
        top = sorted(top, key=lambda b: (-b[4], b[0]))
        top = top[:2]
        top = sorted(top, key=lambda b: b[0])
    if bottom:
        bottom = sorted(bottom, key=lambda b: (-b[4], -b[1]))
        bottom = bottom[:2]
        bottom = sorted(bottom, key=lambda b: -b[1])

    lines = []
    lines.append(f'  视频规格: {W}×{H}, 采样 {N} 帧')
    if top:
        lines.append(f'  检测到【顶部】水印带 {len(top)} 处:')
        for (y0, y1, x0, x1, s) in top:
            lines.append(f'    · y={y0}-{y1}  x={x0}-{x1}  置信度={s:.0%}')
    else:
        lines.append('  未检测到顶部水印带')
    if bottom:
        lines.append(f'  检测到【底部】水印带 {len(bottom)} 处:')
        for (y0, y1, x0, x1, s) in bottom:
            lines.append(f'    · y={y0}-{y1}  x={x0}-{x1}  置信度={s:.0%}')
    else:
        lines.append('  未检测到底部水印带')

    fallback = (not top) and (not bottom)
    if fallback:
        lines.append('  ⚠️ 未能自动定位水印，回退"全角大框"策略（覆盖上/下边缘各 13% 区域）')

    return {
        'found': not fallback,
        'top': top,
        'bottom': bottom,
        'H': H, 'W': W, 'N': N,
        'fallback': fallback,
        'report': '\n'.join(lines),
    }


def analysis_to_rois(analysis, margin=6):
    """把分析结果转成 inpaint 用的 ROI dict。

    顶部带 → TL（左上），底部带 → BR（右下）。
    同一侧若有多个候选，优先选置信度最高的带（最可能是真实水印），
    避免把场景字幕误并入导致遮盖面积过大。
    未检测到则回退全角大框。
    """
    H, W = analysis['H'], analysis['W']
    if H <= 0 or W <= 0:
        return None
    rois = {}
    buf = margin

    def pick(bands, prefer_bottom=False, must_be_edge=False):
        """选最可能的带。must_be_edge 时优先选贴边最紧的带，否则返回 None（触发全角回退）。"""
        if not bands:
            return None
        if must_be_edge:
            if prefer_bottom:
                edge_bands = [b for b in bands if b[1] >= H * 0.90]
            else:
                edge_bands = [b for b in bands if b[0] <= H * 0.12]
            if not edge_bands:
                return None
            if prefer_bottom:
                def score(b):
                    edge = (b[1] - H * 0.90) / (H * 0.10)
                    return b[4] * 1.0 + max(0, edge) * 0.15
            else:
                def score(b):
                    edge = (H * 0.12 - b[0]) / (H * 0.12)
                    return b[4] * 1.0 + max(0, edge) * 0.15
            edge_bands.sort(key=score, reverse=True)
            return edge_bands[0]
        bands = sorted(bands, key=lambda b: (-b[4], (b[0] if not prefer_bottom else -b[1])))
        return bands[0]

    tl = pick(analysis['top'], must_be_edge=True)
    if tl:
        y0, y1, x0, x1, _ = tl
        rois['TL'] = (max(0, y0 - buf), min(H - 1, y1 + buf),
                      max(0, x0 - buf), min(W - 1, x1 + buf))
    else:
        # 回退：顶部 20% 全宽（保守覆盖，确保暗水印不遗漏）
        rois['TL'] = (0, int(H * 0.20) + buf, 0, W)

    br = pick(analysis['bottom'], prefer_bottom=True, must_be_edge=True)
    if br:
        y0, y1, x0, x1, _ = br
        rois['BR'] = (max(0, y0 - buf), min(H - 1, y1 + buf),
                      max(0, x0 - buf), min(W - 1, x1 + buf))
    else:
        rois['BR'] = (int(H * 0.87) - buf, H, 0, W)

    return rois


def process_crop(video_path, output_path, rois):
    """裁切去水印：裁掉覆盖水印的上下水平带，剩余画面等比放大回原高并居中裁回原宽。

    同步自 ben500500/remove-mask 上游 --mode crop 实现：
      顶部水印(TL)下边缘以上、底部水印(BR)上边缘以下整条水平带裁掉，
      保留中间无字区域，等比放大回原始高度，左右对称居中裁回原始宽度。
    """
    print("水印 ROI:", flush=True)
    for c, roi in rois.items():
        print(f"  {c}: {roi}", flush=True)

    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    print(f"Video: {W}x{H} @ {fps:.3f} fps | {total} frames", flush=True)

    # 由 ROI 计算顶部/底部需要裁掉的行数（左右水印只影响缩放后的横向居中，不影响裁剪行）
    # 顶部水印(TL)的 y1 = 裁掉区域下边缘；底部水印(BR)的 y0 = 保留区下边缘
    top = max(r[1] for r in rois.values() if r[1] <= H // 2)      # 顶部裁到 TL 水印下边缘
    bottom = min(r[0] for r in rois.values() if r[0] >= H // 2)   # 底部从 BR 水印上边缘起裁
    crop_h = bottom - top                     # 保留区高度
    scale = H / crop_h                        # 等比放大系数（裁掉后放大回原高）
    crop_w = int(round(W / scale))            # 等比放大回 W×H 前需要裁出的宽度（原图坐标系）
    x0 = (W - crop_w) // 2                    # 左右居中裁
    print(
        f"裁剪区: 顶 {top} 行 / 底 {H - bottom} 行，保留 {crop_h} 行，等比放大 {scale:.4f}x，横向居中裁 {crop_w}px",
        flush=True,
    )

    tmp_video = output_path + '.tmp.mp4'
    audio_tmp = output_path + '.aac'

    # 提取原音频（流复制，无损）；无音轨时静默降级
    print("PROGRESS:3", flush=True)
    has_audio = False
    try:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', video_path,
            '-vn', '-acodec', 'copy', audio_tmp
        ], check=True)
        if os.path.isfile(audio_tmp) and os.path.getsize(audio_tmp) > 0:
            has_audio = True
    except subprocess.CalledProcessError:
        has_audio = False

    print("PROGRESS:8", flush=True)
    # 视频流：rawvideo → libx264 高质量（帧率保持原 fps）
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f'{W}x{H}', '-r', f'{fps:.6f}'.rstrip('0').rstrip('.'),
        '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        tmp_video
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    idx = 0
    print("逐帧裁切中...", flush=True)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        kept = frame[top:bottom, x0:x0 + crop_w]                                # 裁掉水印区
        result = cv2.resize(kept, (W, H), interpolation=cv2.INTER_LANCZOS4)     # 等比放大回原分辨率
        proc.stdin.write(result.tobytes())
        idx += 1
        if idx % 30 == 0 or idx == total:
            pct = 8 + int(idx / total * 82) if total else 90
            print(f"  处理帧 {idx}/{total}", flush=True)
            print(f"PROGRESS:{min(pct, 90)}", flush=True)
    cap.release()
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        for p in (tmp_video, audio_tmp):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        raise RuntimeError("ffmpeg 视频编码失败")

    # 合并音频
    print("合并音频...", flush=True)
    print("PROGRESS:95", flush=True)
    if has_audio:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', tmp_video, '-i', audio_tmp,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'copy',
            '-shortest',
            output_path
        ], check=True)
    else:
        os.replace(tmp_video, output_path)

    for p in (tmp_video, audio_tmp):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

    print(f"完成: {output_path} ({idx} 帧)", flush=True)
    print("PROGRESS:100", flush=True)
    return rois


def process(video_path, output_path, rois, radius=3, iterations=1):
    print("水印 ROI:")
    for c, roi in rois.items():
        print(f"  {c}: {roi}", flush=True)

    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {W}x{H} @ {fps:.3f} fps | {total} frames", flush=True)

    mask = build_mask(rois, H, W)
    print(f"mask 总面积: {int(mask.sum() / 255)} px", flush=True)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    tmp_video = output_path + '.tmp.mp4'
    audio_tmp = output_path + '.aac'

    # 提取原音频（流复制，无损）；无音轨时静默降级
    print("提取原音频...", flush=True)
    print("PROGRESS:3", flush=True)
    has_audio = False
    try:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', video_path,
            '-vn', '-acodec', 'copy', audio_tmp
        ], check=True)
        if os.path.isfile(audio_tmp) and os.path.getsize(audio_tmp) > 0:
            has_audio = True
    except subprocess.CalledProcessError:
        has_audio = False

    print("PROGRESS:8", flush=True)
    # 视频流：rawvideo → libx264 高质量（保留实际帧率）
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f'{W}x{H}', '-r', f'{fps:.3f}',
        '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        tmp_video
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    idx = 0
    print("逐帧修补中...", flush=True)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        result = frame.copy()
        for _ in range(iterations):
            result = cv2.inpaint(result, mask, radius, cv2.INPAINT_TELEA)
        proc.stdin.write(result.tobytes())
        idx += 1
        if idx % 30 == 0 or idx == total:
            pct = 8 + int(idx / total * 82) if total else 90
            print(f"  处理帧 {idx}/{total}", flush=True)
            print(f"PROGRESS:{min(pct, 90)}", flush=True)
    cap.release()
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        for p in (tmp_video, audio_tmp):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        raise RuntimeError("ffmpeg 视频编码失败")

    # 合并音频
    print("合并音频...", flush=True)
    print("PROGRESS:95", flush=True)
    if has_audio:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', tmp_video, '-i', audio_tmp,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'copy',
            '-shortest',
            output_path
        ], check=True)
    else:
        os.replace(tmp_video, output_path)

    for p in (tmp_video, audio_tmp):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

    print(f"完成: {output_path} ({idx} 帧)", flush=True)
    print("PROGRESS:100", flush=True)
    return rois


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="remove_mask_remover",
        description="Remove Mask 去水印引擎（ROI + cv2.inpaint TELEA / 裁切）",
    )
    parser.add_argument("input", help="输入视频路径")
    parser.add_argument("-o", "--output", help="输出视频路径")
    parser.add_argument(
        "-r", "--region",
        help="手动水印区域 x,y,w,h（覆盖文件名匹配；x=列 y=行 w=宽 h=高）",
    )
    parser.add_argument("--radius", type=int, default=3, help="修补半径（默认 3，仅 inpaint 模式）")
    parser.add_argument("--iterations", type=int, default=1, help="修补迭代次数（默认 1，仅 inpaint 模式）")
    parser.add_argument(
        "--scope", default="small", choices=["small", "large"],
        help="水印 ROI 范围：small=收紧贴合水印文字（默认），large=整角大框覆盖更彻底",
    )
    parser.add_argument(
        "--mode", default="inpaint", choices=["inpaint", "crop"],
        help="去水印模式：inpaint=ROI+插值修复保留原构图（默认）；crop=裁切去水印（等比缩放切掉水印）",
    )
    parser.add_argument(
        "--source-name", default=None,
        help="原始文件名（用于匹配内置 ROI；默认取输入文件 basename）",
    )
    parser.add_argument(
        "--analyze-only", action="store_true",
        help="只做自动水印分析，输出检测报告后退出（不执行处理）",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="强制走自动检测（跳过预置 ROI），适合自定义新视频",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    if not args.output:
        root, ext = os.path.splitext(args.input)
        args.output = f"{root}_clean{ext or '.mp4'}"

    manual_region = None
    if args.region:
        try:
            parts = [int(p.strip()) for p in args.region.split(",")]
            assert len(parts) == 4 and all(v >= 0 for v in parts)
            manual_region = tuple(parts)
        except (ValueError, AssertionError):
            print("Error: --region 格式错误，应为 x,y,w,h（如 10,5,120,60）", file=sys.stderr)
            return 1

    radius = max(1, min(args.radius or 3, 20))
    iterations = max(1, min(args.iterations or 1, 5))

    source_name = args.source_name or args.input

    # ---- ① 自动水印分析（同步 remove-mask 上游 v7：任意视频先分析再处理）----
    print('=' * 60, flush=True)
    print('① 自动水印分析', flush=True)
    print('=' * 60, flush=True)
    analysis = analyze_video(args.input)
    print(analysis['report'], flush=True)
    print(flush=True)

    # 已知视频且未强制 auto：优先用人工精调预置 ROI
    use_preset = None
    if not args.auto and not manual_region:
        use_preset = match_rois(source_name, scope=args.scope)
        if use_preset is not None:
            print(f'  命中预置 ROI 配置，使用人工精调框（--scope {args.scope}）', flush=True)

    if args.analyze_only:
        print('--analyze-only：仅分析，不执行处理。', flush=True)
        return 0

    # ---- ② 生成最佳处理方案 ----
    print('=' * 60, flush=True)
    print('② 最佳处理方案', flush=True)
    print('=' * 60, flush=True)
    if manual_region:
        rois = resolve_rois(source_name, manual_region, scope=args.scope)
        print(f'  方案: 手动指定区域 + {args.mode} 模式', flush=True)
    elif use_preset is not None:
        rois = use_preset
        print(f'  方案: 使用预置 ROI（{args.scope}）+ {args.mode} 模式', flush=True)
    else:
        rois = analysis_to_rois(analysis)
        if rois is None:
            print("Error: 无法读取视频，自动分析与回退均不可用", file=sys.stderr)
            return 10
        if analysis['found']:
            if args.mode == 'crop':
                print(f'  方案: 自动检测 ROI + {args.mode} 模式（等比缩放裁掉水印，画面无修复痕迹）', flush=True)
            else:
                print(f'  方案: 自动检测 ROI + {args.mode} 模式（inpaint 修复，保留原构图）', flush=True)
        else:
            print(f'  方案: 全角大框回退 + {args.mode} 模式（未检出水印，保守覆盖上下边缘）', flush=True)
    for c, r in rois.items():
        print(f'    {c}: y={r[0]}-{r[1]} x={r[2]}-{r[3]}', flush=True)
    print(flush=True)

    # ---- ③ 执行处理 ----
    print('=' * 60, flush=True)
    print('③ 执行处理', flush=True)
    print('=' * 60, flush=True)
    try:
        if args.mode == "crop":
            process_crop(args.input, args.output, rois)
        else:
            process(args.input, args.output, rois, radius=radius, iterations=iterations)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 未捕获异常: {e}", file=sys.stderr)
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
