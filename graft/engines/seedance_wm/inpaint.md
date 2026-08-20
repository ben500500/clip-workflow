# engines/seedance_wm/inpaint.py · [[video-processing-engines]] [[watermark-removal-degradation-chain]]

- _lama_model_ready · function · L29-L57 — def _lama_model_ready() -> bool
- resolve_device · function · L60-L70 — def resolve_device(device: str = "auto") -> str
- _inpaint_cv2 · function · L73-L81 — def _inpaint_cv2( image: np.ndarray, mask: np.ndarray, method: str = "cv2_telea", ) -> np.ndarray
- _inpaint_cv2_roi · function · L84-L98 — def _inpaint_cv2_roi( image: np.ndarray, mask: np.ndarray, method: str = "cv2_telea", ) -> np.ndarray
- _inpaint_lama · function · L104-L116 — def _inpaint_lama(image: np.ndarray, mask: np.ndarray, device: str) -> np.ndarray
- inpaint_frames · function · L119-L209 — def inpaint_frames( frames_dir: str | Path, masks_dir: str | Path, output_dir: str | Path, model: str = "lama", device: str = "auto", fp16: bool = True, progress_callback=None, roi_only: bool = False, ) -> dict
- _build_inpaint_chain · function · L212-L247 — def _build_inpaint_chain(model: str, device: str) -> list[tuple[str, str]]
- temporal_smooth · function · L250-L319 — def temporal_smooth( frames_dir: str | Path, window: int = 3, weights: str = "gaussian", ) -> dict
- _read_frame · function · L288-L293 — def _read_frame(i: int)
