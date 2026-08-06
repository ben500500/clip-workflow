//go:build windows

package main

import (
	"embed"
	"fmt"
	"log"
	"runtime"
	"sync"

	"github.com/getlantern/systray"
)

// 内嵌 Windows 图标（ICO，包含 16/32/48/256 多尺寸）
//
//go:embed icons/icon.ico
var winIcons embed.FS

// WindowsTray Windows 任务栏托盘实现。
//
// 说明：systray 的 Run 必须在主 goroutine 调用（Windows 上依赖消息循环），
// 因此 Start 中直接调用 systray.Run 并阻塞直到 OnExit；Worker 主循环由
// tray_common 在 goroutine 中启动（runTray 中 worker.Run 在控制器 Start
// 之后调用，此时 Start 会先返回——见下方实现）。
type WindowsTray struct {
	ui *TrayUI
	mu sync.Mutex
	// 菜单项
	mStatus   *systray.MenuItem
	mCPU      *systray.MenuItem
	mCPUDown  *systray.MenuItem
	mCPUUp    *systray.MenuItem
	mToggle   *systray.MenuItem
	mQuit     *systray.MenuItem
}

// newPlatformTrayController 平台工厂：返回 Windows 托盘实现
func newPlatformTrayController() TrayController {
	return &WindowsTray{}
}

func (t *WindowsTray) iconBytes() []byte {
	data, err := winIcons.ReadFile("icons/icon.ico")
	if err != nil {
		log.Printf("[tray] 读取内嵌图标失败: %v", err)
		return nil
	}
	return data
}

// Start 启动托盘。由于 systray.Run 在主 goroutine 上必须阻塞（消息循环），
// 这里改为启动 goroutine 运行 systray；就绪后由 OnReady 回调构建菜单。
func (t *WindowsTray) Start(ui *TrayUI) {
	t.ui = ui
	go func() {
		// systray 内部依赖固定 OS 线程（init 中 LockOSThread），
		// 这里再显式锁定一次，保证消息循环与窗口创建在同一线程。
		runtime.LockOSThread()
		systray.Run(func() {
			t.onReady()
		}, func() {
			// OnExit
			log.Println("[tray] 托盘已退出")
		})
	}()
}

func (t *WindowsTray) onReady() {
	// 图标：优先内嵌 ICO
	if data := t.iconBytes(); len(data) > 0 {
		systray.SetIcon(data)
	} else {
		systray.SetTitle("Slice Worker")
	}
	systray.SetTooltip("Slice Worker - " + t.ui.NodeID)

	// 菜单
	t.mStatus = systray.AddMenuItem("状态: 启动中...", "当前节点状态")
	t.mStatus.Disable()

	t.mCPU = systray.AddMenuItem("CPU 分配: 50%", "当前 CPU 资源分配比例")
	t.mCPU.Disable()
	t.mCPUDown = systray.AddMenuItem("CPU -10%", "降低 CPU 分配比例（最小 1%）")
	t.mCPUUp = systray.AddMenuItem("CPU +10%", "提高 CPU 分配比例（最大 100%）")

	t.mToggle = systray.AddMenuItem("停用节点", "停止领取新的切片任务（正在执行的不受影响）")
	t.mQuit = systray.AddMenuItem("退出 Worker", "注销节点并退出程序")

	go func() {
		for {
			select {
			case <-t.mCPUDown.ClickedCh:
				if t.ui.OnCPUChange != nil {
					t.ui.OnCPUChange(-10)
				}
			case <-t.mCPUUp.ClickedCh:
				if t.ui.OnCPUChange != nil {
					t.ui.OnCPUChange(10)
				}
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

	// 菜单初始状态
	t.refresh()
}

// refresh 刷新菜单文字与图标状态
func (t *WindowsTray) refresh() {
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
		t.mCPU.SetTitle(fmt.Sprintf("CPU 分配: %d%%", t.ui.CPUPercent))
	}

	if t.ui.Enabled {
		t.mToggle.SetTitle("停用节点")
		t.mToggle.SetTooltip("停止领取新的切片任务（正在执行的不受影响）")
	} else {
		t.mToggle.SetTitle("启用节点")
		t.mToggle.SetTooltip("恢复领取切片任务")
	}
}

func (t *WindowsTray) SetOnline(online bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	// 图标颜色在 systray 中不易按状态动态切换，用 tooltip 与菜单展示状态
	t.refresh()
}

func (t *WindowsTray) Notify(title, msg string) {
	// systray 不提供原生气泡；在状态菜单中体现
	log.Printf("[tray] %s: %s", title, msg)
}

func (t *WindowsTray) Stop() {
	// 由 systray.Run 的退出流程清理；这里仅作兜底
	systray.Quit()
}
