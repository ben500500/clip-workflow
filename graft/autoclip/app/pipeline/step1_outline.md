# autoclip/app/pipeline/step1_outline.py · [[autoclip-pipeline-stages]]

- OutlineExtractor · class · L17-L210 — class OutlineExtractor
- __init__ · method · L20-L42 — def __init__(self, metadata_dir: Path = None, prompt_files: Dict = None)
- extract_outline · method · L44-L111 — def extract_outline(self, srt_path: Path) -> List[Dict]
- _save_chunks_to_files · method · L113-L126 — def _save_chunks_to_files(self, chunks: List[Dict]) -> List[Path]
- _save_srt_chunks · method · L128-L138 — def _save_srt_chunks(self, chunks: List[Dict])
- _parse_outline_response · method · L140-L177 — def _parse_outline_response(self, response: str, chunk_index: int) -> List[Dict]
- _merge_outlines · method · L179-L188 — def _merge_outlines(self, outlines: List[Dict]) -> List[Dict]
- save_outline · method · L190-L203 — def save_outline(self, outlines: List[Dict], output_path: Optional[Path] = None) -> Path
- load_outline · method · L205-L210 — def load_outline(self, input_path: Path) -> List[Dict]
- run_step1_outline · function · L212-L227 — def run_step1_outline(srt_path: Path, metadata_dir: Path = None, output_path: Optional[Path] = None, prompt_files: Dict = None) -> List[Dict]
