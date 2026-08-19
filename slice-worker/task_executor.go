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
	"sync"
	"time"
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

	// —— 断点续传（issue #242 根因 2）——
	// worker 被重启/强杀后，runTask 的 defer 清理未执行，outputDir 中残留上一次已
	// 产出的部分成品。这里按 .completed checkpoint 过滤出已完整完成的段，引擎只处理
	// 剩余段，避免 dedupe 长任务从第 1 段重头跑而占满 worker、新任务排队。
	segs := parseCutlist(task.Cutlist)
	remainingSegs, completedNames := te.filterCompletedSegments(outputDir, segs)
	// 已完成段的产物路径（checkpoint 确认 + 文件有效），用于合并进最终上传清单
	preservedOutputs := te.preservedOutputs(outputDir, segs)
	if len(completedNames) > 0 {
		fmt.Printf("断点续传: 任务 %s 已跳过 %d 个已完成段: %v\n", task.TaskID, len(completedNames), completedNames)
	}
	// 所有段均已完成：直接复用产出，不再调用引擎（耗时任务重启后立即完成）
	if len(completedNames) > 0 && len(remainingSegs) == 0 {
		fmt.Printf("断点续传: 任务 %s 所有段均已完成，跳过引擎\n", task.TaskID)
		return preservedOutputs, nil
	}
	// 部分完成：重写 cutlist，让引擎只处理剩余段（保持原段名/顺序，引擎按名分组）
	if len(remainingSegs) < len(segs) {
		if err := os.WriteFile(cutlistPath, []byte(cutlistForSegments(remainingSegs)), 0644); err != nil {
			return nil, fmt.Errorf("写入续传cutlist失败: %w", err)
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

	// 视频封面：作为视频首帧叠加（后端下发 cover URL，Worker 已下载到本地 path）
	if task.Cover.Path != "" {
		args = append(args, "--cover", task.Cover.Path)
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

	// 字幕对齐源字幕打码区域开关（默认开启）：关闭时透传给引擎 --subtitle-align-mask 0
	if task.SubtitleAlignMask != nil && !*task.SubtitleAlignMask {
		args = append(args, "--subtitle-align-mask", "0")
	}

	// 恒定水印/角标打码：透传给引擎 --watermark-mask（打掉片源固定水印，独立开关）
	if len(task.WatermarkMask) > 0 {
		enabled, _ := task.WatermarkMask["enabled"].(bool)
		if enabled {
			wmBytes, err := json.Marshal(task.WatermarkMask)
			if err != nil {
				return nil, fmt.Errorf("序列化恒定水印打码配置失败: %w", err)
			}
			args = append(args, "--watermark-mask", string(wmBytes))
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
	// 环形缓冲：保留引擎 stderr 最近 N 行，失败时拼进错误消息方便排查根因
	const stderrBufLines = 60
	stderrBuf := make([]string, 0, stderrBufLines)
	var stderrMu sync.Mutex
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
			line := scanner.Text()
			fmt.Printf("[engine] %s %s\n", taskIDShort, line)
			// 环形缓冲：满了丢弃最旧
			stderrMu.Lock()
			if len(stderrBuf) >= stderrBufLines {
				copy(stderrBuf, stderrBuf[1:])
				stderrBuf = stderrBuf[:stderrBufLines-1]
			}
			stderrBuf = append(stderrBuf, line)
			stderrMu.Unlock()
		}
	}()

	// 解析引擎输出
	manifest := make(map[string]float64) // 文件名 -> 时长
	var doneNames []string               // 本次新完成的成品名（用于写断点续传 checkpoint）
	for line := range outputs {
		if name := te.parseEngineLine(task.TaskID, line, manifest); name != "" {
			doneNames = append(doneNames, name)
		}
	}
	// 引擎每完成一段会打印 OUTPUT:<name>，这里把已完成的段持久化到 checkpoint 文件，
	// 供断点续传判断哪些段无需重跑（即使后续某段失败/进程被强杀，已完成段也要保留）。
	te.appendCompletedCheckpoint(outputDir, doneNames)

	// 等待完成（context 超时/取消时 exec.CommandContext 会自动杀掉主进程，
	// 这里再兜底强杀整个进程组）
	if err := cmd.Wait(); err != nil {
		KillProcessTree(cmd)
		if ctx.Err() != nil {
			return nil, fmt.Errorf("任务超时或已取消: %w", ctx.Err())
		}
		// 引擎失败：把 stderr 最近内容拼进错误消息，便于定位打码/检测/ffmpeg 失败根因
		stderrMu.Lock()
		engineErrTail := strings.Join(stderrBuf, "\n")
		stderrMu.Unlock()
		if engineErrTail != "" {
			if len(engineErrTail) > 3000 {
				engineErrTail = "...[截断]...\n" + engineErrTail[len(engineErrTail)-3000:]
			}
			if exitErr, ok := err.(*exec.ExitError); ok {
				return nil, fmt.Errorf("切片引擎执行失败，退出码: %d\n--- 引擎输出 ---\n%s", exitErr.ExitCode(), engineErrTail)
			}
			return nil, fmt.Errorf("切片引擎执行失败: %w\n--- 引擎输出 ---\n%s", err, engineErrTail)
		}
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("切片引擎执行失败，退出码: %d", exitErr.ExitCode())
		}
		return nil, fmt.Errorf("切片引擎执行失败: %w", err)
	}

	// 收集输出文件（以引擎 manifest 为准，同时兜底扫描目录）
	outputs2 := te.collectOutputs(outputDir, manifest)
	// 合并断点续传遗留的已产出成品（不在本次引擎 manifest 中，按名去重排序）
	if len(preservedOutputs) > 0 {
		outputs2 = mergeOutputPaths(preservedOutputs, outputs2)
	}
	if len(outputs2) == 0 {
		return nil, fmt.Errorf("切片引擎未生成任何输出文件")
	}

	return outputs2, nil
}

// parseEngineLine 解析引擎输出行（PROGRESS / OUTPUT）。
// 返回新完成的成品名（OUTPUT 行），非 OUTPUT 行返回空字符串。
func (te *TaskExecutor) parseEngineLine(taskID, line string, manifest map[string]float64) string {
	line = strings.TrimSpace(line)
	if strings.HasPrefix(line, "PROGRESS:") {
		pctStr := strings.TrimPrefix(line, "PROGRESS:")
		if pct, err := strconv.ParseFloat(pctStr, 64); err == nil && te.onTaskProgress != nil {
			te.onTaskProgress(taskID, pct, "", "")
		}
		return ""
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
			return name
		}
	}
	return ""
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

// cutSegment 表示 cutlist 中的一段切片（start, end, name）。
// name 即引擎输出的成品文件名（slice.py 会经 safe_name 追加 .mp4 后缀）。
type cutSegment struct {
	Start float64
	End   float64
	Name  string
}

// parseCutlist 解析 cutlist 文本为段列表（与引擎 engines/slice.py 的 read_cutlist 对齐）。
// 每行格式：start_time end_time clip_name。解析失败的行忽略（与引擎一致）。
func parseCutlist(content string) []cutSegment {
	var segs []cutSegment
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 3 {
			continue
		}
		start, err := parseCutTime(parts[0])
		if err != nil {
			continue
		}
		end, err := parseCutTime(parts[1])
		if err != nil {
			continue
		}
		segs = append(segs, cutSegment{Start: start, End: end, Name: parts[2]})
	}
	return segs
}

