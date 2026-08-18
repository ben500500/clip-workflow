# autoclip/app/pipeline/step3_scoring.py · [[autoclip-pipeline-stages]]

- ClipScorer · class · L19-L288 — class ClipScorer
- __init__ · method · L27-L60 — def __init__(self, prompt_files: Dict = None, metadata_dir: Path = None, frame_analysis_enabled: Optional[bool] = None)
- score_clips · method · L62-L109 — def score_clips(self, timeline_data: List[Dict]) -> List[Dict]
- _get_llm_evaluation · method · L111-L197 — def _get_llm_evaluation(self, clips: List[Dict]) -> List[Dict]
- _extract_transcript · method · L199-L252 — def _extract_transcript(self, chunk_index, start_time, end_time) -> str
- _truncate_transcript · method · L254-L270 — def _truncate_transcript(self, transcript: str) -> str
- _infer_clip_type · method · L272-L282 — def _infer_clip_type(self, start_time, end_time) -> str
- save_scores · method · L284-L288 — def save_scores(self, scored_clips: List[Dict], output_path: Path)
- run_step3_scoring · function · L290-L334 — def run_step3_scoring(timeline_path: Path, metadata_dir: Path = None, output_path: Optional[Path] = None, prompt_files: Dict = None, frame_analysis_enabled: Optional[bool] = None) -> List[Dict]
