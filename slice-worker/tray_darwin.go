//go:build darwin && cgo

package main

import (
	"embed"
	"log"
	"runtime"
	"sync"

	"github.com/getlantern/systray"
)

// 内嵌 macOS 菜单栏图标（Template 图标：黑色透明底，随系统明暗自动适配）
//
//go:embed icons/icon_template.png
var macIcons embed.FS

// MacOSTray macOS 菜单栏托盘实现（cgo 构建：真实菜单栏图标 + 状态菜单）。
type MacOSTray struct {
	ui *TrayUI
	mu sync.Mutex

	mStatus *systray.MenuItem
	mToggle *systray.MenuItem
	mQuit   *systray.MenuItem
}

// newPlatformTrayController 平台工厂：返回 macOS 托盘实现
func newPlatformTrayController() TrayController {
	return &MacOSTray{}
}

func (t *MacOSTray) iconBytes() []byte {
	data, err := macIcons.ReadFile("icons/icon_template.png")
	if err != nil {
		log.Printf("[tray] 读取内嵌图标失败: %v", err)
		return nil
	}
	return data
}

// Start 启动托盘。systray.Run 阻塞于消息循环，放到 goroutine 中运行；
// 就绪后构建菜单。
func (t *MacOSTray) Start(ui *TrayUI) {
	t.ui = ui
	go func() {
		runtime.LockOSThread()
		systray.Run(func() {
			t.onReady()
		}, func() {
			log.Println("[tray] 托盘已退出")
		})
	}()
}

func (t *MacOSTray) onReady() {
	if data := t.iconBytes(); len(data) > 0 {
		// macOS 使用 Template 图标，随菜单栏明暗自动适配
		systray.SetTemplateIcon(data, data)
	}
	systray.SetTooltip("Slice Worker - " + t.ui.NodeID)

	t.mStatus = systray.AddMenuItem("状态: 启动中...", "当前节点状态")
	t.mStatus.Disable()

	t.mToggle = systray.AddMenuItem("停用节点", "停止领取新的切片任务")
	t.mQuit = systray.AddMenuItem("退出 Worker", "注销节点并退出")

	go func() {
		for {
			select {
			case <-t.mToggle.ClickedCh:
				if t.ui.Enabled {
					t.ui.OnToggle(false)
				} else {
					t.ui.OnToggle(true)
				}
			case <-t.mQuit.ClickedCh:
				if t.ui.OnQuit != nil {
					t.ui.OnQuit()
				}
				systray.Quit()
				return
			}
		}
	}()

	t.refresh()
}

func (t *MacOSTray) refresh() {
	if t.ui == nil || t.mStatus == nil {
		return
	}
	state := "离线"
	if t.ui.Online {
		state = "在线"
	}
	t.mStatus.SetTitle("状态: " + state)
	t.mStatus.SetTooltip(t.ui.NodeID)

	if t.ui.Enabled {
		t.mToggle.SetTitle("停用节点")
	} else {
		t.mToggle.SetTitle("启用节点")
	}
}

func (t *MacOSTray) SetOnline(online bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.refresh()
}

func (t *MacOSTray) Notify(title, msg string) {
	log.Printf("[tray] %s: %s", title, msg)
}

func (t *MacOSTray) Stop() {
	systray.Quit()
}
