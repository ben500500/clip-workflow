# engines/seedance_wm/detect.py · [[seedance-watermark-removal-engine]]

Watermark detection module implementing a fallback chain of detectors (matchTemplate, YOLOv8-seg, PaddleOCR, manual bbox) that all return a unified bbox dict.

- _roi_image · function · L36-L40 — Crops the bottom-right corner region of a frame according to ROI ratios, clamping ratios to valid range.
- detect_watermark_seedance · function · L43-L116 — Primary detector that averages multiple frames, extracts Canny edges, closes them morphologically, and picks the largest contour as the watermark bbox, converting ROI-relative coords back to full-image coords.
- _detect_yolov8 · function · L119-L150 — Fallback detector using YOLOv8-seg to find watermark-class objects confined to the bottom-right ROI region, keeping the highest-confidence hit.
- _detect_paddleocr · function · L153-L196 — Fallback detector using PaddleOCR to locate text matching watermark keywords (AI/生成/Seedance) and return its bounding box.
- detect_watermark · function · L199-L261 — Orchestrates the detection fallback chain, honoring manual bbox override, validating the primary detector, and trying each detector in order until one succeeds.
