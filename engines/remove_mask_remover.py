#!/usr/bin/env python3
"""
Remove Mask 去水印引擎 —— 基于 ben500500/remove-mask 的「ROI + cv2.inpaint」方案

原理（沿用 remove-mask 仓库《去水印经验总结》思路）：
1. 不区分“哪些像素是水印”：直接把整个水印 ROI 矩形当掩码
2. cv2.inpaint 从 ROI 边界向内插值填充（TELEA 快速行进法 / NS 纳维-斯托克斯）
3. 按视频文件名匹配内置 ROI（基于全视频时序分析 + OCR 确认的水印框 + buffer）
4. 覆盖四角水印（Seedance 水印规律固定出现在左上/右上/右下角）
5. 参数保真：保留原始分辨率/帧率/编码，音频流复制零损耗

v7 核心升级（同步 ben500500/remove-mask 上游更新）：
**处理前自动分析任意视频**，不再局限于固定视频：
  ① 抽帧分析 → ② 自动检测水印带（半透明白色像素 + y/x 聚类）
  → ③ 生成最佳处理方案（检测不到时回退全角大框） → ④ 执行处理
  保留预置 ROI（已知 5 视频，含新增“爷孙重逢”）与 --scope/--mode 兼容；
  新增 --analyze-only（只分析）与 --auto（强制自动检测，跳过预置 ROI）。

v8/v9/v10/v11（同步 remove-mask 上游后续更新）：
  - v8：自动检测支持同一侧多个水印带（TL/TL2/TL3、BR/BR2），修复置信度
    计算（候选框带帧号，score 改为真实覆盖帧比例）
  - v9：新增时间一致性过滤剔除白发/人脸等移动亮色主体误判 + 文字带高度
    守卫（≤110px）
  - v10：自动检测改为四角（TL/TR/BL/BR）分别检测，可检出右上/右下等
    非贴边水印；收紧半透明白字判定；爷孙重逢 ROI 修正为右上 TR + 右下 BR
    （实测位置，不再误伤老人头部）
  - v11：自动检测改用四角时间一致性热力图 + 边缘先验（解决 v10 逐帧聚类
    对弱/淡色水印漏检，如爷孙重逢右上 TR）；爷孙重逢预置 ROI 补上左上角 TL
    水印覆盖（修复 TL 漏除）。

算法（--algo 切换，依据《引擎排名结论.md》）：
  - NS（cv2.INPAINT_NS）：默认推荐，修复 TL 后测试去除率最高（87.1%）
  - TELEA（cv2.INPAINT_TELEA）：86.4%，同样优秀
  结论：NS + small 预置 + radius=5（ns_small_r5）为最优方案；
  追求 TELEA 则 teela_small_r5 同样优秀；radius=5 全面优于 radius=3。

两种去水印模式（--mode 切换，同步 ben500500/remove-mask 上游更新）：
- inpaint（默认）：ROI + cv2.inpaint 插值修复，保留原始构图，水印区域被插值填充
- crop：裁切去水印，把包含水印的上下两条水平带裁掉，保留中间无字区域后等比放大回
  原始分辨率、左右对称居中裁回原始宽度。画面无修复痕迹但构图有裁剪/放大。
  适合画面上下无重要内容、宁可损失一点构图也不愿看到修复痕迹的场景。

预设方案（--preset，依据《引擎排名结论.md》按排名排序）：
  1. ns_small_r5   —— NS + small 预置 + radius=5（最优，去除率 87.1%）
  2. teela_small_r5—— TELEA + small 预置 + radius=5（86.4%）
  3. ns_small_r3   —— NS + small + radius=3（86.0%）
  4. teela_small_r3—— TELEA + small + radius=3（84.2%）
  5. ns_large_r3   —— NS + large + radius=3（85.6%）
  6. teela_large_r3—— TELEA + large + radius=3（83.3%）
  7. auto          —— 自动检测 ROI（兜底新视频）
  8. crop_small    —— 裁切去水印（不推荐，画面损失大）

CLI:
  python remove_mask_remover.py <输入视频> -o <输出视频> [options]

选项:
  -r, --region  x,y,w,h    手动指定水印区域（覆盖文件名匹配；x=列 y=行 w=宽 h=高）
  --preset     NAME       预设方案（见上方；默认 ns_small_r5，依排名最优）
  --algo       ns|telea   插值算法（默认 ns，依据《引擎排名结论》推荐）
  --scope      small|large 水印 ROI 范围（默认 small：收紧贴合水印文字；large：整角大框）
  --mode       inpaint|crop 去水印模式（默认 inpaint：ROI+插值修复；crop：裁切去水印）
  --radius      N          修补半径（默认 5，依据《引擎排名结论》radius=5 最优）
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
    """半透明白色水印像素：min 通道高 + 低饱和 + 局部比背景亮。

    v10 改进（同步 remove-mask 上游）：收紧判定条件，提高对“纯正白色半透明文字”
    的响应，降低把画面亮色主体（白发/衣物/灯光）误判为水印的概率。
    """
    f = frame.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    ming = np.minimum(np.minimum(r, g), b)
    maxg = np.maximum(np.maximum(r, g), b)
    sat = maxg - ming
    gg = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = cv2.medianBlur(gg.astype(np.uint8), 21).astype(np.float32)
    diff = gg - bg
    # 白色半透明文字：RGB 整体偏亮（min 通道较高）且接近白色（饱和低），
    # 并且明显亮于局部背景（半透明叠加会在背景上产生稳定正增益）。
    sw = ((ming > 105) & (sat < 40) & (diff > 8) & (maxg > 150)).astype(np.uint8)
    sw = cv2.morphologyEx(sw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    sw = cv2.dilate(sw, np.ones((3, 3), np.uint8), iterations=1)
    return sw


def _static_consistency_filter(frames, boxes, N, H, W, min_static=0.25):
    """v9：时间一致性过滤，剔除“移动的亮色主体”（如老头的白发）误判为水印。

    原理：水印是固定叠加的静态文字——同一像素位置在多帧中反复出现；
    而白发/人脸等移动主体在不同帧出现在不同位置，同一像素被反复检出的
    概率远低于静态水印。

    注意：半透明水印只在背景较暗的帧中被检出，且可能分段移动，因此
    本过滤器只剔除【一致性极低且面积很大】的主体区域（避免误伤真水印），
    真正的判定交给后续的高度守卫（文字水印为水平细长条）。

    返回过滤后的 boxes 列表。
    """
    if not boxes:
        return boxes
    # 累计每像素被检出的帧数
    acc = np.zeros((H, W), dtype=np.float32)
    for f in frames:
        acc += _semi_white_mask(f)
    n_frames = len(frames)
    if n_frames == 0:
        return boxes
    thr = max(2, n_frames * min_static)

    out = []
    for (y0, y1, x0, x1, fid) in boxes:
        sub = acc[y0:y1 + 1, x0:x1 + 1]
        active = (sub > 0).sum()
        if active < 5:
            continue
        static = (sub >= thr).sum()
        ratio = static / active
        band_h = y1 - y0 + 1
        band_w = x1 - x0 + 1
        # 仅剔除“极低一致性 + 非细长条”的候选（即移动主体大块区域）：
        # 文字水印即使一致性低，也是水平细长条（高≤110px 且 宽≥3倍高），
        # 予以保留；大面积主体（高>110 或 宽<2倍高）且一致性<5% 则剔除。
        is_text_like = (band_h <= 110) and (band_w >= 3 * band_h)
        if ratio < 0.05 and not is_text_like:
            continue
        out.append((y0, y1, x0, x1, fid))
    return out


def _detect_text_bands(video_path, step=2, max_frames=200):
    """逐帧检测四角水平文字带，返回 (corner_boxes, N, H, W)。

    corner_boxes: dict，键为 'TL'/'TR'/'BL'/'BR'，
      值为每帧检测到的水印候选框列表 [(y0,y1,x0,x1,fid), ...]
    v10 改进（同步 remove-mask 上游）：由“上下两条带”改为“四个角”分别检测，
    可检出右上（TR）/右下（BR）等非贴边但位于角落的水印。
    """
    frames, total = _load_sampled_frames(video_path, step, max_frames)
    if frames is None:
        return None
    N = frames.shape[0]
    H, W = frames.shape[1], frames.shape[2]
    # 四角检测区域：上下各 35%，左右各 55%
    zones = {
        'TL': (0, int(H * 0.35), 0, int(W * 0.55)),
        'TR': (0, int(H * 0.35), int(W * 0.45), W),
        'BL': (int(H * 0.65), H, 0, int(W * 0.55)),
        'BR': (int(H * 0.65), H, int(W * 0.45), W),
    }
    corner_boxes = {k: [] for k in zones}
    for i in range(N):
        sw = _semi_white_mask(frames[i])
        for cname, (z0, z1, zx0, zx1) in zones.items():
            sub = sw[z0:z1, zx0:zx1]
            if sub.sum() < 3:
                continue
            rsum = sub.sum(axis=1)
            thr = max(4, rsum.max() * 0.3)
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
                if (ry1 - ry0) < 6 or (ry1 - ry0) > 150:
                    continue
                sub2 = sw[ry0:ry1 + 1, :]
                csum = sub2.sum(axis=0)
                thr_c = max(3, csum.max() * 0.3)
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
                    if (cx1 - cx0) < 25 or (cx1 - cx0) > W * 0.5:
                        continue
                    corner_boxes[cname].append((ry0, ry1, cx0, cx1, i))
    # v9/v10：时间一致性过滤，剔除移动亮色主体（白发/人脸）误判
    for cname in corner_boxes:
        corner_boxes[cname] = _static_consistency_filter(
            frames, corner_boxes[cname], N, H, W)
    return corner_boxes, N, H, W


def _detect_corner_heatmap(video_path, step=2, max_frames=200, fthr=0.04):
    """四角热力图水印带检测器（v11，同步 remove-mask 上游）。

    基于“时间一致性热力图 + 边缘先验”的改进版检测器，解决 v10 逐帧聚类
    对弱/淡色水印漏检的问题（如《爷孙重逢》右上角 TR 水印）。

    原理：
      - 统计每像素在半透明白色掩码中被检出的帧比例（frac）——真正的静态水印
        会在固定位置反复出现，故 frac 高；移动的亮色主体（白发/衣物）则低。
      - 四个角（TL/TR/BL/BR）分别处理，保留角身份，避免漏盖某个角。
      - 只保留水平细长条带（高度 ≤ 100px，即文字水印特征），排除大块主体。
      - 置信度不足的候选必须靠近画面边缘（左右 15% 或上下 12%），
        进一步抑制画面中央亮色主体误判。

    返回 (corner_bands, N, H, W)：
      corner_bands: dict，键为 'TL'/'TR'/'BL'/'BR'，值为检测到的水印带
        列表 [(y0,y1,x0,x1,score), ...]。
    """
    frames, total = _load_sampled_frames(video_path, step, max_frames)
    if frames is None:
        return None
    N = frames.shape[0]
    H, W = frames.shape[1], frames.shape[2]
    # 累加每像素被检出的帧数 -> 时间一致性热力图
    acc = np.zeros((H, W), dtype=np.float32)
    for f in frames:
        acc += _semi_white_mask(f).astype(np.float32)
    frac = acc / N

    # 四个角区域（每个占画面一半宽、一半高），保留角身份
    zones = {
        'TL': (0, int(H * 0.5), 0, int(W * 0.5)),
        'TR': (0, int(H * 0.5), int(W * 0.5), W),
        'BL': (int(H * 0.5), H, 0, int(W * 0.5)),
        'BR': (int(H * 0.5), H, int(W * 0.5), W),
    }
    corner_bands = {k: [] for k in zones}
    for zname, (z0, z1, zx0, zx1) in zones.items():
        reg = frac[z0:z1, zx0:zx1]
        m = (reg >= fthr).astype(np.uint8)
        if m.sum() < 8:
            continue
        _n, labels, stats, _c = cv2.connectedComponentsWithStats(m, 8)
        comps = []
        for i in range(1, _n):
            x, y, w, h, a = stats[i]
            # 文字水印特征：宽度≥12、高度 5~100px、面积≥20px
            if w < 12 or h < 5 or h > 100 or a < 20:
                continue
            y0f = y + z0; y1f = y + h + z0 - 1
            x0f = x + zx0; x1f = x + w + zx0 - 1
            score = float(frac[y0f:y1f + 1, x0f:x1f + 1].max())
            # 边缘先验：靠近左右边缘或上下边缘才保留弱候选，抑制中央亮色主体
            near_lr = x0f < 0.15 * W or x1f > 0.85 * W
            near_tb = ((zname in ('TL', 'TR') and y0f < 0.12 * H) or
                       (zname in ('BL', 'BR') and y1f > 0.88 * H))
            if score < 0.10 and not (near_lr or near_tb):
                continue
            comps.append([y0f, y1f, x0f, x1f, score])
        # 合并同一水平带内相邻（y 重叠、x gap ≤ 90）的候选
        comps.sort(key=lambda c: (c[0] + c[1]) / 2)
        merged = []
        for c in comps:
            placed = False
            for mr in merged:
                if c[0] <= mr[1] + 4 and c[1] >= mr[0] - 4:
                    gap = max(0, max(c[2], mr[2]) - min(c[3], mr[3]))
                    if gap <= 90:
                        mr[0] = min(mr[0], c[0]); mr[1] = max(mr[1], c[1])
                        mr[2] = min(mr[2], c[2]); mr[3] = max(mr[3], c[3])
                        mr[4] = max(mr[4], c[4])
                        placed = True
                        break
            if not placed:
                merged.append(list(c))
        corner_bands[zname] = [tuple(c) for c in merged if (c[1] - c[0]) <= 100]
    return corner_bands, N, H, W


def _cluster_boxes(boxes, N, H, W, bin_h=12):
    """对候选框聚类：y 直方图峰值分带 + 带内 x 聚类。

    返回 [(y0,y1,x0,x1,score), ...]，score = 该簇覆盖的帧比例。
    v9/v10（同步 remove-mask 上游）：score 改为按真实帧号去重统计；
    新增高度守卫（文字水印为水平细长条，高≤110px），避免把白发/人脸
    等移动亮色主体误判为水印。
    """
    if len(boxes) < max(4, N * 0.03):
        return []
    boxes = np.array(boxes, dtype=np.float32)
    cy = (boxes[:, 0] + boxes[:, 1]) / 2
    cx = (boxes[:, 2] + boxes[:, 3]) / 2
    frame_ids = boxes[:, 4].astype(int)  # 每帧检测到的 box 所来自的帧号

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
        if (y1 - y0) < 10 or (y1 - y0) > 220:
            hist_y[max(0, pk - 2):pk + 3] = 0
            continue
        # v9：高度守卫——真正的文字水印是水平细长条（高≤110px），
        # 过高的带很可能是移动主体（如老头的白发/脸）而不是水印文字。
        if (y1 - y0) > 110:
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
            frames_hit = set(int(frame_ids[i]) for i in orig_idx[xb])
            score = len(frames_hit) / N
            out.append((y0, y1, x0, x1, score))
        hist_y[max(0, pk - 2):pk + 3] = 0
    return out


def _merge_bands(bands):
    """把同一 top/bottom 带内的多个候选框合并成完整覆盖框。

    同一行带内（y 重叠）的多个 x 段合并为一个大框（取 min/max），
    避免左右分段水印被拆成多个小 ROI。
    v10 改进（同步 remove-mask 上游）：合并后若高度超过 120px（远超文字水印高度），
    或宽度超过画面一半，则视为误合并（覆盖了画面主体），回退为不合并。
    """
    if not bands:
        return []
    bands = sorted(bands, key=lambda b: (b[0] + b[1]) / 2)
    groups = []
    for b in bands:
        placed = False
        for g in groups:
            gy0 = min(x[0] for x in g)
            gy1 = max(x[1] for x in g)
            gx0 = min(x[2] for x in g)
            gx1 = max(x[3] for x in g)
            # y 重叠 且 x 区间接近（gap ≤ 80px）才合并，避免把相隔很远的
            # 候选（不同位置的水印/画面内容）错误合并成一个覆盖主体的大框
            if b[0] <= gy1 and b[1] >= gy0:
                gap = max(0, max(b[2], gx0) - min(b[3], gx1))
                if gap <= 80:
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
        # v10：合并后高度过大（覆盖画面主体）或宽度过大则拆分回原候选，
        # 只保留其中面积最大的一个带，避免误伤主体。
        if (y1 - y0) > 120 or (x1 - x0) > 0.55 * 720:
            best = max(g, key=lambda b: b[4])
            merged.append(best)
            continue
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
    # v11（同步 remove-mask 上游）：改用四角时间一致性热力图 + 边缘先验检测器
    det = _detect_corner_heatmap(video_path)
    if det is None:
        return {'found': False, 'top': [], 'bottom': [], 'H': 0, 'W': 0,
                'N': 0, 'fallback': True, 'report': '无法读取视频'}
    corner_bands, N, H, W = det

    # 每个角独立保留身份（v11：四角全覆盖，不再漏盖任意一个角）
    top = []
    bottom = []
    for cname in ('TL', 'TR', 'BL', 'BR'):
        bands = corner_bands[cname]
        if cname in ('TL', 'TR'):
            top.extend(bands)
        else:
            bottom.extend(bands)

    # 同一侧多个候选时，按置信度排序保留多个（支持水印分段出现/多位置）
    if top:
        top = sorted(top, key=lambda b: (-b[4], b[0]))
        top = top[:12]
        top = sorted(top, key=lambda b: b[0])
    if bottom:
        bottom = sorted(bottom, key=lambda b: (-b[4], -b[1]))
        bottom = bottom[:12]
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
    """把分析结果转成 inpaint 用的 ROI dict（v11 四角感知，同步 remove-mask 上游）。

    v11 改进：不再把顶部带一律映射为 TL、底部带一律映射为 BR，而是根据每条
    水印带的 x 中心判断其属于左(TL/BL)还是右(TR/BR)角，从而做到真正的
    “四角全覆盖”——左上、右上、左下、右下各自独立覆盖。
    v8 改进：同一角存在多个候选带时（水印位置随时间变化/分段出现），会为
    每个候选带分别生成 ROI（TL / TL2 / TL3 …、BR / BR2 …）。
    v10 改进：严格过滤误检带——仅保留置信度足够高的带，且所有 ROI 高度限制
    ≤ 110px（真实文字水印为水平细长条），避免把画面主体（老人白发/头部）等
    大块区域误当水印覆盖。未检测到则回退全角大框。
    """
    H, W = analysis['H'], analysis['W']
    if H <= 0 or W <= 0:
        return None
    rois = {}
    buf = margin
    MAX_ROI_H = 110

    def _band_ok(b):
        """候选带是否可作为 ROI：置信度足够 + 高度合理（文字水印特征）。"""
        return b[4] >= 0.09 and (b[1] - b[0]) <= MAX_ROI_H

    def _to_roi(b):
        y0, y1, x0, x1 = b[0], b[1], b[2], b[3]
        return (max(0, y0 - buf), min(H - 1, y1 + buf),
                max(0, x0 - buf), min(W - 1, x1 + buf))

    def _merge_y_overlap(roi_list):
        """合并 y 重叠且 x 相近的 ROI，返回合并后的 ROI 列表。"""
        if not roi_list:
            return []
        roi_list = sorted(roi_list, key=lambda r: r[0])
        merged = []
        for r in roi_list:
            placed = False
            for mr in merged:
                if r[0] <= mr[1] + 4 and r[1] >= mr[0] - 4:
                    gap = max(0, max(r[2], mr[2]) - min(r[3], mr[3]))
                    if gap <= 50:
                        mr[0] = min(mr[0], r[0])
                        mr[1] = max(mr[1], r[1])
                        mr[2] = min(mr[2], r[2])
                        mr[3] = max(mr[3], r[3])
                        placed = True
                        break
            if not placed:
                merged.append(list(r))
        return merged

    def _emit(prefix, merged):
        """把合并后的 ROI 写入 rois（单个用前缀，多个用前缀+序号）。"""
        if len(merged) == 1:
            rois[prefix] = tuple(merged[0])
        else:
            for i, r in enumerate(merged):
                rois[f'{prefix}{i + 1}'] = tuple(r)

    top = analysis.get('top', [])
    bottom = analysis.get('bottom', [])

    # ---- 顶部：TL 与 TR 分开 ----
    for corner, prefix in (('TL', 'TL'), ('TR', 'TR')):
        bands = [b for b in top
                 if ((b[2] + b[3]) / 2 < W / 2) == (corner == 'TL')]
        # 边缘先验：TR 角水印应贴近右边缘或顶边缘；TL 角应贴近左边缘或顶边缘。
        # 高置信度（≥0.5）的带本身已是强水印证据，无需再受边缘约束。
        def _corner_edge_ok(b):
            y0, y1, x0, x1 = b[0], b[1], b[2], b[3]
            if b[4] >= 0.5:
                return True
            if corner == 'TL':
                return x0 < 0.10 * W or y0 < 0.10 * H
            else:  # TR
                return x1 > 0.90 * W or y0 < 0.10 * H

        bands = [b for b in bands if _corner_edge_ok(b)]
        # 非贴顶（y 中心 > 上 15%）的带必须置信度足够高才保留
        ok = [b for b in bands if _band_ok(b)
              and ((b[0] + b[1]) / 2 <= H * 0.15 or b[4] >= 0.20)]
        if ok:
            ok = sorted(ok, key=lambda b: -b[4])[:2]
            roi_list = []
            for b in ok:
                r = _to_roi(b)
                if (r[1] - r[0]) > MAX_ROI_H + 8:
                    continue
                roi_list.append(list(r))
            if roi_list:
                _emit(prefix, _merge_y_overlap(roi_list))
            else:
                rois[prefix] = (0, int(H * 0.20) + buf, 0, W)
        else:
            # 回退：该角所在半侧顶部 20% 全宽（保守覆盖，确保暗水印不遗漏）
            x0 = 0 if corner == 'TL' else W // 2
            x1 = W // 2 if corner == 'TL' else W
            rois[prefix] = (0, int(H * 0.20) + buf, x0, x1)

    # ---- 底部：BL 与 BR 分开 ----
    for corner, prefix in (('BL', 'BL'), ('BR', 'BR')):
        bands = [b for b in bottom
                 if ((b[2] + b[3]) / 2 < W / 2) == (corner == 'BL')]
        def _corner_edge_ok(b):
            y0, y1, x0, x1 = b[0], b[1], b[2], b[3]
            if b[4] >= 0.5:
                return True
            if corner == 'BL':
                return x0 < 0.10 * W or y1 > 0.90 * H
            else:  # BR
                return x1 > 0.90 * W or y1 > 0.90 * H

        bands = [b for b in bands if _corner_edge_ok(b)]
        # 非贴底（y 中心 < 下 15%）的带必须置信度足够高才保留
        ok = [b for b in bands if _band_ok(b)
              and ((b[0] + b[1]) / 2 >= H * 0.85 or b[4] >= 0.20)]
        if ok:
            ok = sorted(ok, key=lambda b: -b[4])[:2]
            roi_list = []
            for b in ok:
                r = _to_roi(b)
                if (r[1] - r[0]) > MAX_ROI_H + 8:
                    continue
                roi_list.append(list(r))
            if roi_list:
                _emit(prefix, _merge_y_overlap(roi_list))
            else:
                x0 = 0 if corner == 'BL' else W // 2
                x1 = W // 2 if corner == 'BL' else W
                rois[prefix] = (int(H * 0.87) - buf, H, x0, x1)
        else:
            x0 = 0 if corner == 'BL' else W // 2
            x1 = W // 2 if corner == 'BL' else W
            rois[prefix] = (int(H * 0.87) - buf, H, x0, x1)

    return rois


def process_crop(video_path, output_path, rois):
    """裁切去水印：裁掉覆盖水印的上下水平带，剩余画面等比放大回原高并居中裁回原宽。

    同步自 ben500500/remove-mask 上游 --mode crop 实现：
      顶部水印(TL)下边缘以上、底部水印(BR)上边缘以下整条水平带裁掉，
      保留中间无字区域，等比放大回原始高度，左右对称居中裁回原始宽度。
    """
    print("水印 ROI:", flush=True)
    for c, roi in rois.items():
        print(f"  {c}: {tuple(int(v) for v in roi)}", flush=True)

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


def process(video_path, output_path, rois, radius=5, iterations=1, algo='ns'):
    print("水印 ROI:")
    for c, roi in rois.items():
        print(f"  {c}: {tuple(int(v) for v in roi)}", flush=True)

    if algo not in ('ns', 'telea'):
        algo = 'ns'
    inpaint_flag = cv2.INPAINT_NS if algo == 'ns' else cv2.INPAINT_TELEA
    algo_label = 'NS' if algo == 'ns' else 'TELEA'
    print(f"算法: {algo_label}（radius={radius}, iterations={iterations}）", flush=True)

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
            result = cv2.inpaint(result, mask, radius, inpaint_flag)
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
        description="Remove Mask 去水印引擎（ROI + cv2.inpaint NS/TELEA / 裁切）",
    )
    parser.add_argument("input", help="输入视频路径")
    parser.add_argument("-o", "--output", help="输出视频路径")
    parser.add_argument(
        "-r", "--region",
        help="手动水印区域 x,y,w,h（覆盖文件名匹配；x=列 y=行 w=宽 h=高）",
    )
    parser.add_argument(
        "--preset", default=None,
        help=(
            "预设方案（按《引擎排名结论.md》排名排序）："
            "ns_small_r5（最优，默认）/ teela_small_r5 / ns_small_r3 / "
            "teela_small_r3 / ns_large_r3 / teela_large_r3 / auto（自动检测兜底）/ "
            "crop_small / crop_large。指定 preset 后覆盖 --algo/--scope/--mode/--radius。"
        ),
    )
    parser.add_argument(
        "--algo", default=None, choices=["ns", "telea"],
        help="插值算法：ns（默认推荐，依据《引擎排名结论》）/ telea（同样优秀）",
    )
    parser.add_argument("--radius", type=int, default=5, help="修补半径（默认 5，依据《引擎排名结论》radius=5 最优）")
    parser.add_argument("--iterations", type=int, default=1, help="修补迭代次数（默认 1，仅 inpaint 模式生效）")
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

    # ── 预设方案（依据《引擎排名结论.md》，按排名排序）──
    # 排名 1~10：NS/TELEA 插值 + small/large 预置 + radius 3/5，自动检测，裁切
    PRESETS = {
        'ns_small_r5':    {'algo': 'ns',    'scope': 'small', 'mode': 'inpaint', 'radius': 5, 'rank': 1},
        'teela_small_r5': {'algo': 'telea', 'scope': 'small', 'mode': 'inpaint', 'radius': 5, 'rank': 2},
        'ns_small_r3':    {'algo': 'ns',    'scope': 'small', 'mode': 'inpaint', 'radius': 3, 'rank': 3},
        'ns_large_r3':    {'algo': 'ns',    'scope': 'large', 'mode': 'inpaint', 'radius': 3, 'rank': 4},
        'teela_small_r3': {'algo': 'telea', 'scope': 'small', 'mode': 'inpaint', 'radius': 3, 'rank': 5},
        'teela_large_r3': {'algo': 'telea', 'scope': 'large', 'mode': 'inpaint', 'radius': 3, 'rank': 6},
        'auto':           {'algo': 'ns',    'scope': 'small', 'mode': 'inpaint', 'radius': 5, 'rank': 7, 'force_auto': True},
        'crop_small':     {'algo': 'ns',    'scope': 'small', 'mode': 'crop',    'radius': 5, 'rank': 8},
        'crop_large':     {'algo': 'ns',    'scope': 'large', 'mode': 'crop',    'radius': 5, 'rank': 9},
    }

    # 应用 preset（覆盖单项参数）；未指定时用命令行单项（默认 ns + small + inpaint + r5）
    preset = args.preset
    if preset:
        if preset not in PRESETS:
            print(f"Error: 未知预设方案 {preset}，可用: {', '.join(PRESETS)}", file=sys.stderr)
            return 1
        p = PRESETS[preset]
        algo = p['algo']
        scope = p['scope']
        mode = p['mode']
        radius = p['radius']
        force_auto = p.get('force_auto', False)
        print(f'  预设方案: {preset}（排名 #{p["rank"]}）', flush=True)
    else:
        algo = args.algo or 'ns'
        scope = args.scope
        mode = args.mode
        radius = max(1, min(args.radius or 5, 20))
        force_auto = False

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
    if not args.auto and not force_auto and not manual_region:
        use_preset = match_rois(source_name, scope=scope)
        if use_preset is not None:
            print(f'  命中预置 ROI 配置，使用人工精调框（--scope {scope}）', flush=True)

    if args.analyze_only:
        print('--analyze-only：仅分析，不执行处理。', flush=True)
        return 0

    # ---- ② 生成最佳处理方案 ----
    print('=' * 60, flush=True)
    print('② 最佳处理方案', flush=True)
    print('=' * 60, flush=True)
    if manual_region:
        rois = resolve_rois(source_name, manual_region, scope=scope)
        print(f'  方案: 手动指定区域 + {mode} 模式', flush=True)
    elif use_preset is not None:
        rois = use_preset
        print(f'  方案: 使用预置 ROI（{scope}）+ {mode} 模式', flush=True)
    else:
        rois = analysis_to_rois(analysis)
        if rois is None:
            print("Error: 无法读取视频，自动分析与回退均不可用", file=sys.stderr)
            return 10
        if analysis['found']:
            if mode == 'crop':
                print(f'  方案: 自动检测 ROI + {mode} 模式（等比缩放裁掉水印，画面无修复痕迹）', flush=True)
            else:
                print(f'  方案: 自动检测 ROI + {mode} 模式（inpaint 修复，保留原构图）', flush=True)
        else:
            print(f'  方案: 全角大框回退 + {mode} 模式（未检出水印，保守覆盖上下边缘）', flush=True)
    for c, r in rois.items():
        print(f'    {c}: y={r[0]}-{r[1]} x={r[2]}-{r[3]}', flush=True)
    print(flush=True)

    # ---- ③ 执行处理 ----
    print('=' * 60, flush=True)
    print('③ 执行处理', flush=True)
    print('=' * 60, flush=True)
    try:
        if mode == "crop":
            process_crop(args.input, args.output, rois)
        else:
            process(args.input, args.output, rois, radius=radius, iterations=iterations, algo=algo)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 未捕获异常: {e}", file=sys.stderr)
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
