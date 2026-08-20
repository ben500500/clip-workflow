# engines/seedance_wm/detect.py · [[video-processing-engines]] [[watermark-removal-degradation-chain]]

- _roi_image · function · L36-L40 — def _roi_image(img: np.ndarray, roi: dict) -> np.ndarray
- detect_watermark_seedance · function · L43-L116 — def detect_watermark_seedance( frames_dir: str | Path, config: DetectorConfig | None = None, max_sample_frames: int = 60, confidence_threshold: float = 0.6, roi: dict | None = None, ) -> dict
- _detect_yolov8 · function · L119-L150 — def _detect_yolov8( frames_dir: str | Path, config: DetectorConfig, roi: dict | None ) -> dict
- _detect_paddleocr · function · L153-L196 — def _detect_paddleocr( frames_dir: str | Path, config: DetectorConfig, roi: dict | None ) -> dict
- detect_watermark · function · L199-L261 — def detect_watermark( frames_dir: str | Path, primary: str = "matchTemplate", fallback: list[str] | None = None, bbox: list[int] | None = None, config: DetectorConfig | None = None, ) -> dict
