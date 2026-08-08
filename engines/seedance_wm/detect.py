"""阶段 2：水印检测模块。

降级链（TRD §3.2 / API §3.2）:
  matchTemplate（多帧均值 + 边缘聚簇，主检测）
    -> yolov8_seg（Ultralytics，可选）
    -> paddleocr（可选）
    -> 手动 bbox

所有检测器必须返回统一 dict: {x, y, w, h, confidence, method}
"""

from __future__ import annotations

import glob
from pathlib import Path

import cv2
import numpy as np

from seedance_wm.config import DetectorConfig
from seedance_wm.errors import DetectFailError
from seedance_wm.log import get_logger

log = get_logger("detect")

DETECTORS = ("matchTemplate", "yolov8_seg", "paddleocr")

# 检测器显示名（用于向用户展示已尝试的检测方法）
DETECTOR_DISPLAY = {
    "matchTemplate": "边缘模板检测",
    "yolov8_seg": "YOLO 目标检测",
    "paddleocr": "OCR 文字检测",
}


def _roi_image(img: np.ndarray, roi: dict) -> np.ndarray:
    h, w = img.shape[:2]
    h_ratio = min(max(float(roi.get("h_ratio", 0.12)), 0.0), 1.0)
    w_ratio = min(max(float(roi.get("w_ratio", 0.08)), 0.0), 1.0)
    return img[int(h * (1 - h_ratio)) :, int(w * (1 - w_ratio)) :]


def detect_watermark_seedance(
    frames_dir: str | Path,
    config: DetectorConfig | None = None,
    max_sample_frames: int = 60,
    confidence_threshold: float = 0.6,
    roi: dict | None = None,
) -> dict:
    """主检测器：多帧均值 + Canny 边缘 + 形态学闭运算 + 最大连通域。

    返回 bbox 为 ROI 内的相对坐标，调用方需转回全图坐标。
    """
    cfg = config or DetectorConfig()
    max_frames = max_sample_frames or cfg.max_sample_frames
    thresh = confidence_threshold or cfg.confidence_threshold
    roi_cfg = roi or cfg.roi

    frames = sorted(glob.glob(str(Path(frames_dir) / "frame_*.png")))[:max_frames]
    if not frames:
        raise DetectFailError("抽帧目录为空，无法检测")

    rois = []
    for f in frames:
        img = cv2.imread(f, cv2.IMREAD_COLOR)
        if img is None:
            continue
        rois.append(_roi_image(img, roi_cfg))
    if not rois:
        raise DetectFailError("无法读取任何帧")

    mean_roi = np.mean(rois, axis=0).astype(np.uint8)
    edges = cv2.Canny(mean_roi, 50, 150)
    score = float(np.sum(edges) / edges.size)
    if score < 0.001:
        raise DetectFailError("No watermark edges found")

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise DetectFailError("No contours")

    bbox = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(bbox)
    confidence = min(score * 100.0, 0.99)

    # ROI 相对坐标 -> 全图坐标（ROI 为原图右下角 w_ratio x h_ratio 区域）
    roi_h, roi_w = mean_roi.shape[:2]
    h_ratio = min(max(float(roi_cfg.get("h_ratio", 0.12)), 0.0), 1.0)
    w_ratio = min(max(float(roi_cfg.get("w_ratio", 0.08)), 0.0), 1.0)
    full_w = int(roi_w / w_ratio) if w_ratio > 0 else roi_w
    full_h = int(roi_h / h_ratio) if h_ratio > 0 else roi_h
    x_abs = int(x) + int(full_w * (1 - w_ratio))
    y_abs = int(y) + int(full_h * (1 - h_ratio))

    log.info(
        "detect_watermark matchTemplate: bbox=(%d,%d,%d,%d) conf=%.2f",
        x_abs,
        y_abs,
        int(w),
        int(h),
        confidence,
    )
    if confidence < thresh:
        raise DetectFailError(
            f"matchTemplate confidence {confidence:.3f} < threshold {thresh}"
        )
    return {
        "x": x_abs,
        "y": y_abs,
        "w": int(w),
        "h": int(h),
        "confidence": confidence,
        "method": "matchTemplate",
    }


