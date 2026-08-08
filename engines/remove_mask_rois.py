#!/usr/bin/env python3
"""remove-mask 去水印经验共享模块。

集成自 ben500500/remove-mask 仓库《去水印经验总结》：
基于全视频 OCR + 时序分析确认的水印 ROI 表（覆盖 Seedance 左上 + 右下角规律），
参数保真。remove_mask 引擎直接使用本表；其它引擎（seedance_wm / seedance /
remove_ai 区域擦除）在未指定手动区域时，可通过 match_rois 命中内置经验库，
把确认过的 ROI 作为「经验回退」直接使用，避免自动检测漏检/误检。

ROI 参考坐标系：1280x720（H×W，竖屏视频 720×1280），格式 (y0, y1, x0, x1)。

两套 ROI 范围（同步 remove-mask 上游更新）：
- small（默认）：新版收紧 ROI，严格贴合水印文字 + 6px buffer，遮盖面积小
- large：旧版整角大框，覆盖更彻底，但会误伤角部非水印画面
"""

from __future__ import annotations

import os
import re
from typing import Optional

# ── small（默认）：收紧 ROI，严格贴合水印文字像素 + 6px buffer ──
# Seedance 水印为左上/右下两个水平文字带（约 36~40px 高）：
#   TL 带：y≈42-79，x≈49-218（各视频微差）
#   BR 带：y≈1202-1240，x≈506-687
VIDEO_ROIS_SMALL = {
    '648BC321': {
        'TL': (36, 85, 51, 218),
        'BR': (1196, 1245, 506, 687),
    },
    'C0CC0472': {
        'TL': (36, 85, 50, 212),
        'BR': (1196, 1246, 507, 687),
    },
    '0270150E': {
        'TL': (36, 85, 52, 210),
        'BR': (1196, 1245, 506, 687),
    },
    '3906E761': {
        'TL': (36, 85, 49, 224),
        'BR': (1197, 1245, 506, 678),
    },
}

# ── large（旧版）：整角大框，覆盖更彻底，但遮盖面积明显更大 ──
VIDEO_ROIS_LARGE = {
    '648BC321': {
        'TL': (20, 100, 40, 285),
        'BR': (1170, 1270, 500, 705),
    },
    'C0CC0472': {
        'TL': (35, 90, 38, 240),
        'BR': (1185, 1245, 550, 675),
    },
    '0270150E': {
        'TL': (20, 110, 30, 245),
        'BR': (1150, 1270, 435, 705),
    },
    '3906E761': {
        'TL': (20, 95, 20, 240),
        'BR': (1150, 1270, 500, 705),
    },
}

# 默认使用 small（收紧 ROI）——同步 remove-mask 上游默认行为
VIDEO_ROIS = VIDEO_ROIS_SMALL
VIDEO_ROIS_BY_SCOPE = {
    'small': VIDEO_ROIS_SMALL,
    'large': VIDEO_ROIS_LARGE,
}

# 内置 ROI 的参考坐标系（720×1280 竖屏视频）
REF_H, REF_W = 1280, 720

# 通用默认 ROI（Seedance 水印规律：左上 + 右下），未匹配到内置配置时使用。
# 与默认 small 一致（收紧版，减少对画面的干预）
DEFAULT_ROIS = {
    'TL': (36, 85, 51, 218),
    'BR': (1196, 1245, 506, 687),
}


def _norm_source_name(source_name: str) -> str:
    base = os.path.splitext(os.path.basename(source_name or ''))[0]
    return base.upper()


def match_rois(source_name: str, scope: str = 'small') -> Optional[dict]:
    """按原始文件名匹配内置 ROI 经验库（scope: small/large，默认 small）。

    先精确匹配全名，再从文件名中提取 8 位大写码（如 ``648BC321_xxx.mp4``、
    ``xxx-648BC321.mp4``）匹配。未命中返回 None（由调用方决定是否回退通用默认）。
    """
    table = VIDEO_ROIS_BY_SCOPE.get(scope, VIDEO_ROIS_SMALL)
    norm = _norm_source_name(source_name)
    if norm in table:
        return table[norm]
    for code in re.findall(r'[0-9A-Z]{8}', norm):
        if code in table:
            return table[code]
    return None


def resolve_rois(source_name: str, manual_region=None, scope: str = 'small') -> dict:
    """决定使用的 ROI 配置。优先级：手动区域 > 文件名匹配内置 > 通用默认。

    scope: small/large（默认 small，收紧 ROI；large 为旧版整角大框）。
    返回 {name: (y0, y1, x0, x1)}，与 remove_mask 引擎原逻辑一致。
    """
    if manual_region:
        x, y, w, h = manual_region
        return {'manual': (y, y + h, x, x + w)}
    rois = match_rois(source_name, scope)
    if rois:
        return rois
    return DEFAULT_ROIS


def build_mask(rois: dict, H: int, W: int) -> "np.ndarray":
    """把 (y0,y1,x0,x1) 的 ROI 掩码按实际分辨率等比缩放到 H×W。"""
    import numpy as np

    mask = np.zeros((H, W), dtype=np.uint8)
    sh, sw = H / REF_H, W / REF_W
    for _name, (y0, y1, x0, x1) in rois.items():
        _y0 = int(y0 * sh)
        _y1 = max(_y0 + 1, int(y1 * sh))
        _x0 = int(x0 * sw)
        _x1 = max(_x0 + 1, int(x1 * sw))
        mask[_y0:_y1, _x0:_x1] = 255
    return mask


def rois_to_bboxes(rois: dict, width: int, height: int) -> list[tuple[int, int, int, int]]:
    """把 (y0,y1,x0,x1) ROI 等比缩放到实际分辨率，转成 (x,y,w,h) bbox 列表。

    供 seedance_wm / seedance / remove_ai 等引擎在未指定手动区域、且命中内置
    经验库时直接使用。
    """
    sh = height / REF_H
    sw = width / REF_W
    boxes = []
    for _name, (y0, y1, x0, x1) in rois.items():
        x = int(round(x0 * sw))
        y = int(round(y0 * sh))
        w = max(1, int(round((x1 - x0) * sw)))
        h = max(1, int(round((y1 - y0) * sh)))
        boxes.append((x, y, w, h))
    return boxes


def probe_video_size(video_path: str) -> tuple[int, int]:
    """用 OpenCV 快速探测视频宽高 (width, height)，失败返回 (0, 0)。"""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        try:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            cap.release()
        return (w, h) if w > 0 and h > 0 else (0, 0)
    except Exception:  # noqa: BLE001
        return (0, 0)
