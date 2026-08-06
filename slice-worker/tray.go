package main

// 系统托盘（菜单栏）实现。
//
// 平台适配：
//   - Windows：使用 github.com/getlantern/systray，图标显示在任务栏托盘区；
//     菜单提供：节点状态查看、开启/停用节点（写入 Redis 控制 key，与后端
//     /workers 页面共用同一开关）、退出。
//   - macOS：使用 github.com/getlantern/systray + Template 图标，图标显示在
//     菜单栏，并带“在线/离线”角标。菜单与 Windows 一致。
//   - Linux/服务器/容器：提供 no-tray 纯日志后台模式（原有 --no-tui），
//     不受影响。
//
// 平台无关的通用托盘逻辑在 tray_common.go；平台相关初始化在 tray_windows.go
// 与 tray_darwin.go，两者通过 build tag（windows/darwin）隔离，避免在
// Linux 等无 GUI 环境引入桌面依赖。

// TrayController 托盘控制接口：由各平台实现。
type TrayController interface {
	// Start 启动托盘（阻塞在事件循环前返回即可，需在内部自行处理
	// 就绪后的状态同步）。
	Start(ui *TrayUI)
	// Stop 退出托盘并释放资源。
	Stop()
	// SetOnline 更新节点在线状态图标（绿色=在线 / 灰色=离线）。
	SetOnline(online bool)
	// Notify 在托盘弹一条消息（可选实现，不支持则忽略）。
	Notify(title, msg string)
}

// TrayUI 托盘 UI 状态与回调（平台无关）。
type TrayUI struct {
	Controller TrayController

	// 当前节点状态（供菜单渲染与图标刷新）
	NodeID    string
	Online    bool
	Enabled   bool
	Running   int
	Completed int
	Failed    int
	// 当前 CPU 资源分配比例（%），默认 50
	CPUPercent int

	// 回调（由 tray_common 注入）
	OnToggle     func(enabled bool)
	OnCPUChange  func(delta int) // 在托盘菜单中调整 CPU 分配（+/-）
	OnQuit       func()

	// 内部：菜单状态刷新（由平台实现调用）
	updateMenu func()
}

// NewTrayUI 创建托盘 UI 状态对象（平台无关部分）。
func NewTrayUI(nodeID string) *TrayUI {
	return &TrayUI{
		NodeID:     nodeID,
		Online:     false,
		Enabled:    true,
		CPUPercent: 50,
	}
}

// SetStatus 更新节点状态并刷新图标与菜单。
func (u *TrayUI) SetStatus(online, enabled bool, running, completed, failed int) {
	changed := u.Online != online || u.Enabled != enabled ||
		u.Running != running || u.Completed != completed || u.Failed != failed
	u.Online = online
	u.Enabled = enabled
	u.Running = running
	u.Completed = completed
	u.Failed = failed
	if changed && u.Controller != nil {
		u.Controller.SetOnline(online && enabled)
	}
	if changed && u.updateMenu != nil {
		u.updateMenu()
	}
}

// SetCPUPercent 更新 CPU 分配比例并刷新菜单。
func (u *TrayUI) SetCPUPercent(pct int) {
	if pct < 1 {
		pct = 1
	}
	if pct > 100 {
		pct = 100
	}
	if u.CPUPercent != pct && u.updateMenu != nil {
		u.updateMenu()
	}
	u.CPUPercent = pct
}
