//go:build darwin && !cgo

package main

// macOS 无 cgo（CGO_ENABLED=0）构建时的托盘兜底实现。
//
// getlantern/systray 的 macOS 端依赖 Cocoa（cgo），无 cgo 时无法显示菜单栏
// 图标；此实现退化为日志模式，保证 `CGO_ENABLED=0 go build` 可编译通过。
// 实际使用 macOS 桌面菜单栏请使用默认 cgo 构建（见 build_mac.sh）。

import "log"

// NoCgoMacTray macOS 无 cgo 时的兜底托盘
type NoCgoMacTray struct {
	ui *TrayUI
}

func newPlatformTrayController() TrayController {
	return &NoCgoMacTray{}
}

func (t *NoCgoMacTray) Start(ui *TrayUI) {
	t.ui = ui
	log.Println("[tray] 当前构建未启用 cgo，无法显示 macOS 菜单栏图标，以后台模式运行")
}

func (t *NoCgoMacTray) Stop() {}

func (t *NoCgoMacTray) SetOnline(online bool) {}

func (t *NoCgoMacTray) Notify(title, msg string) {
	log.Printf("[tray] %s: %s", title, msg)
}
