# slice-worker/tray.go · [[redis-task-coordination-contract]] [[worker-platform-abstractions]]

- TrayController · interface · L19-L29 — TrayController
- TrayUI · struct · L32-L52 — TrayUI
- NewTrayUI · function · L55-L62 — func NewTrayUI(nodeID string) *TrayUI
- SetStatus · method · L65-L79 — func (u *TrayUI) SetStatus(online, enabled bool, running, completed, failed int)
- SetCPUPercent · method · L82-L93 — func (u *TrayUI) SetCPUPercent(pct int)
