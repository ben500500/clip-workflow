# slice-worker/task_executor.go

Task executor that invokes the Python slice.py engine to perform video slicing tasks, parsing progress and collecting output files.

- TaskExecutor · struct · L18-L21 — Holds the worker config and an optional progress callback for reporting ffmpeg slicing progress.
- NewTaskExecutor · function · L24-L28 — Constructs a TaskExecutor bound to the given worker config.
- SetProgressCallback · method · L31-L33 — Registers the callback invoked with ffmpeg progress updates during slicing.
- ExecuteTask · method · L40-L324 — Runs the slice.py engine on a task, building CLI args from all optional features (watermark, badges, subtitles, masks, encoder, dedupe), streaming progress, and returning generated output file paths.
- parseEngineLine · method · L327-L347 — Parses engine stdout lines, forwarding PROGRESS percentages to the callback and recording OUTPUT file durations into the manifest.
- collectOutputs · method · L350-L379 — Collects output file paths, preferring the engine manifest order and falling back to scanning the directory for mp4 files.
