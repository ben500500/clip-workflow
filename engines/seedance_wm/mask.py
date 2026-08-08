"""阶段 3：mask 序列生成（bbox -> 帧级 mask PNG）。

mask 为单通道 uint8：白=水印（255），黑=背景（0）。
带形态学膨胀余量（默认 5px），给 LaMa 留修复空间。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from seedance_wm.log import get_logger

log = get_logger("mask")


def generate_mask_sequence(
    bbox: dict | list[dict],
    total_frames: int,
    width: int,
    height: int,
    output_dir: str | Path,
    expand_px: int = 5,
) -> dict:
    """生成帧级 mask 序列。

    bbox 可为单个 {x,y,w,h} 字典，也可为多个字典组成的列表（借 remove-mask
    经验库：一处视频可能同时存在左上 + 右下两个水印 ROI）。所有 box 会被合并到
    同一帧 mask 中。

    Returns:
        dict: {masks_dir, mask_files: list[str]}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if isinstance(bbox, dict):
        boxes = [bbox]
    else:
        boxes = list(bbox or [])
    if not boxes:
        raise ValueError("generate_mask_sequence: bbox 为空")

    expand = max(0, int(expand_px))
    rects = []
    for box in boxes:
        x = int(box["x"])
        y = int(box["y"])
        w = int(box["w"])
        h = int(box["h"])
        x1 = max(0, x - expand)
        y1 = max(0, y - expand)
        x2 = min(width, x + w + expand)
        y2 = min(height, y + h + expand)
        if x2 > x1 and y2 > y1:
            rects.append((x1, y1, x2, y2))
    if not rects:
        raise ValueError("generate_mask_sequence: 所有 bbox 均在画面外")

    mask_files: list[str] = []
    for i in range(total_frames):
        mask = np.zeros((height, width), dtype=np.uint8)
        for x1, y1, x2, y2 in rects:
            mask[y1:y2, x1:x2] = 255
        path = out / f"mask_{i:06d}.png"
        cv2.imwrite(str(path), mask)
        mask_files.append(str(path))

    log.info(
        "generate_mask_sequence Done: %d masks, %d box(es) expand=%d",
        total_frames,
        len(rects),
        expand,
    )
    return {"masks_dir": str(out), "mask_files": mask_files}
