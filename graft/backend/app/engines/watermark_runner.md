# backend/app/engines/watermark_runner.py · [[engine-execution-layer]]

- _run_cmd · function · L33-L130 — async def _run_cmd( cmd: list[str], progress_cb: ProgressCallback = None, timeout: float = 2 * 3600, ) -> tuple[int, str, str]
- read_stream · function · L57-L74 — async def read_stream(stream, sink)
- progress_pulse · function · L76-L89 — async def progress_pulse()
- watchdog · function · L91-L109 — async def watchdog()
- _script_path · function · L133-L138 — def _script_path(name: str) -> str
- _load_roi_experience · function · L141-L158 — def _load_roi_experience(source_name: str)
- run_remove_ai_watermarks · function · L161-L216 — async def run_remove_ai_watermarks( source_path: str, output_path: str, options: Optional[dict] = None, progress_cb: ProgressCallback = None, timeout: float = 2 * 3600, ) -> tuple[int, str, str]
- run_seedance_watermark_remover · function · L219-L260 — async def run_seedance_watermark_remover( source_path: str, output_path: str, options: Optional[dict] = None, progress_cb: ProgressCallback = None, timeout: float = 2 * 3600, ) -> tuple[int, str, str]
- run_remove_mask · function · L263-L325 — async def run_remove_mask( source_path: str, output_path: str, options: Optional[dict] = None, progress_cb: ProgressCallback = None, timeout: float = 2 * 3600, ) -> tuple[int, str, str]
- run_seedance_wm · function · L328-L374 — async def run_seedance_wm( source_path: str, output_path: str, options: Optional[dict] = None, progress_cb: ProgressCallback = None, timeout: float = 2 * 3600, ) -> tuple[int, str, str]
- run_watermark_engine · function · L377-L402 — async def run_watermark_engine( engine: str, source_path: str, output_path: str, options: Optional[dict] = None, progress_cb: ProgressCallback = None, timeout: float = 2 * 3600, ) -> tuple[int, str, str]
- temp_video_path · function · L405-L407 — def temp_video_path(prefix: str = "wm") -> str