// parseCutTime 解析引擎时间格式（H:MM:SS.mmm / MM:SS.mmm / SS.mmm）为秒数。
func parseCutTime(s string) (float64, error) {
	s = strings.TrimSpace(s)
	parts := strings.Split(s, ":")
	switch len(parts) {
	case 3:
		h, err := strconv.ParseFloat(parts[0], 64)
		if err != nil {
			return 0, err
		}
		m, err := strconv.ParseFloat(parts[1], 64)
		if err != nil {
			return 0, err
		}
		sec, err := strconv.ParseFloat(parts[2], 64)
		if err != nil {
			return 0, err
		}
		return h*3600 + m*60 + sec, nil
	case 2:
		m, err := strconv.ParseFloat(parts[0], 64)
		if err != nil {
			return 0, err
		}
		sec, err := strconv.ParseFloat(parts[1], 64)
		if err != nil {
			return 0, err
		}
		return m*60 + sec, nil
	default:
		sec, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return 0, err
		}
		return sec, nil
	}
}

// outputName 返回段对应的成品文件名（引擎 safe_name 逻辑：basename + .mp4）。
func (c cutSegment) outputName() string {
	name := filepath.Base(c.Name)
	if strings.HasSuffix(strings.ToLower(name), ".mp4") {
		return name
	}
	return name + ".mp4"
}

// filterCompletedSegments 依据断点续传 checkpoint（.completed）中记录的已完整产出段，
// 把已完成段从列表中过滤掉，返回（剩余段, 已完成段名列表）。
//
// 背景（issue #242 根因 2）：dedupe 长任务（如 1080p 多段）被 worker 重启/强杀后，
// 历史实现从第 1 段重头跑，期间该 worker 不再消费新任务。这里通过 .completed checkpoint
// （引擎每完成一段的 OUTPUT 行都会写入）实现断点续传：只有引擎确认完整产出的段才跳过，
// 避免半成品/缺后处理（角标/封面/字幕）的段被误当完成。
func (te *TaskExecutor) filterCompletedSegments(outputDir string, segs []cutSegment) ([]cutSegment, []string) {
	completedSet := te.readCompletedCheckpoint(outputDir)
	var remaining []cutSegment
	var completed []string
	for _, seg := range segs {
		name := seg.outputName()
		// 仅当 checkpoint 记录完成 且 产物文件仍有效时才跳过
		if completedSet[name] && te.outputFileValid(filepath.Join(outputDir, name)) {
			completed = append(completed, seg.Name)
			continue
		}
		remaining = append(remaining, seg)
	}
	return remaining, completed
}

