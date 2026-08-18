# autoclip/app/pipeline/step4_title.py · [[autoclip-pipeline-stages]]

- TitleGenerator · class · L18-L115 — class TitleGenerator
- __init__ · method · L21-L34 — def __init__(self, metadata_dir: Optional[Path] = None, prompt_files: Dict = None)
- generate_titles · method · L36-L109 — def generate_titles(self, high_score_clips: List[Dict]) -> List[Dict]
- save_clips_with_titles · method · L111-L115 — def save_clips_with_titles(self, clips_with_titles: List[Dict], output_path: Path)
- run_step4_title · function · L117-L159 — def run_step4_title(high_score_clips_path: Path, output_path: Optional[Path] = None, metadata_dir: Optional[str] = None, prompt_files: Dict = None) -> List[Dict]
