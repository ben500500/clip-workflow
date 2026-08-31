# backend/app/services/slice_service.py · [[slice-engine-orchestration]]

- _run_cmd · function · L15-L65 — Runs an engine subprocess with a timeout, concurrently draining stdout/stderr while parsing PROGRESS lines, and escalates from SIGTERM to SIGKILL on timeout.
- read_stream · function · L34-L47 — Reads a subprocess stream line-by-line, accumulating output and forwarding clamped PROGRESS percentage updates to the progress callback.
- _terminate_proc · function · L73-L92 — async def _terminate_proc(proc) -> None
- kill_slice_proc · function · L95-L109 — async def kill_slice_proc(task_id: str) -> bool
- _engine_path · function · L112-L113 — Resolves an engine script's absolute path under the configured engines directory.
- _require_engine · function · L116-L121 — Guards against a missing engine binary by raising FileNotFoundError with a Chinese hint about mounting the engines directory.
- run_slice · function · L124-L233 — Builds the full ffmpeg slice engine CLI command from all optional configs (watermark, badges, subtitles, masks, dedupe, cover) and executes it, returning the engine's exit code and output.
- run_slice_scrub · function · L236-L301 — Delegates to run_slice in scrub mode, slicing the cutlist minus removed intervals by passing the intervals path.
- run_slice_fast · function · L304-L371 — Validates the mode is fast or dedupe, then delegates to run_slice without intervals for fast/dedupe slicing.