// preservedOutputs 返回 checkpoint 确认已完成且产物文件仍有效的段路径（断点续传遗留）。
func (te *TaskExecutor) preservedOutputs(outputDir string, segs []cutSegment) []string {
	completedSet := te.readCompletedCheckpoint(outputDir)
	var outputs []string
	for _, seg := range segs {
		name := seg.outputName()
		if !completedSet[name] {
			continue
		}
		path := filepath.Join(outputDir, name)
		if te.outputFileValid(path) {
			outputs = append(outputs, path)
		}
	}
	sort.Strings(outputs)
	return outputs
}

// outputFileValid 判断已存在的产出文件是否有效可复用。
// 强杀时 ffmpeg 可能写出截断/半成品文件，仅判断存在不够——用 ffprobe 探测
// 时长 > 0 且文件非空，确保复用的是完整成品而非残缺段。
func (te *TaskExecutor) outputFileValid(path string) bool {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() || info.Size() == 0 {
		return false
	}
	dur, err := ffprobeDurationSec(path)
	if err != nil || dur <= 0 {
		return false
	}
	return true
}

// ffprobeDurationSec 用 ffprobe 读取视频时长（秒），失败返回 0。
func ffprobeDurationSec(path string) (float64, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "ffprobe",
		"-v", "error",
		"-show_entries", "format=duration",
		"-of", "default=noprint_wrappers=1:nokey=1",
		path,
	).Output()
	if err != nil {
		return 0, err
	}
	return strconv.ParseFloat(strings.TrimSpace(string(out)), 64)
}

// checkpointFile 断点续传 checkpoint 文件名（存于输出目录，记录已完整产出的成品名）。
const checkpointFile = ".completed"

// readCompletedCheckpoint 读取断点续传 checkpoint，返回 成品文件名 -> 是否完成 的集合。
func (te *TaskExecutor) readCompletedCheckpoint(outputDir string) map[string]bool {
	set := make(map[string]bool)
	data, err := os.ReadFile(filepath.Join(outputDir, checkpointFile))
	if err != nil {
		return set
	}
	for _, line := range strings.Split(string(data), "\n") {
		name := strings.TrimSpace(line)
		if name != "" {
			set[name] = true
		}
	}
	return set
}

// appendCompletedCheckpoint 把新完成的成品名追加写入 checkpoint（去重，追加写避免整文件重写）。
func (te *TaskExecutor) appendCompletedCheckpoint(outputDir string, names []string) {
	if len(names) == 0 {
		return
	}
	path := filepath.Join(outputDir, checkpointFile)
	existing := te.readCompletedCheckpoint(outputDir)
	var sb strings.Builder
	for _, n := range names {
		if n == "" {
			continue
		}
		sb.WriteString(n + "\n")
		delete(existing, n) // 不重复追加已存在的
	}
	if sb.Len() == 0 {
		return
	}
	// 先写临时文件再改名，避免强杀导致 checkpoint 文件半截损坏
	if info, err := os.Stat(path); err == nil && !info.IsDir() {
		if existingData, err := os.ReadFile(path); err == nil {
			sb.WriteString(string(existingData))
		}
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(sb.String()), 0644); err == nil {
		_ = os.Rename(tmp, path)
	}
}

// cutlistForSegments 把剩余段序列化回 cutlist 文本（供引擎只处理剩余段）。
// 时间格式与后端 format_time 一致：保留 3 位小数。
func cutlistForSegments(segs []cutSegment) string {
	var sb strings.Builder
	for _, s := range segs {
		sb.WriteString(fmt.Sprintf("%s %s %s\n", formatSec(s.Start), formatSec(s.End), s.Name))
	}
	return sb.String()
}

// formatSec 秒数转引擎/后端时间格式（H:MM:SS.mmm，与前端一致）。
func formatSec(sec float64) string {
	if sec < 0 {
		sec = 0
	}
	total := int64(sec * 1000)
	h := total / 3600000
	m := (total % 3600000) / 60000
	s := (total % 60000) / 1000
	ms := total % 1000
	return fmt.Sprintf("%d:%02d:%02d.%03d", h, m, s, ms)
}

// mergeOutputPaths 合并两批输出路径并按字典序去重排序。
func mergeOutputPaths(a, b []string) []string {
	seen := make(map[string]bool, len(a)+len(b))
	merged := make([]string, 0, len(a)+len(b))
	for _, p := range append(append([]string{}, a...), b...) {
		if !seen[p] {
			seen[p] = true
			merged = append(merged, p)
		}
	}
	sort.Strings(merged)
	return merged
}

// KillProcessTree 强制终止进程树（平台相关，见 exec_unix.go / exec_windows.go）
