# engines/seedance_wm/pipeline.py · [[seedance-wm-engine]] [[seedance-wm-resumability-state]]

- ProcessResult · class · L41-L51 — class ProcessResult
- _State · class · L54-L85 — class _State
- __init__ · method · L57-L63 — def __init__(self, cache_dir: Path)
- load · method · L65-L75 — def load(self, video_hash: str) -> bool
- save · method · L77-L79 — def save(self) -> None
- mark_done · method · L81-L82 — def mark_done(self, stage: str) -> None
- is_done · method · L84-L85 — def is_done(self, stage: str) -> bool
- _video_hash · function · L88-L96 — def _video_hash(path: str | Path) -> str
- _cache_dir · function · L99-L100 — def _cache_dir(config: Config, video_hash: str) -> Path
- _ensure_disk · function · L103-L108 — def _ensure_disk(cache_dir: Path, video_hash: str) -> None
- _emit · function · L111-L119 — def _emit(progress_callback, pct: float, msg: str = "") -> None
- process_video · function · L122-L367 — def process_video( input_path: str, output_path: str, config: Config, bbox: list[int] | None = None, bboxes: list[list[int]] | None = None, progress_callback=None, ) -> ProcessResult
- _inpaint_progress · function · L280-L283 — def _inpaint_progress(stage_pct: int, _msg: str = "") -> None: # 将逐帧修复阶段进度 (0-100) 映射到整体进度 25%-85%
- _qa_check · function · L370-L384 — def _qa_check(dst: Path, source_duration: float, mux_info: dict) -> None
