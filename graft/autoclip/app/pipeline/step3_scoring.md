# autoclip/app/pipeline/step3_scoring.py · [[autoclip-pipeline]]

- ClipScorer · class · L19-L372 — class ClipScorer
- __init__ · method · L27-L76 — def __init__(self, prompt_files: Dict = None, metadata_dir: Path = None, frame_analysis_enabled: Optional[bool] = None, frame_analysis_provider: Optional[str] = None, frame_analysis_model: Optional[str] = None, frame_vision_base: Optional[str] = None, frame_vision_key: Optional[str] = None, highlight_mode: bool = False, highlight_max_duration: float = 10.0)
- score_clips · method · L78-L125 — def score_clips(self, timeline_data: List[Dict]) -> List[Dict]
- _get_llm_evaluation · method · L127-L281 — def _get_llm_evaluation(self, clips: List[Dict]) -> List[Dict]
- _extract_transcript · method · L283-L336 — def _extract_transcript(self, chunk_index, start_time, end_time) -> str
- _truncate_transcript · method · L338-L354 — def _truncate_transcript(self, transcript: str) -> str
- _infer_clip_type · method · L356-L366 — def _infer_clip_type(self, start_time, end_time) -> str
- save_scores · method · L368-L372 — def save_scores(self, scored_clips: List[Dict], output_path: Path)
- run_step3_scoring · function · L374-L431 — def run_step3_scoring(timeline_path: Path, metadata_dir: Path = None, output_path: Optional[Path] = None, prompt_files: Dict = None, frame_analysis_enabled: Optional[bool] = None, frame_analysis_provider: Optional[str] = None, frame_analysis_model: Optional[str] = None, frame_vision_base: Optional[str] = None, frame_vision_key: Optional[str] = None, highlight_mode: bool = False, highlight_max_duration: float = 10.0) -> List[Dict]
