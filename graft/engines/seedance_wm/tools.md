# engines/seedance_wm/tools.py

- extract_frames · function · L15-L26 — def extract_frames(video_path: str, output_dir: str, fps: float | None = None) -> dict
- detect_watermark · function · L29-L42 — def detect_watermark( frames_dir: str, primary: str = "matchTemplate", fallback: list[str] | None = None, bbox: list[int] | None = None, ) -> dict
- generate_mask_sequence · function · L45-L51 — def generate_mask_sequence( bbox: dict, frame_count: int, width: int, height: int, output_dir: str ) -> dict
- inpaint_frames · function · L54-L65 — def inpaint_frames( frames_dir: str, masks_dir: str, output_dir: str, model: str = "lama", device: str = "auto", fp16: bool = True, ) -> dict
- temporal_smooth · function · L68-L72 — def temporal_smooth(frames_dir: str, window: int = 3) -> dict
- mux_video · function · L75-L83 — def mux_video( frames_dir: str, audio_src: str | None, output_path: str, fps: int = 30, crf: int = 18, ) -> dict
- video_meta · function · L86-L96 — def video_meta(video_path: str) -> dict
