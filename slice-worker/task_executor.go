package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// TaskExecutor 任务执行器
type TaskExecutor struct {
	config         *Config
	onTaskProgress func(taskID string, percent float64, speed string, eta string)
}

// NewTaskExecutor 创建任务执行器
func NewTaskExecutor(config *Config) *TaskExecutor {
	return &TaskExecutor{
		config: config,
	}
}

// SetProgressCallback 设置ffmpeg进度回调
func (te *TaskExecutor) SetProgressCallback(cb func(taskID string, percent float64, speed string, eta string)) {
	te.onTaskProgress = cb
}

// ExecuteTask 执行切片任务
//
// 调用 Python 引擎 engines/slice.py（与后端 Celery 路径共用同一套引擎），
// 签名：slice.py <source> <cutlist> <output_dir> --mode fast|dedupe|scrub [--intervals FILE]
// 引擎向 stdout 输出 PROGRESS:<pct> 与 OUTPUT:<name>:<duration> 行。
func (te *TaskExecutor) ExecuteTask(ctx context.Context, task *SliceTask, sourcePath string, outputDir string) ([]string, error) {
	// 创建输出目录
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return nil, fmt.Errorf("创建输出目录失败: %w", err)
	}

	// 写入 cutlist 文件
	cutlistPath := filepath.Join(outputDir, "cutlist.txt")
	if err := os.WriteFile(cutlistPath, []byte(task.Cutlist), 0644); err != nil {
		return nil, fmt.Errorf("写入cutlist失败: %w", err)
	}

	// 写入 intervals 文件（scrub 模式需要）
	var intervalsPath string
	if task.Intervals != "" {
		intervalsPath = filepath.Join(outputDir, "intervals.txt")
		if err := os.WriteFile(intervalsPath, []byte(task.Intervals), 0644); err != nil {
			return nil, fmt.Errorf("写入intervals失败: %w", err)
		}
	}

	// 构建命令：统一调用 Python 引擎 slice.py
	enginePath := filepath.Join(te.config.EnginesPath, "slice.py")
	args := []string{
		enginePath,
		sourcePath,
		cutlistPath,
		outputDir,
		"--mode", task.Mode,
	}
	if task.Mode == "scrub" {
		if intervalsPath == "" {
			return nil, fmt.Errorf("scrub模式需要提供intervals")
		}
		args = append(args, "--intervals", intervalsPath)
	}
	// CPU 资源分配：限制 ffmpeg 线程数/占用率，默认 50%
	cpuPercent := te.config.CPUPercent
	if cpuPercent < 1 || cpuPercent > 100 {
		cpuPercent = 50
	}
	args = append(args, "--cpu-percent", fmt.Sprintf("%d", cpuPercent))

	// 自定义文字水印：后端下发的 watermark 配置（JSON 透传给引擎）
	if task.Watermark != nil && len(task.Watermark) > 0 {
		wmBytes, err := json.Marshal(task.Watermark)
		if err == nil {
			args = append(args, "--watermark", string(wmBytes))
		}
	}

	// 三期 GPU 加速编码：后端下发的 encoder（如 h264_nvenc/hevc_videotoolbox）
	if task.Encoder != "" {
		args = append(args, "--encoder", task.Encoder)
	}

	// 去重档位配置：后端下发的 dedupe_config（如 {"preset":"light|standard|heavy"}）
	// JSON 透传给引擎 --dedupe-config，引擎按档位构造老电视质感去重滤镜链。
	if task.DedupeConfig != nil && len(task.DedupeConfig) > 0 {
		if dcBytes, err := json.Marshal(task.DedupeConfig); err == nil {
			args = append(args, "--dedupe-config", string(dcBytes))
		}
	}

	// 竖屏转横屏预处理：后端下发的 vert2horiz 配置（JSON 透传给引擎 --vert2horiz）
	if task.Vert2Horiz != nil && len(task.Vert2Horiz) > 0 {
		v2hBytes, err := json.Marshal(task.Vert2Horiz)
		if err == nil {
			args = append(args, "--vert2horiz", string(v2hBytes))
		}
	}

	// 图片角标：后端下发 badges（含已下载到本地的 path），透传给引擎 --badges
	if len(task.Badges) > 0 {
		badgeItems := make([]map[string]interface{}, 0)
		for _, b := range task.Badges {
			if b.Path == "" {
				continue
			}
			item := map[string]interface{}{
				"path":     b.Path,
				"position": b.Position,
			}
			if b.Width > 0 {
				item["width"] = b.Width
			}
			if b.Offset > 0 {
				item["offset"] = b.Offset
			}
			if b.Opacity != nil {
				item["opacity"] = *b.Opacity
			}
			badgeItems = append(badgeItems, item)
		}
		if len(badgeItems) > 0 {
			bBytes, err := json.Marshal(badgeItems)
			if err == nil {
				args = append(args, "--badges", string(bBytes))
			}
		}
	}

	// 角标默认尺寸：透传给引擎 --badge-default-width（0 时不传，保持原图尺寸）
	if task.BadgeDefaultWidth > 0 {
		args = append(args, "--badge-default-width", strconv.Itoa(task.BadgeDefaultWidth))
	}

	// ASR 字幕烧录：把后端下发的 SRT 内容写到本地文件，透传给引擎 --subtitle
	if len(task.Subtitle) > 0 {
		enabled, _ := task.Subtitle["enabled"].(bool)
		srtContent, _ := task.Subtitle["srt"].(string)
		if enabled && strings.TrimSpace(srtContent) != "" {
			subtitlePath := filepath.Join(outputDir, "subtitle.srt")
			if err := os.WriteFile(subtitlePath, []byte(srtContent), 0644); err != nil {
				return nil, fmt.Errorf("写入字幕文件失败: %w", err)
			}
			args = append(args, "--subtitle", subtitlePath)
			// 字幕字号（相对高度比例）：透传给引擎 --subtitle-font-ratio，未设置时用引擎默认值
			if fontRatio, ok := task.Subtitle["font_ratio"].(float64); ok && fontRatio > 0 {
				args = append(args, "--subtitle-font-ratio", strconv.FormatFloat(fontRatio, 'f', -1, 64))
			}
			// 字幕字间距（ASS Spacing 像素）：透传给引擎 --subtitle-spacing，未设置时用引擎默认值
			if sp, ok := task.Subtitle["spacing"].(float64); ok {
				args = append(args, "--subtitle-spacing", strconv.FormatFloat(sp, 'f', 0, 64))
			}
			// 字幕样式（default/custom 自定义字体色+边框色、无底色）：透传给引擎
			if st, ok := task.Subtitle["style"].(string); ok && st != "" {
				args = append(args, "--subtitle-style", st)
			}
			if fc, ok := task.Subtitle["font_color"].(string); ok && fc != "" {
				args = append(args, "--subtitle-color", fc)
			}
			if bc, ok := task.Subtitle["border_color"].(string); ok && bc != "" {
				args = append(args, "--subtitle-border-color", bc)
			}
		}
	}

	// 固定文字角标：直接透传给引擎 --text-overlays（无需下载，纯文本）
	if len(task.TextOverlays) > 0 {
		textBytes, err := json.Marshal(task.TextOverlays)
		if err != nil {
			return nil, fmt.Errorf("序列化固定文字角标失败: %w", err)
		}
		args = append(args, "--text-overlays", string(textBytes))
	}

	// 源视频字幕打码：透传给引擎 --subtitle-mask（去片源自带字幕，独立开关）
	if len(task.SubtitleMask) > 0 {
		enabled, _ := task.SubtitleMask["enabled"].(bool)
		if enabled {
			// 打码时间轴 SRT：后端把 SRT 文本放进 SubtitleMask["srt"]，
			// 这里写到本地文件并替换为路径，供引擎 --subtitle-mask 使用。
			if srtContent, ok := task.SubtitleMask["srt"].(string); ok && strings.TrimSpace(srtContent) != "" {
				maskSrtPath := filepath.Join(outputDir, "subtitle_mask.srt")
				if err := os.WriteFile(maskSrtPath, []byte(srtContent), 0644); err != nil {
					return nil, fmt.Errorf("写入源字幕打码时间轴文件失败: %w", err)
				}
				task.SubtitleMask["srt"] = maskSrtPath
			}
			maskBytes, err := json.Marshal(task.SubtitleMask)
			if err != nil {
				return nil, fmt.Errorf("序列化源字幕打码配置失败: %w", err)
			}
			args = append(args, "--subtitle-mask", string(maskBytes))
		}
	}

	// Alpine 镜像提供 python3 可执行文件；Windows 上为 python
	cmd := exec.CommandContext(ctx, pythonBinary(), args...)

	// 设置进程组，便于超时/取消时强杀整棵进程树（含 ffmpeg 子进程）
	SetProcessGroup(cmd)

	// 获取 stdout/stderr 管道用于解析进度
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("获取stdout管道失败: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("获取stderr管道失败: %w", err)
	}

	// 启动命令
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("启动命令失败: %w", err)
	}

	// 并行读取 stdout / stderr，避免管道阻塞
	outputs := make(chan string, 64)
	errCh := make(chan error, 2)
	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			outputs <- scanner.Text()
		}
		if err := scanner.Err(); err != nil {
			errCh <- err
		}
		close(outputs)
	}()
	go func() {
		// 透传 Python 引擎 stderr 到 worker 日志（带 [engine] 前缀），
		// 方便排查打码/检测等引擎内部诊断；行首 taskID 便于多任务并发时定位。
		scanner := bufio.NewScanner(stderr)
		taskIDShort := task.TaskID
		if len(taskIDShort) > 8 {
			taskIDShort = taskIDShort[:8]
		}
		for scanner.Scan() {
			fmt.Printf("[engine] %s %s\n", taskIDShort, scanner.Text())
		}
	}()

	// 解析引擎输出
	manifest := make(map[string]float64) // 文件名 -> 时长
	for line := range outputs {
		te.parseEngineLine(task.TaskID, line, manifest)
	}

	// 等待完成（context 超时/取消时 exec.CommandContext 会自动杀掉主进程，
	// 这里再兜底强杀整个进程组）
	if err := cmd.Wait(); err != nil {
		KillProcessTree(cmd)
		if ctx.Err() != nil {
			return nil, fmt.Errorf("任务超时或已取消: %w", ctx.Err())
		}
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("切片引擎执行失败，退出码: %d", exitErr.ExitCode())
		}
		return nil, fmt.Errorf("切片引擎执行失败: %w", err)
	}

	// 收集输出文件（以引擎 manifest 为准，同时兜底扫描目录）
	outputs2 := te.collectOutputs(outputDir, manifest)
	if len(outputs2) == 0 {
		return nil, fmt.Errorf("切片引擎未生成任何输出文件")
	}

	return outputs2, nil
}

