# autoclip/app/pipeline/step2_timeline.py

- TimelineExtractor · class · L18-L421 — class TimelineExtractor
- __init__ · method · L21-L42 — def __init__(self, metadata_dir: Path = None, prompt_files: Dict = None, duration_config: Optional[Dict] = None)
- _apply_duration_config · method · L44-L110 — def _apply_duration_config(self)
- extract_timeline · method · L112-L291 — def extract_timeline(self, outlines: List[Dict]) -> List[Dict]
- _parse_and_validate_response · method · L293-L372 — def _parse_and_validate_response(self, response: str, chunk_start: str, chunk_end: str, chunk_index: int) -> List[Dict]
- _validate_time_format · method · L374-L379 — def _validate_time_format(self, time_str: str) -> bool
- _convert_time_format · method · L381-L387 — def _convert_time_format(self, time_str: str) -> str
- _save_debug_response · method · L389-L399 — def _save_debug_response(self, response: str, chunk_index: int, error_type: str) -> None
- save_timeline · method · L401-L414 — def save_timeline(self, timeline_data: List[Dict], output_path: Optional[Path] = None) -> Path
- load_timeline · method · L416-L421 — def load_timeline(self, input_path: Path) -> List[Dict]
- run_step2_timeline · function · L423-L444 — def run_step2_timeline(outline_path: Path, metadata_dir: Path = None, output_path: Optional[Path] = None, prompt_files: Dict = None, duration_config: Optional[Dict] = None) -> List[Dict]
