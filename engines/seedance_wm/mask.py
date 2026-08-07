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
    bbox: dict,
    total_frames: int,
    width: int,
    height: int,
    output_dir: str | Path,
    expand_px: int = 5,
) -> dict:
    """生成帧级 mask 序列。

    Returns:
        dict: {masks_dir, mask_files: list[str]}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    x = int(bbox["x"])
    y = int(bbox["y"])
    w = int(bbox["w"])
    h = int(bbox["h"])
    expand = max(0, int(expand_px))

    x1 = max(0, x - expand)
    y1 = max(0, y - expand)
    x2 = min(width, x + w + expand)
    y2 = min(height, y + h + expand)

    mask_files: list[str] = []
    for i in range(total_frames):
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[y1:y2, x1:x2] = 255
        path = out / f"mask_{i:06d}.png"
        cv2.imwrite(str(path), mask)
        mask_files.append(str(path))

    log.info(
        "generate_mask_sequence Done: %d masks, bbox=(%d,%d,%d,%d) expand=%d",
        total_frames,
        x1,
        y1,
        x2 - x1,
        y2 - y1,
        expand,
    )
    return {"masks_dir": str(out), "mask_files": mask_files}
