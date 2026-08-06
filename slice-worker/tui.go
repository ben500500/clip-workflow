package main

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// ========== 样式定义 ==========

var (
	// 颜色
	colorPrimary   = lipgloss.Color("#7C3AED") // 紫色
	colorSuccess   = lipgloss.Color("#10B981") // 绿色
	colorWarning   = lipgloss.Color("#F59E0B") // 黄色
	colorError     = lipgloss.Color("#EF4444") // 红色
	colorInfo      = lipgloss.Color("#3B82F6") // 蓝色
	colorMuted     = lipgloss.Color("#6B7280") // 灰色
	colorBorder    = lipgloss.Color("#374151") // 边框

	// 样式
	titleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("#FFFFFF")).
			Background(colorPrimary).
			Padding(0, 1)

	statusBarStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#E5E7EB")).
			Background(lipgloss.Color("#1F2937")).
			Padding(0, 1)

	panelStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(colorBorder).
			Padding(0, 1)

	taskActiveStyle = lipgloss.NewStyle().
			Foreground(colorInfo).
			Bold(true)

	taskCompleteStyle = lipgloss.NewStyle().
			Foreground(colorSuccess)

	taskErrorStyle = lipgloss.NewStyle().
			Foreground(colorError)

	progressBarStyle = lipgloss.NewStyle().
			Foreground(colorPrimary)

	logTimeStyle = lipgloss.NewStyle().
		Foreground(colorMuted)

	logInfoStyle = lipgloss.NewStyle().
		Foreground(colorInfo)

	logSuccessStyle = lipgloss.NewStyle().
			Foreground(colorSuccess)

	logWarnStyle = lipgloss.NewStyle().
		Foreground(colorWarning)

	logErrorStyle = lipgloss.NewStyle().
		Foreground(colorError)
)

// ========== 数据模型 ==========

// TaskStatus 任务状态
type TaskStatus struct {
	TaskID    string
	EpisodeID string
	Mode      string
	Phase     string    // download/ffmpeg/upload
	Percent   float64
	Speed     string
	Detail    string
	StartTime time.Time
	Status    string // running/completed/failed
	Outputs   int
}

// LogEntry 日志条目
type LogEntry struct {
	Time    time.Time
	Level   string
	Message string
}

// TUIModel TUI数据模型
type TUIModel struct {
	config     *Config
	worker     *Worker
	width      int
	height     int

	// 状态
	nodeStatus string
	tasks      map[string]*TaskStatus
	taskOrder  []string // 保持顺序
	logs       []LogEntry
	maxLogs    int

	// 统计
	totalCompleted int
	totalFailed    int
	totalFiles     int
	startTime      time.Time

	// 退出
	quitting bool
	err      error
}

// NewTUIModel 创建TUI模型
func NewTUIModel(config *Config, worker *Worker) *TUIModel {
	return &TUIModel{
		config:     config,
		worker:     worker,
		tasks:      make(map[string]*TaskStatus),
		maxLogs:    100,
		startTime:  time.Now(),
		nodeStatus: "connecting...",
	}
}

// ========== BubbleTea 接口实现 ==========

// Init 初始化
func (m TUIModel) Init() tea.Cmd {
	return tea.Batch(
		m.tickCmd(),
		m.resizeCmd(),
	)
}

// Update 更新
func (m TUIModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q":
			m.quitting = true
			return m, tea.Quit
		}

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case TickMsg:
		return m, m.tickCmd()

	case TaskStartMsg:
		m.tasks[msg.TaskID] = &TaskStatus{
			TaskID:    msg.TaskID,
			EpisodeID: msg.EpisodeID,
			Mode:      msg.Mode,
			Phase:     "init",
			Status:    "running",
			StartTime: time.Now(),
		}
		m.taskOrder = append(m.taskOrder, msg.TaskID)
		m.addLog("info", "任务开始: %s [%s]", msg.TaskID[:8], msg.Mode)
		return m, nil

	case TaskProgressMsg:
		if task, ok := m.tasks[msg.TaskID]; ok {
			task.Phase = msg.Phase
			task.Percent = msg.Percent
			task.Detail = msg.Detail
			if msg.Phase == "ffmpeg" && msg.Detail != "" {
				task.Speed = msg.Detail
			}
		}
		return m, nil

	case TaskCompleteMsg:
		if task, ok := m.tasks[msg.TaskID]; ok {
			task.Status = "completed"
			task.Percent = 100
			task.Outputs = msg.OutputCount
			m.totalCompleted++
			m.totalFiles += msg.OutputCount
		}
		m.addLog("success", "任务完成: %s, %d 个文件", msg.TaskID[:8], msg.OutputCount)
		return m, nil

	case TaskErrorMsg:
		if task, ok := m.tasks[msg.TaskID]; ok {
			task.Status = "failed"
			task.Detail = msg.Error
		}
		m.totalFailed++
		m.addLog("error", "任务失败: %s - %s", msg.TaskID[:8], msg.Error)
		return m, nil

	case LogMsg:
		m.addLog(msg.Level, msg.Message)
		return m, nil

	case StatusMsg:
		m.nodeStatus = msg.Status
		return m, nil
	}

	return m, nil
}

