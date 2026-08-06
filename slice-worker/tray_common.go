package main

// 系统托盘通用逻辑：菜单项组装、节点启停、状态轮询、退出。
//
// 该文件不引用任何平台相关 API，仅通过 TrayController 接口与
// 平台实现（tray_windows.go / tray_darwin.go）交互。

import (
	"context"
	"fmt"
	"log"
	"os"
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

// trayStopper 记录已启动的托盘控制器，便于信号处理时统一退出
var (
	trayMu     sync.Mutex
	trayActive []TrayController
)

func registerTray(c TrayController) {
	trayMu.Lock()
	defer trayMu.Unlock()
	trayActive = append(trayActive, c)
}

// StopAllTrays 退出所有已启动的托盘（供 main 退出路径调用）
func StopAllTrays() {
	trayMu.Lock()
	defer trayMu.Unlock()
	for _, c := range trayActive {
		c.Stop()
	}
	trayActive = nil
}

// runTray 启动托盘模式（Windows / macOS 使用）。
//
// 与 runTUI / runDaemon 并列：新增 --tray 参数后，在支持系统托盘的
// 平台优先启动托盘；后台仍保持 Worker 核心逻辑不变。
//
// 注意：systray 的 GUI 消息循环建议在 main goroutine 上运行
// （Windows 消息泵 / macOS 主线程），因此这里把 Worker 主循环放到
// goroutine，托盘 Start 阻塞到退出。
func runTray(ctx context.Context, config *Config, worker *Worker) {
	fmt.Println("╔══════════════════════════════════════════════════════════╗")
	fmt.Println("║  Slice Worker - 托盘模式（状态栏图标 + 节点启停）        ║")
	fmt.Println("╚══════════════════════════════════════════════════════════╝")
	fmt.Println()
	fmt.Printf("  节点ID:    %s\n", config.NodeID)
	fmt.Printf("  Redis:     %s\n", config.RedisURL)
	fmt.Printf("  平台:      %s/%s\n", runtime.GOOS, runtime.GOARCH)
	fmt.Println()
	fmt.Println("启动中... 托盘图标就绪后，可从系统托盘/菜单栏查看状态并启停节点")

	// 托盘 UI（平台无关）
	ui := NewTrayUI(config.NodeID)
	ui.CPUPercent = config.CPUPercent

	// 控制器由平台初始化
	controller := NewTrayController()
	ui.Controller = controller
	registerTray(controller)

	// 菜单/退出回调
	ui.OnToggle = func(enabled bool) {
		if enabled {
			if err := worker.redis.SetNodeEnabled(config.NodeID, true); err != nil {
				log.Printf("[tray] 启用节点失败: %v", err)
			} else {
				ui.SetStatus(ui.Online, true, worker.GetCurrentTaskCount(),
					int(atomic.LoadInt32(&worker.totalCompleted)),
					int(atomic.LoadInt32(&worker.totalFailed)))
			}
		} else {
			if err := worker.redis.SetNodeEnabled(config.NodeID, false); err != nil {
				log.Printf("[tray] 停用节点失败: %v", err)
			} else {
				ui.SetStatus(ui.Online, false, worker.GetCurrentTaskCount(),
					int(atomic.LoadInt32(&worker.totalCompleted)),
					int(atomic.LoadInt32(&worker.totalFailed)))
			}
		}
	}
	// 托盘菜单中调整 CPU 分配（+/-），写入 Redis 控制 key，Worker 下次取任务前生效
	ui.OnCPUChange = func(delta int) {
		current, err := worker.redis.GetNodeCPUPercent(config.NodeID, config.CPUPercent)
		if err != nil {
			current = config.CPUPercent
		}
		next := ClampCPUPercent(current + delta)
		if err := worker.redis.SetNodeCPUPercent(config.NodeID, next); err != nil {
			log.Printf("[tray] 调整 CPU 分配失败: %v", err)
			return
		}
		config.CPUPercent = next
		ui.SetCPUPercent(next)
		log.Printf("[tray] CPU 分配已调整为 %d%%", next)
	}
	ui.OnQuit = func() {
		// 退出前注销节点
		_ = worker.redis.UnregisterNode(config.NodeID, config.Tags)
		fmt.Println("Worker 已通过托盘退出")
		os.Exit(0)
	}

	// 后台运行 Worker 主循环（与 daemon 模式共用逻辑）
	worker.SetCallbacks(
		func(task *SliceTask) {
			ui.SetStatus(ui.Online, ui.Enabled, worker.GetCurrentTaskCount(),
				int(atomic.LoadInt32(&worker.totalCompleted)),
				int(atomic.LoadInt32(&worker.totalFailed)))
		},
		func(taskID string, phase string, percent float64, detail string) {
			// 进度变化仅刷新图标角标状态
			ui.SetStatus(ui.Online, ui.Enabled, worker.GetCurrentTaskCount(),
				int(atomic.LoadInt32(&worker.totalCompleted)),
				int(atomic.LoadInt32(&worker.totalFailed)))
		},
		func(taskID string, outputs []string) {
			ui.SetStatus(ui.Online, ui.Enabled, worker.GetCurrentTaskCount(),
				int(atomic.LoadInt32(&worker.totalCompleted)),
				int(atomic.LoadInt32(&worker.totalFailed)))
		},
		func(taskID string, err error) {
			ui.SetStatus(ui.Online, ui.Enabled, worker.GetCurrentTaskCount(),
				int(atomic.LoadInt32(&worker.totalCompleted)),
				int(atomic.LoadInt32(&worker.totalFailed)))
		},
		func(level string, msg string) {
			if level == "error" {
				log.Printf("[%s] %s", level, msg)
			}
		},
	)

	workerDone := make(chan error, 1)
	go func() {
		workerDone <- worker.Run(ctx)
	}()

	// 启动状态轮询：感知节点启用/停用状态与在线状态（心跳由 Worker 内部完成）
	stopPoll := make(chan struct{})
	go func() {
		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-stopPoll:
				return
			case <-ctx.Done():
				return
			case <-ticker.C:
				enabled, err := worker.redis.IsNodeEnabled(config.NodeID)
				if err != nil {
					continue
				}
				ui.SetStatus(true, enabled, worker.GetCurrentTaskCount(),
					int(atomic.LoadInt32(&worker.totalCompleted)),
					int(atomic.LoadInt32(&worker.totalFailed)))
			}
		}
	}()

	// 阻塞在托盘消息循环（平台实现内部运行 systray.Run）
	controller.Start(ui)

	close(stopPoll)

	// 托盘退出后，等待 Worker 退出
	select {
	case err := <-workerDone:
		if err != nil {
			fmt.Fprintf(os.Stderr, "Worker运行错误: %v\n", err)
		}
	case <-ctx.Done():
	}

	fmt.Println("Worker已退出")
	StopAllTrays()
}

// NewTrayController 由平台文件实现
func NewTrayController() TrayController {
	return newPlatformTrayController()
}
