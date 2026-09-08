# slice-worker/task_executor.go · [[slice-worker-node]]

Task executor that orchestrates the Python slicing engine, building CLI args from task config, running the engine, parsing progress/output, and collecting generated files.

- TaskExecutor · struct · L19-L22 — Holds the worker config and an optional progress callback for reporting ffmpeg slicing progress.
- NewTaskExecutor · function · L25-L29 — Constructs a TaskExecutor bound to the given worker config.
- SetProgressCallback · method · L32-L34 — Registers the callback invoked with ffmpeg progress updates during slicing.
- ExecuteTask · method · L41-L396 — Runs the slice.py engine for a slicing task: writes cutlist/intervals/subtitle files, assembles all optional feature flags (watermark, encoder, dedupe, badges, masks) into CLI args, executes the engine with process-group kill on timeout, parses PROGRESS/OUTPUT lines, and returns collected output file paths.
- parseEngineLine · method · L400-L422 — Parses engine stdout lines, forwarding PROGRESS percentages to the callback and recording OUTPUT file durations into the manifest.
- collectOutputs · method · L425-L454 — Collects output file paths, preferring the engine manifest order and falling back to scanning the directory for mp4 files.
- cutSegment · struct · L458-L462 — cutSegment
- parseCutlist · function · L466-L488 — func parseCutlist(content string) []cutSegment
- parseCutTime · function · L491-L526 — func parseCutTime(s string) (float64, error)
- outputName · method · L529-L535 — func (c cutSegment) outputName() string
- filterCompletedSegments · method · L544-L558 — func (te *TaskExecutor) filterCompletedSegments(outputDir string, segs []cutSegment) ([]cutSegment, []string)
- preservedOutputs · method · L561-L576 — func (te *TaskExecutor) preservedOutputs(outputDir string, segs []cutSegment) []string
- outputFileValid · method · L581-L591 — func (te *TaskExecutor) outputFileValid(path string) bool
- ffprobeDurationSec · function · L594-L607 — func ffprobeDurationSec(path string) (float64, error)
- readCompletedCheckpoint · method · L613-L626 — func (te *TaskExecutor) readCompletedCheckpoint(outputDir string) map[string]bool
- appendCompletedCheckpoint · method · L629-L656 — func (te *TaskExecutor) appendCompletedCheckpoint(outputDir string, names []string)
- cutlistForSegments · function · L660-L666 — func cutlistForSegments(segs []cutSegment) string
- formatSec · function · L669-L679 — func formatSec(sec float64) string
- mergeOutputPaths · function · L682-L693 — func mergeOutputPaths(a, b []string) []string