// View 渲染
func (m TUIModel) View() string {
	if m.quitting {
		return "再见！\n"
	}

	var sections []string

	// 1. 标题栏
	sections = append(sections, m.renderHeader())

	// 2. 节点状态栏
	sections = append(sections, m.renderStatusBar())

	// 3. 主内容区（左右分栏）
	contentWidth := m.width - 4
	leftWidth := contentWidth * 2 / 3
	rightWidth := contentWidth - leftWidth - 1

	leftPanel := m.renderTaskList(leftWidth)
	rightPanel := m.renderLogPanel(rightWidth)

	mainContent := lipgloss.JoinHorizontal(lipgloss.Top, leftPanel, " ", rightPanel)
	sections = append(sections, mainContent)

	// 4. 底部提示
	sections = append(sections, m.renderFooter())

	return lipgloss.JoinVertical(lipgloss.Left, sections...)
}

// ========== 渲染方法 ==========

func (m TUIModel) renderHeader() string {
	title := titleStyle.Render(" Slice Worker ")
	uptime := fmt.Sprintf("运行: %s", formatDuration(time.Since(m.startTime)))
	version := "v1.0.0"

	gap := m.width - lipgloss.Width(title) - lipgloss.Width(uptime) - lipgloss.Width(version)
	if gap < 0 {
		gap = 0
	}

	return title + strings.Repeat(" ", gap) + uptime + "  " + version
}

func (m TUIModel) renderStatusBar() string {
	items := []string{
		fmt.Sprintf("节点: %s", m.config.NodeID),
		fmt.Sprintf("标签: %s", strings.Join(m.config.Tags, ",")),
		fmt.Sprintf("并发: %d/%d", len(m.getActiveTasks()), m.config.MaxConcurrent),
		fmt.Sprintf("完成: %d", m.totalCompleted),
		fmt.Sprintf("失败: %d", m.totalFailed),
		fmt.Sprintf("文件: %d", m.totalFiles),
		fmt.Sprintf("状态: %s", m.nodeStatus),
	}

	content := strings.Join(items, "  │  ")
	return statusBarStyle.Width(m.width).Render(content)
}

func (m TUIModel) renderTaskList(width int) string {
	var lines []string

	// 标题
	lines = append(lines, lipgloss.NewStyle().Bold(true).Render("任务列表"))
	lines = append(lines, strings.Repeat("─", width-2))

	activeTasks := m.getActiveTasks()
	if len(activeTasks) == 0 && m.totalCompleted == 0 {
		lines = append(lines, "")
		lines = append(lines, "  暂无任务，等待中...")
		lines = append(lines, "")
	} else {
		// 显示最近的任务（最多显示10个）
		tasksToShow := m.taskOrder
		if len(tasksToShow) > 10 {
			tasksToShow = tasksToShow[len(tasksToShow)-10:]
		}

		for _, taskID := range tasksToShow {
			task := m.tasks[taskID]
			if task == nil {
				continue
			}
			lines = append(lines, m.renderTaskItem(task, width-2))
		}
	}

	content := strings.Join(lines, "\n")
	panelHeight := m.height - 8
	return panelStyle.Width(width).Height(panelHeight).Render(content)
}