def _detect_yolov8(
    frames_dir: str | Path, config: DetectorConfig, roi: dict | None
) -> dict:
    """兜底检测器 2：YOLOv8-seg（ultralytics，AGPL-3.0，可选）。"""
    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        raise DetectFailError("yolov8_seg 依赖未安装（pip install seedance-wm[yolo]）") from None

    model = YOLO("yolov8n-seg.pt")
    frames = sorted(glob.glob(str(Path(frames_dir) / "frame_*.png")))
    if not frames:
        raise DetectFailError("抽帧目录为空，无法检测")
    roi_cfg = roi or config.roi
    results = model(frames[: min(len(frames), config.max_sample_frames)], verbose=False)
    best = None
    for r in results:
        if r.boxes is None or len(r.boxes) == 0:
            continue
        for box, conf in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), strict=False):
            x1, y1, x2, y2 = box
            h_img, w_img = r.orig_shape
            # 只关注右下角区域的水印类目标
            rx1 = int(w_img * (1 - roi_cfg["w_ratio"]))
            ry1 = int(h_img * (1 - roi_cfg["h_ratio"]))
            if x1 >= rx1 and y1 >= ry1 and conf >= config.confidence_threshold:
                if best is None or conf > best[0]:
                    best = (float(conf), int(x1), int(y1), int(x2 - x1), int(y2 - y1))
    if best is None:
        raise DetectFailError("yolov8_seg: 0 命中")
    conf, x, y, w, h = best
    return {"x": x, "y": y, "w": w, "h": h, "confidence": conf, "method": "yolov8_seg"}


def _detect_paddleocr(
    frames_dir: str | Path, config: DetectorConfig, roi: dict | None
) -> dict:
    """兜底检测器 3：PaddleOCR（识别 "AI 生成" / "Seedance" 文本位置）。"""
    try:
        from paddleocr import PaddleOCR  # noqa: PLC0415
    except ImportError:
        raise DetectFailError("paddleocr 依赖未安装（pip install seedance-wm[ocr]）") from None

    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    frames = sorted(glob.glob(str(Path(frames_dir) / "frame_*.png")))
    if not frames:
        raise DetectFailError("抽帧目录为空，无法检测")
    keywords = ("ai", "生成", "seedance", "生成")
    for f in frames[: config.max_sample_frames]:
        img = cv2.imread(f)
        if img is None:
            continue
        h_img, w_img = img.shape[:2]
        result = ocr.ocr(f, cls=True)
        if not result:
            continue
        for line in result:
            if not line:
                continue
            for item in line:
                box, (text, conf) = item[0], item[1]
                text_l = text.lower()
                if conf >= config.confidence_threshold and any(
                    k in text_l for k in keywords
                ):
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    x, y = int(min(xs)), int(min(ys))
                    w, h = int(max(xs) - min(xs)), int(max(ys) - min(ys))
                    return {
                        "x": x,
                        "y": y,
                        "w": w,
                        "h": h,
                        "confidence": float(conf),
                        "method": "paddleocr",
                    }
    raise DetectFailError("paddleocr: 0 命中")


def detect_watermark(
    frames_dir: str | Path,
    primary: str = "matchTemplate",
    fallback: list[str] | None = None,
    bbox: list[int] | None = None,
    config: DetectorConfig | None = None,
) -> dict:
    """执行检测降级链。

    bbox 为手动指定 [x, y, w, h]，此时跳过自动检测直接返回。
    """
    cfg = config or DetectorConfig()
    if bbox and len(bbox) == 4:
        x, y, w, h = bbox
        return {
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "confidence": 1.0,
            "method": "manual",
            "attempted": ["manual"],
        }

    if primary not in DETECTORS:
        primary = cfg.primary if cfg.primary in DETECTORS else "matchTemplate"
    chain = [primary] + [d for d in (fallback or cfg.fallback) if d != primary]
    attempted: list[str] = []

    detectors = {
        "matchTemplate": lambda: detect_watermark_seedance(frames_dir, cfg),
        "yolov8_seg": lambda: _detect_yolov8(frames_dir, cfg, cfg.roi),
        "paddleocr": lambda: _detect_paddleocr(frames_dir, cfg, cfg.roi),
    }

    for name in chain:
        if name not in detectors:
            log.warning("未知检测器 %s，跳过", name)
            continue
        attempted.append(name)
        log.info("detect_watermark Trying %s", name)
        try:
            result = detectors[name]()
            result["attempted"] = attempted
            log.info(
                "detect_watermark OK method=%s bbox=(%d,%d,%d,%d) conf=%.2f",
                result["method"],
                result["x"],
                result["y"],
                result["w"],
                result["h"],
                result["confidence"],
            )
            return result
        except DetectFailError as e:
            log.warning("detect_watermark %s failed: %s", name, e.message)

    raise DetectFailError(
        "未检测到水印（已尝试: {}）。该视频可能本身不含水印，无需处理；"
        "如需移除特定位置的水印/角标，可在页面手动指定水印区域 (x,y,w,h)。".format(
            "、".join(DETECTOR_DISPLAY.get(name, name) for name in attempted)
        )
    )
