package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
)

// TaskExecutor 任务执行器
type TaskExecutor struct {
	config     *Config
	onFFmpegProgress func(taskID string, percent float64, speed string, eta string)
}

// NewTaskExecutor 创建任务执行器
func NewTaskExecutor(config *Config) *TaskExecutor {
	return &TaskExecutor{
		config: config,
	}
}

// SetProgressCallback 设置ffmpeg进度回调
func (te *TaskExecutor) SetProgressCallback(cb func(taskID string, percent float64, speed string, eta string)) {
	te.onFFmpegProgress = cb
}

// ExecuteTask 执行切片任务
func (te *TaskExecutor) ExecuteTask(task *SliceTask, sourcePath string, outputDir string) ([]string, error) {
	// 创建输出目录
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return nil, fmt.Errorf("创建输出目录失败: %w", err)
	}

	// 写入cutlist文件
	cutlistPath := filepath.Join(outputDir, "cutlist.txt")
	if err := os.WriteFile(cutlistPath, []byte(task.Cutlist), 0644); err != nil {
		return nil, fmt.Errorf("写入cutlist失败: %w", err)
	}

	// 写入intervals文件（如果有）
	var intervalsPath string
	if task.Intervals != "" {
		intervalsPath = filepath.Join(outputDir, "intervals.txt")
		if err := os.WriteFile(intervalsPath, []byte(task.Intervals), 0644); err != nil {
			return nil, fmt.Errorf("写入intervals失败: %w", err)
		}
	}

	// 写入dedupe.conf（如果有配置）
	var dedupeConfPath string
	if len(task.DedupeConfig) > 0 {
		dedupeConfPath = filepath.Join(outputDir, "dedupe.conf")
		if err := te.writeDedupeConf(dedupeConfPath, task.DedupeConfig); err != nil {
			return nil, fmt.Errorf("写入dedupe.conf失败: %w", err)
		}
	}

	// 构建命令
	var cmd *exec.Cmd
	switch task.Mode {
	case "scrub":
		if intervalsPath == "" {
			return nil, fmt.Errorf("scrub模式需要提供intervals")
		}
		cmd = exec.Command("bash",
			filepath.Join(te.config.EnginesPath, "slice_scrub.sh"),
			sourcePath, cutlistPath, intervalsPath, outputDir)
	case "dedupe":
		cmd = exec.Command("bash",
			filepath.Join(te.config.EnginesPath, "slice.sh"),
			sourcePath, cutlistPath, "dedupe")
	case "fast":
		cmd = exec.Command("bash",
			filepath.Join(te.config.EnginesPath, "slice.sh"),
			sourcePath, cutlistPath, "fast")
	default:
		return nil, fmt.Errorf("未知的切片模式: %s", task.Mode)
	}

	// 设置环境变量
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("DEDUPE_CONF=%s", dedupeConfPath),
		fmt.Sprintf("OUTPUT_DIR=%s", outputDir),
	)

	// 获取stderr管道用于解析进度
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("获取stderr管道失败: %w", err)
	}

	// 启动命令
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("启动命令失败: %w", err)
	}

	// 解析ffmpeg进度
	scanner := bufio.NewScanner(stderr)
	scanner.Split(scanFFmpegLines)
	for scanner.Scan() {
		line := scanner.Text()
		te.parseFFmpegProgress(task.TaskID, line)
	}

	// 等待完成
	if err := cmd.Wait(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("ffmpeg执行失败，退出码: %d", exitErr.ExitCode())
		}
		return nil, fmt.Errorf("ffmpeg执行失败: %w", err)
	}

	// 收集输出文件
	outputs, err := te.collectOutputs(outputDir)
	if err != nil {
		return nil, fmt.Errorf("收集输出文件失败: %w", err)
	}

	return outputs, nil
}

// writeDedupeConf 写入去重配置
func (te *TaskExecutor) writeDedupeConf(path string, config map[string]float64) error {
	var lines []string

	if v, ok := config["speed_factor"]; ok {
		lines = append(lines, "SPEED_CHANGE=on")
		lines = append(lines, fmt.Sprintf("SPEED_FACTOR=%.4f", v))
	}
	if v, ok := config["saturation"]; ok {
		lines = append(lines, "SATURATION=on")
		lines = append(lines, fmt.Sprintf("SATURATION_VALUE=%.4f", v))
	}
	if v, ok := config["brightness"]; ok {
		lines = append(lines, "BRIGHTNESS=on")
		lines = append(lines, fmt.Sprintf("BRIGHTNESS_VALUE=%.4f", v))
	}
	if v, ok := config["sharpen"]; ok {
		lines = append(lines, "SHARPEN=on")
		lines = append(lines, fmt.Sprintf("SHARPEN_AMOUNT=%.4f", v))
	}

	return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0644)
}

// parseFFmpegProgress 解析ffmpeg进度输出
func (te *TaskExecutor) parseFFmpegProgress(taskID, line string) {
	// 匹配 time=00:01:23.45
	timeRe := regexp.MustCompile(`time=(\d+):(\d+):(\d+\.\d+)`)
	timeMatch := timeRe.FindStringSubmatch(line)

	// 匹配 speed=1.23x
	speedRe := regexp.MustCompile(`speed=\s*([\d.]+)x`)
	speedMatch := speedRe.FindStringSubmatch(line)

	if timeMatch != nil && te.onFFmpegProgress != nil {
		hours, _ := strconv.ParseFloat(timeMatch[1], 64)
		minutes, _ := strconv.ParseFloat(timeMatch[2], 64)
		seconds, _ := strconv.ParseFloat(timeMatch[3], 64)
		currentSec := hours*3600 + minutes*60 + seconds

		// 简单估算百分比（假设总时长，实际应该从任务信息获取）
		// 这里用当前时间作为进度的粗略指示
		percent := 0.0
		if currentSec > 0 {
			// 简化处理：假设进度随时间增长
			percent = (currentSec / 600) * 100 // 假设10分钟视频
			if percent > 99 {
				percent = 99
			}
		}

		speed := ""
		if speedMatch != nil {
			speed = speedMatch[1] + "x"
		}

		te.onFFmpegProgress(taskID, percent, speed, "")
	}
}

// collectOutputs 收集输出文件
func (te *TaskExecutor) collectOutputs(outputDir string) ([]string, error) {
	var outputs []string

	// 遍历输出目录
	err := filepath.Walk(outputDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(strings.ToLower(info.Name()), ".mp4") {
			outputs = append(outputs, path)
		}
		return nil
	})

	return outputs, err
}

// scanFFmpegLines 自定义scanner分割函数，处理ffmpeg的\r进度输出
func scanFFmpegLines(data []byte, atEOF bool) (advance int, token []byte, err error) {
	// 查找 \r 或 \n
	for i := 0; i < len(data); i++ {
		if data[i] == '\r' || data[i] == '\n' {
			return i + 1, data[:i], nil
		}
	}

	// 如果到末尾了
	if atEOF {
		return len(data), data, nil
	}

	// 需要更多数据
	return 0, nil, nil
}

// KillProcess 强制终止进程组
func KillProcess(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	// 终止整个进程组
	pgid, err := syscall.Getpgid(cmd.Process.Pid)
	if err == nil {
		return syscall.Kill(-pgid, syscall.SIGKILL)
	}
	return cmd.Process.Kill()
}