func (m TUIModel) renderTaskItem(task *TaskStatus, width int) string {
	// 状态图标
	var icon string
	var style lipgloss.Style
	switch task.Status {
	case "running":
		icon = "▶"
		style = taskActiveStyle
	case "completed":
		icon = "✓"
		style = taskCompleteStyle
	case "failed":
		icon = "✗"
		style = taskErrorStyle
	default:
		icon = "○"
		style = lipgloss.NewStyle().Foreground(colorMuted)
	}

	// 任务ID（截短）
	shortID := task.TaskID
	if len(shortID) > 8 {
		shortID = shortID[:8]
	}

	// 进度条
	progressBar := ""
	if task.Status == "running" {
		progressBar = m.renderProgressBar(task.Percent, 20)
	}

	// 详情
	detail := ""
	if task.Status == "running" {
		phase := task.Phase
		switch phase {
		case "download":
			phase = "下载"
		case "ffmpeg":
			phase = "切片"
		case "upload":
			phase = "上传"
		}
		detail = fmt.Sprintf("[%s] %s", phase, task.Speed)
	} else if task.Status == "completed" {
		detail = fmt.Sprintf("%d 个文件", task.Outputs)
	} else if task.Status == "failed" {
		detail = task.Detail
		if len(detail) > 30 {
			detail = detail[:30] + "..."
		}
	}

	// 耗时
	elapsed := formatDuration(time.Since(task.StartTime))

	// 组装
	line := fmt.Sprintf("  %s %s  %s  %s  %s",
		icon,
		style.Render(shortID),
		progressBar,
		detail,
		logTimeStyle.Render(elapsed),
	)

	// 截断到宽度
	if lipgloss.Width(line) > width {
		line = line[:width]
	}

	return line
}

func (m TUIModel) renderProgressBar(percent float64, width int) string {
	filled := int(percent / 100 * float64(width))
	if filled > width {
		filled = width
	}
	empty := width - filled

	bar := strings.Repeat("█", filled) + strings.Repeat("░", empty)
	return progressBarStyle.Render(fmt.Sprintf("%s %3.0f%%", bar, percent))
}

func (m TUIModel) renderLogPanel(width int) string {
	var lines []string

	// 标题
	lines = append(lines, lipgloss.NewStyle().Bold(true).Render("实时日志"))
	lines = append(lines, strings.Repeat("─", width-2))

	// 日志内容
	logHeight := m.height - 8
	startIdx := 0
	if len(m.logs) > logHeight-3 {
		startIdx = len(m.logs) - (logHeight - 3)
	}

	for i := startIdx; i < len(m.logs); i++ {
		log := m.logs[i]
		timeStr := log.Time.Format("15:04:05")

		var style lipgloss.Style
		switch log.Level {
		case "info":
			style = logInfoStyle
		case "success":
			style = logSuccessStyle
		case "warn":
			style = logWarnStyle
		case "error":
			style = logErrorStyle
		default:
			style = lipgloss.NewStyle()
		}

		line := fmt.Sprintf("%s %s", logTimeStyle.Render(timeStr), style.Render(log.Message))
		// 截断
		if lipgloss.Width(line) > width-2 {
			// 简单截断
			for len(line) > width-2 {
				line = line[:len(line)-1]
			}
		}
		lines = append(lines, line)
	}

	content := strings.Join(lines, "\n")
	return panelStyle.Width(width).Height(logHeight).Render(content)
}

func (m TUIModel) renderFooter() string {
	help := "q: 退出  │  Ctrl+C: 强制退出"
	gap := m.width - lipgloss.Width(help)
	if gap < 0 {
		gap = 0
	}
	return strings.Repeat(" ", gap) + lipgloss.NewStyle().Foreground(colorMuted).Render(help)
}

// ========== 辅助方法 ==========

func (m *TUIModel) addLog(level, format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	m.logs = append(m.logs, LogEntry{
		Time:    time.Now(),
		Level:   level,
		Message: msg,
	})
	// 限制日志数量
	if len(m.logs) > m.maxLogs {
		m.logs = m.logs[len(m.logs)-m.maxLogs:]
	}
}

func (m TUIModel) getActiveTasks() []*TaskStatus {
	var active []*TaskStatus
	for _, task := range m.tasks {
		if task.Status == "running" {
			active = append(active, task)
		}
	}
	return active
}

func formatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	if d < time.Hour {
		return fmt.Sprintf("%dm%ds", int(d.Minutes()), int(d.Seconds())%60)
	}
	return fmt.Sprintf("%dh%dm", int(d.Hours()), int(d.Minutes())%60)
}

// ========== 消息类型 ==========

type TickMsg time.Time

type TaskStartMsg struct {
	TaskID    string
	EpisodeID string
	Mode      string
}

type TaskProgressMsg struct {
	TaskID  string
	Phase   string
	Percent float64
	Detail  string
}

type TaskCompleteMsg struct {
	TaskID      string
	OutputCount int
}

type TaskErrorMsg struct {
	TaskID string
	Error  string
}

type LogMsg struct {
	Level   string
	Message string
}

type StatusMsg struct {
	Status string
}

// ========== 命令 ==========

func (m TUIModel) tickCmd() tea.Cmd {
	return tea.Tick(200*time.Millisecond, func(t time.Time) tea.Msg {
		return TickMsg(t)
	})
}

func (m TUIModel) resizeCmd() tea.Cmd {
	return tea.WindowSize()
}
