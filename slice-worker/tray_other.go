//go:build !windows && !darwin

package main

// 非 Windows/macOS 平台（Linux、容器、服务器）的托盘兜底实现。
//
// 这些环境通常没有桌面托盘；为保持代码结构统一，这里返回一个
// “无操作”控制器，实际仍以原有后台/TUI 模式运行。

import "log"

// NoopTray 无操作托盘（Linux/服务器/容器环境）
type NoopTray struct {
	ui *TrayUI
}

func newPlatformTrayController() TrayController {
	return &NoopTray{}
}

func (t *NoopTray) Start(ui *TrayUI) {
	t.ui = ui
	log.Println("[tray] 当前平台不支持系统托盘，以后台模式运行（如需界面请使用 TUI 模式）")
}

func (t *NoopTray) Stop() {}

func (t *NoopTray) SetOnline(online bool) {}

func (t *NoopTray) Notify(title, msg string) {
	log.Printf("[tray] %s: %s", title, msg)
}
