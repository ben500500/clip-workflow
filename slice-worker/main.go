package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"runtime"
	"syscall"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	// 命令行参数
	configPath := flag.String("config", "worker.json", "配置文件路径")
	noTUI := flag.Bool("no-tui", false, "禁用TUI界面（后台模式）")
	trayMode := flag.Bool("tray", false, "启用系统托盘/菜单栏模式（Windows/macOS 有效）")
	flag.Parse()

	// 加载配置
	config, err := LoadConfig(*configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "加载配置失败: %v\n", err)
		os.Exit(1)
	}

	// Windows 默认进入托盘模式（任务栏图标 + 节点启停），除非显式指定 --no-tui
	if runtime.GOOS == "windows" && !*trayMode && !*noTUI {
		*trayMode = true
	}

	// 创建临时目录
	os.MkdirAll(config.TempDir, 0755)

	// 连接Redis
	redis, err := NewRedisClient(config.RedisURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "连接Redis失败: %v\n", err)
		os.Exit(1)
	}
	defer redis.Close()

	// 创建Worker
	worker := NewWorker(config, redis)

	// 上下文（用于优雅退出）
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 信号处理
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		cancel()
	}()

	if *trayMode {
		// 托盘模式（Windows/macOS 任务栏/菜单栏状态图标 + 启停）
		runTray(ctx, config, worker)
	} else if *noTUI {
		// 后台模式：纯日志输出
		runDaemon(ctx, config, worker)
	} else {
		// TUI模式
		runTUI(ctx, config, worker)
	}
}

// runDaemon 后台模式运行
func runDaemon(ctx context.Context, config *Config, worker *Worker) {
	fmt.Println("╔══════════════════════════════════════════════════════════╗")
	fmt.Println("║          Slice Worker - 分布式切片执行节点              ║")
	fmt.Println("╚══════════════════════════════════════════════════════════╝")
	fmt.Println()
	fmt.Printf("  节点ID:    %s\n", config.NodeID)
	fmt.Printf("  Redis:     %s\n", config.RedisURL)
	fmt.Printf("  标签:      %v\n", config.Tags)
	fmt.Printf("  最大并发:  %d\n", config.MaxConcurrent)
	fmt.Printf("  CPU分配:  %d%%\n", config.CPUPercent)
	fmt.Println()
	fmt.Println("启动中...")

	// 设置日志回调
	worker.SetCallbacks(
		func(task *SliceTask) {
			fmt.Printf("[INFO] 任务开始: %s [%s]\n", task.TaskID[:8], task.Mode)
		},
		func(taskID string, phase string, percent float64, detail string) {
			fmt.Printf("[INFO] %s [%s] %.0f%% %s\n", taskID[:8], phase, percent, detail)
		},
		func(taskID string, outputs []string) {
			fmt.Printf("[OK] 任务完成: %s, %d 个文件\n", taskID[:8], len(outputs))
		},
		func(taskID string, err error) {
			fmt.Printf("[ERROR] 任务失败: %s - %v\n", taskID[:8], err)
		},
		func(level string, msg string) {
			fmt.Printf("[%s] %s\n", level, msg)
		},
	)

	// 运行
	if err := worker.Run(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "Worker运行错误: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Worker已退出")
}

// runTUI TUI模式运行
func runTUI(ctx context.Context, config *Config, worker *Worker) {
	// 创建TUI模型
	model := NewTUIModel(config, worker)

	// 设置Worker回调 → 发送到TUI
	// 注意：这里需要通过channel传递消息到TUI的Update方法
	// 简化处理：直接通过全局program发送消息
	var program *tea.Program

	worker.SetCallbacks(
		func(task *SliceTask) {
			if program != nil {
				program.Send(TaskStartMsg{
					TaskID:    task.TaskID,
					EpisodeID: task.EpisodeID,
					Mode:      task.Mode,
				})
			}
		},
		func(taskID string, phase string, percent float64, detail string) {
			if program != nil {
				program.Send(TaskProgressMsg{
					TaskID:  taskID,
					Phase:   phase,
					Percent: percent,
					Detail:  detail,
				})
			}
		},
		func(taskID string, outputs []string) {
			if program != nil {
				program.Send(TaskCompleteMsg{
					TaskID:      taskID,
					OutputCount: len(outputs),
				})
			}
		},
		func(taskID string, err error) {
			if program != nil {
				program.Send(TaskErrorMsg{
					TaskID: taskID,
					Error:  err.Error(),
				})
			}
		},
		func(level string, msg string) {
			if program != nil {
				program.Send(LogMsg{
					Level:   level,
					Message: msg,
				})
			}
		},
	)

	// 创建并运行程序
	program = tea.NewProgram(model, tea.WithAltScreen())

	// 异步启动Worker
	go func() {
		if err := worker.Run(ctx); err != nil {
			program.Send(LogMsg{
				Level:   "error",
				Message: fmt.Sprintf("Worker错误: %v", err),
			})
		}
	}()

	// 运行TUI
	if _, err := program.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "TUI运行错误: %v\n", err)
		os.Exit(1)
	}
}