// parseEngineLine 解析引擎输出行（PROGRESS / OUTPUT）
func (te *TaskExecutor) parseEngineLine(taskID, line string, manifest map[string]float64) {
	line = strings.TrimSpace(line)
	if strings.HasPrefix(line, "PROGRESS:") {
		pctStr := strings.TrimPrefix(line, "PROGRESS:")
		if pct, err := strconv.ParseFloat(pctStr, 64); err == nil && te.onTaskProgress != nil {
			te.onTaskProgress(taskID, pct, "", "")
		}
		return
	}
	if strings.HasPrefix(line, "OUTPUT:") {
		parts := strings.Split(strings.TrimPrefix(line, "OUTPUT:"), ":")
		if len(parts) >= 1 {
			name := parts[0]
			var dur float64
			if len(parts) >= 2 {
				dur, _ = strconv.ParseFloat(parts[1], 64)
			}
			manifest[name] = dur
		}
	}
}

// collectOutputs 收集输出文件
func (te *TaskExecutor) collectOutputs(outputDir string, manifest map[string]float64) []string {
	var outputs []string

	// 优先按 manifest 顺序收集
	if len(manifest) > 0 {
		for name := range manifest {
			path := filepath.Join(outputDir, name)
			if info, err := os.Stat(path); err == nil && !info.IsDir() {
				outputs = append(outputs, path)
			}
		}
		sort.Strings(outputs)
		return outputs
	}

	// 兜底：遍历目录收集 mp4 文件
	err := filepath.Walk(outputDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(strings.ToLower(info.Name()), ".mp4") {
			outputs = append(outputs, path)
		}
		return nil
	})
	if err == nil {
		sort.Strings(outputs)
	}
	return outputs
}

// KillProcessTree 强制终止进程树（平台相关，见 exec_unix.go / exec_windows.go）
