# slice-worker/engine_update.go · [[engine-update-versioning]] [[slice-worker-node]]

- nodeUpdateCommand · struct · L33-L36 — nodeUpdateCommand
- ComputeEngineVersion · function · L41-L60 — func ComputeEngineVersion(enginesDir string) (string, error)
- listEngineFiles · function · L63-L89 — func listEngineFiles(enginesDir string) ([]string, error)
- PullEngineUpdate · function · L95-L130 — func PullEngineUpdate(backendURL, enginesDir string) (string, error)
- extractTarGz · function · L134-L198 — func extractTarGz(data []byte, destDir string) error
- readUpdateCommandJSON · function · L201-L210 — func readUpdateCommandJSON(raw string) (*nodeUpdateCommand, error)
