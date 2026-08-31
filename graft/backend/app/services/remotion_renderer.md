# backend/app/services/remotion_renderer.py

- parse_mix_segments · function · L32-L48 — def parse_mix_segments(cutlist: str) -> list[dict]
- _parse_ts · function · L51-L65 — def _parse_ts(raw: str) -> Optional[float]
- _parse_progress_stdout · function · L68-L76 — def _parse_progress_stdout(stdout: str) -> None
- _build_props · function · L79-L127 — def _build_props(segments: list[dict], config: dict, source_path: str) -> dict
- render_highlight_mix · function · L130-L195 — async def render_highlight_mix( slice_task, config: dict, source_file_key: Optional[str] = None, source_bucket: Optional[str] = None, progress_cb: ProgressCallback = None, ) -> tuple[bool, str]
- _run_render_media · function · L198-L239 — async def _run_render_media(props: dict, config: dict) -> tuple[bool, str, str]
