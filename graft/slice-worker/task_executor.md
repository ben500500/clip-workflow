# slice-worker/task_executor.go

- TaskExecutor · struct · L18-L21 — TaskExecutor
- NewTaskExecutor · function · L24-L28 — func NewTaskExecutor(config *Config) *TaskExecutor
- SetProgressCallback · method · L31-L33 — func (te *TaskExecutor) SetProgressCallback(cb func(taskID string, percent float64, speed string, eta string))
- ExecuteTask · method · L40-L324 — func (te *TaskExecutor) ExecuteTask(ctx context.Context, task *SliceTask, sourcePath string, outputDir string) ([]string, error)
- parseEngineLine · method · L327-L347 — func (te *TaskExecutor) parseEngineLine(taskID, line string, manifest map[string]float64)
- collectOutputs · method · L350-L379 — func (te *TaskExecutor) collectOutputs(outputDir string, manifest map[string]float64) []string
