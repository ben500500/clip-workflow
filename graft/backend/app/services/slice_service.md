# backend/app/services/slice_service.py · [[slice-engine-orchestration]]

- _run_cmd · function · L14-L63 — Runs an engine subprocess with a timeout, concurrently draining stdout/stderr while parsing PROGRESS lines, and escalates from SIGTERM to SIGKILL on timeout.
- read_stream · function · L28-L41 — Reads a subprocess stream line-by-line, accumulating output and forwarding clamped PROGRESS percentage updates to the progress callback.
- _engine_path · function · L66-L67 — Resolves an engine script's absolute path under the configured engines directory.
- _require_engine · function · L70-L75 — Guards against a missing engine binary by raising FileNotFoundError with a Chinese hint about mounting the engines directory.
- run_slice · function · L78-L165 — Builds the full ffmpeg slice engine CLI command from all optional configs (watermark, badges, subtitles, masks, dedupe, cover) and executes it, returning the engine's exit code and output.
- run_slice_scrub · function · L168-L221 — Delegates to run_slice in scrub mode, slicing the cutlist minus removed intervals by passing the intervals path.
- run_slice_fast · function · L224-L279 — Validates the mode is fast or dedupe, then delegates to run_slice without intervals for fast/dedupe slicing.
