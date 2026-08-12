//go:build darwin && cgo

package main

import (
	"embed"
	"fmt"
	"log"
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

	mStatus   *systray.MenuItem
	mCPU      *systray.MenuItem
	mCPUItems map[int]*systray.MenuItem
	mToggle   *systray.MenuItem
	mQuit     *systray.MenuItem
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

// Start 启动托盘。systray.Run 阻塞于消息循环，就绪后构建菜单。
//
// 注意：macOS 上 [NSApp run]（AppKit 主事件循环）必须在主线程执行，
// 放进 goroutine 即使 LockOSThread 也会 SIGTRAP 崩溃（systray 库硬性要求）。
// 因此这里直接在主 goroutine 阻塞运行；worker 主循环已在 runTray 的
// goroutine 中启动，不受影响。
func (t *MacOSTray) Start(ui *TrayUI) {
	t.ui = ui
	systray.Run(func() {
		t.onReady()
	}, func() {
		log.Println("[tray] 托盘已退出")
	})
}

func (t *MacOSTray) onReady() {
	if data := t.iconBytes(); len(data) > 0 {
		// macOS 使用 Template 图标，随菜单栏明暗自动适配
		systray.SetTemplateIcon(data, data)
	}
	systray.SetTooltip("Slice Worker - " + t.ui.NodeID)

	t.mStatus = systray.AddMenuItem("状态: 启动中...", "当前节点状态")
	t.mStatus.Disable()

	// CPU 分配：点击展开子菜单，直接选择预设值（当前值打勾标记）
	t.mCPU = systray.AddMenuItem("CPU 分配: 50% ▸", "点击选择 CPU 资源分配比例")
	t.mCPUItems = make(map[int]*systray.MenuItem)
	for _, pct := range []int{10, 20, 30, 40, 50, 60, 70, 80, 90, 100} {
		item := t.mCPU.AddSubMenuItem(fmt.Sprintf("%d%%", pct), fmt.Sprintf("设置 CPU 分配为 %d%%", pct))
		t.mCPUItems[pct] = item
	}

	t.mToggle = systray.AddMenuItem("停用节点", "停止领取新的切片任务")
	t.mQuit = systray.AddMenuItem("退出 Worker", "注销节点并退出")

	go func() {
		for {
			select {
			case <-t.mCPU.ClickedCh:
				// 点击主项仅展开子菜单，无需处理
			case <-t.mCPUItems[10].ClickedCh:
				t.setCPU(10)
			case <-t.mCPUItems[20].ClickedCh:
				t.setCPU(20)
			case <-t.mCPUItems[30].ClickedCh:
				t.setCPU(30)
			case <-t.mCPUItems[40].ClickedCh:
				t.setCPU(40)
			case <-t.mCPUItems[50].ClickedCh:
				t.setCPU(50)
			case <-t.mCPUItems[60].ClickedCh:
				t.setCPU(60)
			case <-t.mCPUItems[70].ClickedCh:
				t.setCPU(70)
			case <-t.mCPUItems[80].ClickedCh:
				t.setCPU(80)
			case <-t.mCPUItems[90].ClickedCh:
				t.setCPU(90)
			case <-t.mCPUItems[100].ClickedCh:
				t.setCPU(100)
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

// setCPU 把 CPU 分配调整到目标百分比（通过 delta 回调驱动后端）。
func (t *MacOSTray) setCPU(target int) {
	if t.ui.OnCPUChange != nil {
		t.ui.OnCPUChange(target - t.ui.CPUPercent)
	}
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

	if t.mCPU != nil {
		t.mCPU.SetTitle(fmt.Sprintf("CPU 分配: %d%% ▸", t.ui.CPUPercent))
		// 子菜单当前值打勾标记（其他项取消勾选）
		for pct, item := range t.mCPUItems {
			if pct == t.ui.CPUPercent {
				item.Check()
			} else {
				item.Uncheck()
			}
		}
	}

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
