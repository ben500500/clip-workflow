# engines/seedance_wm/remover.py · [[seedance-wm-engine]]

- BatchResult · class · L28-L39 — class BatchResult
- success_count · method · L34-L35 — def success_count(self) -> int
- failed · method · L38-L39 — def failed(self) -> list[ProcessResult]
- Remover · class · L42-L143 — class Remover
- __init__ · method · L43-L44 — def __init__(self, config: Config | None = None)
- process · method · L47-L54 — def process( self, input_file: str, output_file: str, bbox: list[int] | None = None, bboxes: list[list[int]] | None = None, ) -> ProcessResult
- batch · method · L57-L128 — def batch( self, input_dir: str, output_dir: str, workers: int = 1, skip_existing: bool = False, retry_failed: int = 0, failed_log: str = "failed.log", extensions: list[str] | None = None, ) -> BatchResult
- _process_one · method · L130-L143 — def _process_one(self, src: Path, dst: Path, retry: int) -> ProcessResult
