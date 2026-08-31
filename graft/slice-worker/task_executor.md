# slice-worker/task_executor.go · [[slice-worker-node]]

Task executor that orchestrates the Python slicing engine, building CLI args from task config, running the engine, parsing progress/output, and collecting generated files.

- TaskExecutor · struct · L19-L22 — Holds the worker config and an optional progress callback for reporting ffmpeg slicing progress.
- NewTaskExecutor · function · L25-L29 — Constructs a TaskExecutor bound to the given worker config.
- SetProgressCallback · method · L32-L34 — Registers the callback invoked with ffmpeg progress updates during slicing.
- ExecuteTask · method · L41-L391 — Runs the slice.py engine for a slicing task: writes cutlist/intervals/subtitle files, assembles all optional feature flags (watermark, encoder, dedupe, badges, masks) into CLI args, executes the engine with process-group kill on timeout, parses PROGRESS/OUTPUT lines, and returns collected output file paths.
- parseEngineLine · method · L395-L417 — Parses engine stdout lines, forwarding PROGRESS percentages to the callback and recording OUTPUT file durations into the manifest.
- collectOutputs · method · L420-L449 — Collects output file paths, preferring the engine manifest order and falling back to scanning the directory for mp4 files.
- cutSegment · struct · L453-L457 — cutSegment
- parseCutlist · function · L461-L483 — func parseCutlist(content string) []cutSegment
- parseCutTime · function · L486-L521 — func parseCutTime(s string) (float64, error)
- outputName · method · L524-L530 — func (c cutSegment) outputName() string
- filterCompletedSegments · method · L539-L553 — func (te *TaskExecutor) filterCompletedSegments(outputDir string, segs []cutSegment) ([]cutSegment, []string)
- preservedOutputs · method · L556-L571 — func (te *TaskExecutor) preservedOutputs(outputDir string, segs []cutSegment) []string
- outputFileValid · method · L576-L586 — func (te *TaskExecutor) outputFileValid(path string) bool
- ffprobeDurationSec · function · L589-L602 — func ffprobeDurationSec(path string) (float64, error)
- readCompletedCheckpoint · method · L608-L621 — func (te *TaskExecutor) readCompletedCheckpoint(outputDir string) map[string]bool
- appendCompletedCheckpoint · method · L624-L651 — func (te *TaskExecutor) appendCompletedCheckpoint(outputDir string, names []string)
- cutlistForSegments · function · L655-L661 — func cutlistForSegments(segs []cutSegment) string
- formatSec · function · L664-L674 — func formatSec(sec float64) string
- mergeOutputPaths · function · L677-L688 — func mergeOutputPaths(a, b []string) []string
