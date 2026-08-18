# slice-worker/task_executor.go · [[slice-worker-node]]

Task executor that orchestrates the Python slicing engine, building CLI args from task config, running the engine, parsing progress/output, and collecting generated files.

- TaskExecutor · struct · L18-L21 — Holds the worker config and an optional progress callback for reporting ffmpeg slicing progress.
- NewTaskExecutor · function · L24-L28 — Constructs a TaskExecutor bound to the given worker config.
- SetProgressCallback · method · L31-L33 — Registers the callback invoked with ffmpeg progress updates during slicing.
- ExecuteTask · method · L40-L329 — Runs the slice.py engine for a slicing task: writes cutlist/intervals/subtitle files, assembles all optional feature flags (watermark, encoder, dedupe, badges, masks) into CLI args, executes the engine with process-group kill on timeout, parses PROGRESS/OUTPUT lines, and returns collected output file paths.
- parseEngineLine · method · L332-L352 — Parses engine stdout lines, forwarding PROGRESS percentages to the callback and recording OUTPUT file durations into the manifest.
- collectOutputs · method · L355-L384 — Collects output file paths, preferring the engine manifest order and falling back to scanning the directory for mp4 files.
