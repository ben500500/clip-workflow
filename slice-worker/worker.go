package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// 优雅退出时等待正在执行任务完成的超时（切片任务可能耗时数分钟）
const gracefulShutdownTimeout = 15 * time.Minute

// uuidDirRe 匹配任务临时目录名（UUID 格式）
var uuidDirRe = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// Worker 核心工作节点
type Worker struct {
	config   *Config
	redis    *RedisClient
	executor *TaskExecutor
	transfer *FileTransfer
	callback *CallbackService

	// 状态
	currentTasks   int32
	runningTasks   sync.Map // taskID -> *RunningTask
	totalCompleted int32
	totalFailed    int32
	// 本节点当前引擎版本（启动时计算，推送更新后原子更新）
	engineVersion string
	// 本节点硬件编码能力（启动时检测一次，供心跳/注册上报；预留 GPU 自动分派接口）
	encoderCapabilities []string

	// 回调
	onTaskStart    func(task *SliceTask)
	onTaskProgress func(taskID string, phase string, percent float64, detail string)
	onTaskComplete func(taskID string, outputs []string)
	onTaskError    func(taskID string, err error)
	onLog          func(level string, msg string)
}

// RunningTask 正在运行的任务
type RunningTask struct {
	Task      *SliceTask
	MsgID     string
	Stream    string
	StartTime time.Time
	Cancel    context.CancelFunc
}

// NewWorker 创建Worker
func NewWorker(config *Config, redis *RedisClient) *Worker {
	return &Worker{
		config:   config,
		redis:    redis,
		executor: NewTaskExecutor(config),
		transfer: NewFileTransfer(),
		callback: NewCallbackService(config.NodeID),
	}
}

// SetCallbacks 设置回调
func (w *Worker) SetCallbacks(
	onStart func(task *SliceTask),
	onProgress func(taskID string, phase string, percent float64, detail string),
	onComplete func(taskID string, outputs []string),
	onError func(taskID string, err error),
	onLog func(level string, msg string),
) {
	w.onTaskStart = onStart
	w.onTaskProgress = onProgress
	w.onTaskComplete = onComplete
	w.onTaskError = onError
	w.onLog = onLog

	// 设置文件传输进度回调
	w.transfer.SetProgressCallback(func(taskID, fileName string, downloaded, total int64) {
		percent := float64(0)
		if total > 0 {
			percent = float64(downloaded) / float64(total) * 100
		}
		if w.onTaskProgress != nil {
			w.onTaskProgress(taskID, "transfer", percent, fmt.Sprintf("%s: %d/%d", fileName, downloaded, total))
		}
	})

	// 设置引擎进度回调
	w.executor.SetProgressCallback(func(taskID string, percent float64, speed string, eta string) {
		if w.onTaskProgress != nil {
			w.onTaskProgress(taskID, "ffmpeg", percent, fmt.Sprintf("speed=%s", speed))
		}
	})
}

// Run 启动Worker主循环
// checkEngine 启动时对引擎做 py_compile 自检，尽早暴露 Python 版本不兼容
// （引擎要求 Python 3.10+，低版本会抛 str|None TypeError）或引擎文件损坏问题
// ——否则要等第一条任务才会失败，且失败信息容易误导排查。
func (w *Worker) checkEngine() {
	enginePath := filepath.Join(w.config.EnginesPath, "slice.py")
	if _, err := os.Stat(enginePath); err != nil {
		w.log("warn", "引擎文件不存在 %s: %v（将无法处理任务）", enginePath, err)
		return
	}
	py := pythonBinary()
	cmd := exec.Command(py, "-m", "py_compile", enginePath)
	out, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if len(msg) > 600 {
			msg = msg[len(msg)-600:]
		}
		w.log("warn", "引擎自检失败（Python=%s，引擎要求 3.10+，可能无法运行）: %v\n%s",
			py, err, msg)
		return
	}
	w.log("info", "引擎自检通过: Python=%s, 引擎=%s", py, enginePath)
}

func (w *Worker) Run(ctx context.Context) error {
	// 启动时计算本节点本地引擎版本（供心跳上报/推送更新判断）
	if v, err := ComputeEngineVersion(w.config.EnginesPath); err == nil {
		w.engineVersion = v
	} else {
		w.engineVersion = ""
		w.log("warn", "计算引擎版本失败（将无法接收推送更新）: %v", err)
	}

	// 检测本节点硬件编码能力（启动时一次即可，供注册/心跳上报；预留 GPU 自动分派接口）
	w.encoderCapabilities = GetEncoderCapabilities()
	if len(w.encoderCapabilities) > 0 {
		w.log("info", "检测到硬件编码能力: %v", w.encoderCapabilities)
	}

	// 引擎自检：尽早暴露 Python 版本不兼容/引擎文件损坏等问题，
	// 而不是等到第一条任务才失败（引擎要求 Python 3.10+，低版本会 TypeError）。
	w.checkEngine()

	// 注册节点
	nodeInfo := &NodeInfo{
		NodeID:              w.config.NodeID,
		Hostname:            getHostname(),
		OS:                  GetOS(),
		Arch:                GetArch(),
		FFmpegVersion:       GetFFmpegVersion(),
		Tags:                w.config.Tags,
		MaxConcurrent:       w.config.MaxConcurrent,
		CurrentTasks:        0,
		Status:              "online",
		LastHeartbeat:       time.Now().Unix(),
		IP:                  GetIP(),
		StartedAt:           time.Now().Unix(),
		TotalTasksCompleted: 0,
		TotalTasksFailed:    0,
		CPUPercent:          w.config.CPUPercent,
		EngineVersion:       w.engineVersion,
		EncoderCapabilities: w.encoderCapabilities,
	}

	if err := w.redis.RegisterNode(nodeInfo, w.config.HeartbeatTTL()); err != nil {
		return fmt.Errorf("注册节点失败: %w", err)
	}
	w.log("info", "节点注册成功: %s", w.config.NodeID)

	// 启动时清理孤儿临时目录（上次强杀/崩溃遗留的残留目录）
	w.cleanupOrphanDirs()

	// 确保退出时注销
	defer func() {
		w.redis.UnregisterNode(w.config.NodeID, w.config.Tags)
		w.log("info", "节点已注销")
	}()

	// 创建消费者组
	streams := w.config.EffectiveConsumeStreams()
	for _, stream := range streams {
		if err := w.redis.CreateConsumerGroup(stream, "workers"); err != nil {
			w.log("warn", "创建消费者组失败 %s: %v", stream, err)
		}
	}

	// 启动心跳
	go w.heartbeatLoop(ctx)

	// 启动引擎更新检查（服务器推送引擎更新后自动拉取应用，无需重新部署）
	go w.engineUpdateLoop(ctx)

	// 启动 PEL 恢复（认领崩溃遗留的未完成消息）
	go w.claimLoop(ctx)

	// 主消费循环
	w.log("info", "开始消费任务，最大并发: %d，消费流: %v", w.config.MaxConcurrent, streams)
	for {
		select {
		case <-ctx.Done():
			w.log("info", "收到退出信号，等待正在执行的任务完成（最多 %s）", gracefulShutdownTimeout)
			// 优雅退出：停止认领新任务，等待当前任务跑完（避免强杀导致临时目录残留）
			w.waitRunningTasks(gracefulShutdownTimeout)
			w.log("info", "优雅退出完成")
			return nil
		default:
			// 检查节点是否被管理员停用（停用后暂停领取新任务，正在执行的不受影响）
			enabled, err := w.redis.IsNodeEnabled(w.config.NodeID)
			if err == nil && !enabled {
				w.log("warn", "节点已被管理员停用，暂停领取新任务")
				time.Sleep(3 * time.Second)
				continue
			}

			// 检查并发上限
			if int(atomic.LoadInt32(&w.currentTasks)) >= w.config.MaxConcurrent {
				time.Sleep(500 * time.Millisecond)
				continue
			}

			// 获取任务
			msg, err := w.redis.FetchTask(streams, "workers", w.config.NodeID, 1*time.Second)
			if err != nil {
				w.log("error", "获取任务失败: %v", err)
				time.Sleep(1 * time.Second)
				continue
			}
			if msg == nil {
				continue
			}

			// 检查标签匹配
			if !w.matchTags(msg.Task.RequiredTags) {
				w.log("debug", "标签不匹配，重新入队: %s", msg.Task.TaskID)
				w.redis.RequeueTask(msg.Stream, msg.RawData)
				continue
			}

			// 启动任务
			go w.runTask(msg)
		}
	}
}

// cleanupOrphanDirs 启动时清理孤儿临时目录。
//
// 场景：worker 被强杀（如 docker compose --force-recreate 或 OOM）时，正在处理的
// 任务进程被 SIGKILL，runTask 的 defer 清理未执行，任务目录（含下载的源视频、
// 中间文件）残留。重启后这些消息会被幂等检测跳过（终态直接 ACK），不再触发清理，
// 需要在此兜底。
//
// 注意 TempDir 为多 worker 共享卷：只清理「非 UUID 目录」或「UUID 目录但 redis 中
// 无对应任务 / 任务已终态」的目录；running/pending 的任务目录必须跳过（可能正被
// 其他 worker 使用）。
func (w *Worker) cleanupOrphanDirs() {
	entries, err := os.ReadDir(w.config.TempDir)
	if err != nil {
		w.log("warn", "扫描临时目录失败: %v", err)
		return
	}
	removed := 0
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		dir := filepath.Join(w.config.TempDir, name)
		if !uuidDirRe.MatchString(name) {
			// 非 UUID 目录（如手工测试残留 repro-* 等）：直接清理
			if rmErr := os.RemoveAll(dir); rmErr == nil {
				w.log("info", "清理非任务残留目录: %s", name)
				removed++
			}
			continue
		}
		// UUID 目录：查 redis 任务状态决定是否孤儿
		status, err := w.redis.GetTaskStatus(name)
		if err != nil {
			continue // 查询失败保守跳过
		}
		if status == "" || status == "completed" || status == "failed" || status == "cancelled" {
			if rmErr := os.RemoveAll(dir); rmErr == nil {
				w.log("info", "清理孤儿任务目录: %s (status=%q)", name, status)
				removed++
			}
		}
	}
	w.log("info", "临时目录清理完成，共清理 %d 个残留目录", removed)
}

// waitRunningTasks 等待正在执行的任务全部完成（优雅退出），带超时保护。
func (w *Worker) waitRunningTasks(timeout time.Duration) {
	deadline := time.Now().Add(timeout)
	for {
		n := 0
		w.runningTasks.Range(func(_, _ interface{}) bool {
			n++
			return true
		})
		if n == 0 {
			w.log("info", "所有任务已完成，退出")
			return
		}
		if time.Now().After(deadline) {
			w.log("warn", "等待超时（仍有 %d 个任务在执行），强制退出", n)
			return
		}
		time.Sleep(500 * time.Millisecond)
	}
}

// claimLoop 定期从 PEL 认领超时未完成的任务（Worker 崩溃恢复）
func (w *Worker) claimLoop(ctx context.Context) {
	streams := w.config.EffectiveConsumeStreams()
	// 认领阈值：任务进入 PEL 超过 minIdle 且无租约的视为孤儿任务。
	// 调大至 5 分钟（原为 3×心跳≈30s）：切片任务通常耗时数分钟，过短阈值会把
	// 正常处理中的任务误判为孤儿重新执行，导致与已完成任务冲突、状态污染。
	minIdle := time.Duration(5) * time.Minute
	ticker := time.NewTicker(minIdle)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			claimed, err := w.redis.ClaimStaleTasks(streams, "workers", w.config.NodeID, minIdle)
			if err != nil {
				w.log("error", "PEL 认领失败: %v", err)
				continue
			}
			for _, msg := range claimed {
				// 跳过仍在正常处理中的任务（任务 Hash 中 status 仍为 running 且租约新鲜）
				hash, err := w.redis.GetTaskHash(msg.Task.TaskID)
				if err != nil {
					continue
				}
				if hash["status"] == "running" && hash["lease"] != "" {
					leaseTS, _ := strconvParseInt(hash["lease"])
					// 租约新鲜度阈值与 minIdle 一致（5 分钟）：心跳每 10s 续期，
					// 正常任务租约恒新鲜，只有 Worker 真正宕机 5 分钟后才会被认领
					if time.Now().Unix()-leaseTS < int64(5*60) {
						continue // 任务仍被存活 Worker 处理
					}
				}
				if hash["status"] == "completed" || hash["status"] == "failed" {
					// 终态任务直接 ACK，避免重复处理
					w.redis.AckTask(msg.Stream, "workers", msg.ID)
					continue
				}

				// 标记为待重试并重新执行
				w.log("warn", "认领到孤儿任务: %s (stream=%s, msg=%s)", msg.Task.TaskID, msg.Stream, msg.ID)
				go w.runTask(msg)
			}
		}
	}
}

// runTask 执行单个任务
func (w *Worker) runTask(msg *StreamMessage) {
	task := msg.Task

	// 去重：若任务已在运行中则跳过
	if _, exists := w.runningTasks.Load(task.TaskID); exists {
		return
	}

	// 幂等：若任务已达终态（completed/failed/cancelled），直接 ACK 跳过，
	// 避免残留消息被重复执行导致状态被污染（已完成的成品不重复生成）。
	if hash, err := w.redis.GetTaskHash(task.TaskID); err == nil {
		if st := hash["status"]; st == "completed" || st == "failed" || st == "cancelled" {
			w.log("info", "任务 %s 已处于终态(%s)，跳过重复执行并 ACK", task.TaskID, st)
			if ackErr := w.redis.AckTask(msg.Stream, "workers", msg.ID); ackErr != nil {
				w.log("error", "终态任务 ACK 失败: %v", ackErr)
			}
			return
		}
	}

	timeout := time.Duration(task.TimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = time.Duration(w.config.TaskTimeout) * time.Second
	}
	taskCtx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	// 记录运行中的任务（Cancel 可在取消接口中调用）
	rt := &RunningTask{
		Task:      task,
		MsgID:     msg.ID,
		Stream:    msg.Stream,
		StartTime: time.Now(),
		Cancel:    cancel,
	}
	w.runningTasks.Store(task.TaskID, rt)
	atomic.AddInt32(&w.currentTasks, 1)
	defer func() {
		w.runningTasks.Delete(task.TaskID)
		atomic.AddInt32(&w.currentTasks, -1)
	}()

	w.log("info", "开始任务: %s (模式: %s)", task.TaskID, task.Mode)

	// 动态应用 CPU 分配比例：优先取 Redis 控制 key（管理员在界面上可实时调整），
	// 未设置时使用 worker.json 中的配置（默认 50）
	if pct, err := w.redis.GetNodeCPUPercent(w.config.NodeID, w.config.CPUPercent); err == nil {
		w.config.CPUPercent = pct
	}

	if w.onTaskStart != nil {
		w.onTaskStart(task)
	}

	// 更新状态
	// 同时写入任务模式（mode），供后端 Worker 节点界面展示"当前在处理什么"
	w.redis.UpdateTaskStatus(task.TaskID, "running", map[string]interface{}{
		"node_id":    w.config.NodeID,
		"started_at": time.Now().Unix(),
		"lease":      time.Now().Unix(),
		"mode":       task.Mode,
	})

	// 启动取消监听：轮询 Redis 中任务是否被后端标记为 cancelled
	go w.watchCancellation(taskCtx, task.TaskID, cancel)

	// 启动租约续期：周期性刷新任务 lease，防止运行超过 claimLoop 阈值（5 分钟）
	// 的长任务被误判为孤儿重新执行（lease 不刷新是历史双副本/状态污染的真根源）
	go w.leaseRenewal(taskCtx, task.TaskID)

	// 创建临时目录
	taskDir := filepath.Join(w.config.TempDir, task.TaskID)
	os.MkdirAll(taskDir, 0755)
	defer os.RemoveAll(taskDir)

	// 1. 下载素材
	sourcePath := filepath.Join(taskDir, "source.mp4")
	w.emitProgress(task.TaskID, "download", 0, "开始下载素材")
	if err := w.transfer.DownloadFile(taskCtx, task.Source.URL, sourcePath, task.TaskID); err != nil {
		w.handleTaskError(taskCtx, task, msg, fmt.Errorf("下载素材失败: %w", err))
		return
	}
	w.emitProgress(task.TaskID, "download", 100, "素材下载完成")

	// 1.5 下载图片角标（如有），写入本地 path 供引擎叠加
	for i := range task.Badges {
		b := &task.Badges[i]
		if b.URL == "" {
			continue
		}
		badgePath := filepath.Join(taskDir, fmt.Sprintf("badge_%d.png", i))
		if err := w.transfer.DownloadFile(taskCtx, b.URL, badgePath, task.TaskID); err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("下载角标图片失败(%d): %w", i, err))
			return
		}
		b.Path = badgePath
	}

	// 2. 执行切片（引擎内部会解析 PROGRESS 并回调真实进度）
	w.emitProgress(task.TaskID, "ffmpeg", 0, "开始切片")
	outputDir := filepath.Join(taskDir, "output")
	outputs, err := w.executor.ExecuteTask(taskCtx, task, sourcePath, outputDir)
	if err != nil {
		w.handleTaskError(taskCtx, task, msg, fmt.Errorf("切片执行失败: %w", err))
		return
	}
	w.emitProgress(task.TaskID, "ffmpeg", 100, "切片完成")

	// 3. 上传结果（每个文件逐一申请 presigned PUT URL）
	w.emitProgress(task.TaskID, "upload", 0, "开始上传结果")
	var outputFiles []OutputFileInfo
	for i, outputPath := range outputs {
		fileName := filepath.Base(outputPath)

		// 申请精确绑定 object key 的上传 URL
		uploadURL, fileKey, err := w.transfer.GetUploadURL(taskCtx, w.config.BackendURL, task.TaskID, fileName, task.Output.CallbackToken)
		if err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("获取上传URL失败(%s): %w", fileName, err))
			return
		}

		progress := float64(i) / float64(len(outputs)) * 100
		w.emitProgress(task.TaskID, "upload", progress, fmt.Sprintf("上传 %s", fileName))
		if err := w.transfer.UploadFileWithProgress(taskCtx, outputPath, uploadURL, task.TaskID); err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("上传结果失败(%s): %w", fileName, err))
			return
		}

		outputFiles = append(outputFiles, OutputFileInfo{
			FileName: fileName,
			FileKey:  fileKey,
			FileSize: getFileSize(outputPath),
		})
	}
	w.emitProgress(task.TaskID, "upload", 100, "上传完成")

	// 4. ACK确认（成功后才从 PEL 移除）
	if err := w.redis.AckTask(msg.Stream, "workers", msg.ID); err != nil {
		w.log("error", "ACK失败: %v", err)
	}

	// 5. 更新状态到Redis
	w.redis.UpdateTaskStatus(task.TaskID, "completed", map[string]interface{}{
		"completed_at": time.Now().Unix(),
		"output_count": len(outputFiles),
	})
	w.redis.ExpireTaskStatus(task.TaskID, 7*24*time.Hour)
	atomic.AddInt32(&w.totalCompleted, 1)

	// 6. 发送HTTP回调通知后端
	if task.Output.CallbackURL != "" {
		w.callback.SetToken(task.Output.CallbackToken)
		callbackData := &TaskCallback{
			TaskID:      task.TaskID,
			Status:      "completed",
			Outputs:     outputFiles,
			OutputCount: len(outputFiles),
		}
		if err := w.callback.SendCallback(task.Output.CallbackURL, callbackData); err != nil {
			w.log("warn", "回调通知失败: %v", err)
		} else {
			w.log("info", "回调通知成功: %s", task.TaskID)
		}
	}

	w.log("info", "任务完成: %s, 输出: %d 个文件", task.TaskID, len(outputFiles))
	if w.onTaskComplete != nil {
		w.onTaskComplete(task.TaskID, outputs)
	}
}

// handleTaskError 处理任务错误（支持重试）
func (w *Worker) handleTaskError(taskCtx context.Context, task *SliceTask, msg *StreamMessage, err error) {
	w.log("error", "任务失败: %s - %v", task.TaskID, err)

	// 区分取消 / 超时：取消不重试，超时按可重试处理
	if taskCtx.Err() == context.Canceled || strings.Contains(err.Error(), "已取消") {
		w.redis.UpdateTaskStatus(task.TaskID, "cancelled", map[string]interface{}{
			"error":     "任务已取消",
			"failed_at": time.Now().Unix(),
		})
		// cancelled 也设置 TTL，避免历史取消任务的 hash 永久残留
		w.redis.ExpireTaskStatus(task.TaskID, 7*24*time.Hour)
		w.redis.AckTask(msg.Stream, "workers", msg.ID)
		atomic.AddInt32(&w.totalFailed, 1)
		w.sendFailureCallback(task, "任务已取消")
		if w.onTaskError != nil {
			w.onTaskError(task.TaskID, err)
		}
		return
	}

	// 判断是否重试
	if task.RetryCount < w.config.MaxRetries {
		task.RetryCount++
		retryDelay := time.Duration(w.config.RetryDelay) * time.Second
		if retryDelay <= 0 {
			retryDelay = 30 * time.Second
		}

		// 标记任务为 pending 并稍后重新入队
		w.redis.UpdateTaskStatus(task.TaskID, "pending", map[string]interface{}{
			"error":       err.Error(),
			"retry_count": task.RetryCount,
			"retry_at":    time.Now().Add(retryDelay).Unix(),
		})

		w.log("info", "任务 %s 将在 %s 后重试 (第 %d/%d 次)", task.TaskID, retryDelay, task.RetryCount, w.config.MaxRetries)
		time.AfterFunc(retryDelay, func() {
			// 重新发布到 Stream，让任意可用 Worker 消费（携带递增后的重试次数）
			data, mErr := json.Marshal(task)
			if mErr != nil {
				w.log("error", "任务重试序列化失败: %v", mErr)
				return
			}
			if rerr := w.redis.RequeueTask(msg.Stream, string(data)); rerr != nil {
				w.log("error", "任务重试重新入队失败: %v", rerr)
			}
		})
		// 当前消息从 PEL 中 ACK 掉，避免被其他 Worker 重复处理
		w.redis.AckTask(msg.Stream, "workers", msg.ID)
		return
	}

	// 重试耗尽，标记失败
	w.redis.UpdateTaskStatus(task.TaskID, "failed", map[string]interface{}{
		"error":     err.Error(),
		"failed_at": time.Now().Unix(),
	})
	w.redis.ExpireTaskStatus(task.TaskID, 7*24*time.Hour)
	atomic.AddInt32(&w.totalFailed, 1)
	w.sendFailureCallback(task, err.Error())

	// ACK 移除 PEL 中的消息
	if ackErr := w.redis.AckTask(msg.Stream, "workers", msg.ID); ackErr != nil {
		w.log("error", "ACK失败: %v", ackErr)
	}

	if w.onTaskError != nil {
		w.onTaskError(task.TaskID, err)
	}
}

// sendFailureCallback 发送失败回调
func (w *Worker) sendFailureCallback(task *SliceTask, errMsg string) {
	if task.Output.CallbackURL == "" {
		return
	}
	callbackData := &TaskCallback{
		TaskID: task.TaskID,
		Status: "failed",
		Error:  errMsg,
	}
	if cbErr := w.callback.SendCallback(task.Output.CallbackURL, callbackData); cbErr != nil {
		w.log("warn", "失败回调通知错误: %v", cbErr)
	}
}

// watchCancellation 轮询 Redis 任务状态，感知后端取消指令并触发 context 取消
func (w *Worker) watchCancellation(ctx context.Context, taskID string, cancel context.CancelFunc) {
	ticker := time.NewTicker(3 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			cancelled, err := w.redis.IsTaskCancelled(taskID)
			if err != nil {
				continue
			}
			if cancelled {
				w.log("warn", "任务 %s 收到取消信号，终止执行", taskID)
				cancel()
				return
			}
		}
	}
}

// leaseRenewal 周期性刷新运行中任务的租约（lease）。
//
// 背景：claimLoop 以 5 分钟为阈值认领"无租约/租约过期"的任务。若运行中任务
// 不刷新 lease，任何耗时超过 5 分钟的任务（如 vert2horiz 动态跟踪逐帧检测、
// 大视频切片）都会被误判为孤儿重新执行 → 双副本 + 状态污染。
// 此 goroutine 每 30 秒 TouchTask 刷新 lease，taskCtx 结束（完成/取消/超时）即退出。
func (w *Worker) leaseRenewal(ctx context.Context, taskID string) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := w.redis.TouchTask(taskID); err != nil {
				w.log("warn", "任务 %s 租约续期失败: %v", taskID, err)
			}
		}
	}
}

// heartbeatLoop 心跳循环
func (w *Worker) heartbeatLoop(ctx context.Context) {
	ticker := time.NewTicker(time.Duration(w.config.HeartbeatInterval) * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			current := int(atomic.LoadInt32(&w.currentTasks))
			completed := int(atomic.LoadInt32(&w.totalCompleted))
			failed := int(atomic.LoadInt32(&w.totalFailed))
			w.redis.Heartbeat(w.config.NodeID, current, completed, failed, w.engineVersion, w.encoderCapabilities, w.config.HeartbeatTTL())

			// 同时向后端 DB 同步节点数据（双写，保证 Worker 节点界面/数据库有数据）
			if err := w.sendBackendHeartbeat(); err != nil {
				w.log("warn", "后端心跳同步失败: %v", err)
			} else {
				w.log("debug", "后端心跳同步成功")
			}
		}
	}
}

// engineUpdateLoop 引擎更新检查循环。
//
// 服务器端「节点功能」（engines/ 目录中的 slice.py 等脚本）被修改后，管理员在
// 界面点击「推送更新」，后端把目标版本写入 Redis 更新指令
// `slice:node-update:{node_id}`。此循环周期性读取该指令，若目标版本与本地
// 引擎版本不一致，则从后端拉取引擎更新包并替换本地 engines/ 目录，随后更新
// 本地版本、清除指令。整个过程无需重新部署/重启节点。
func (w *Worker) engineUpdateLoop(ctx context.Context) {
	interval := time.Duration(w.config.HeartbeatInterval) * time.Second
	if interval < 5*time.Second {
		interval = 5 * time.Second
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			w.checkEngineUpdate()
		}
	}
}

// checkEngineUpdate 检查并应用一次引擎更新（若服务器下发更新指令）。
func (w *Worker) checkEngineUpdate() {
	// 读取更新指令
	raw, err := w.redis.GetNodeUpdateCommand(w.config.NodeID)
	if err != nil {
		w.log("debug", "读取引擎更新指令失败: %v", err)
		return
	}
	if raw == "" {
		return
	}
	cmd, err := readUpdateCommandJSON(raw)
	if err != nil {
		w.log("warn", "解析引擎更新指令失败: %v", err)
		// 指令格式异常，清除避免反复重试
		w.redis.ClearNodeUpdateCommand(w.config.NodeID)
		return
	}

	// 目标版本与本地一致则无需更新（正常情况下后端推送后本地应用成功即一致）
	if cmd.TargetVersion != "" && cmd.TargetVersion == w.engineVersion {
		// 已是最新，清除指令
		w.redis.ClearNodeUpdateCommand(w.config.NodeID)
		return
	}

	w.log("info", "检测到引擎更新：本地版本 %q → 目标版本 %q，开始拉取更新包", w.engineVersion, cmd.TargetVersion)

	// 拉取并应用更新
	newVersion, err := PullEngineUpdate(w.config.BackendURL, w.config.EnginesPath)
	if err != nil {
		w.log("error", "拉取/应用引擎更新失败: %v", err)
		// 保留指令，下个周期重试
		return
	}

	// 更新本地版本并清除指令
	w.engineVersion = newVersion
	w.redis.ClearNodeUpdateCommand(w.config.NodeID)
	w.log("info", "引擎更新完成：新版本 %s", newVersion)
}

// emitProgress 上报进度（同时写入 Redis，供后端查询真实进度）
func (w *Worker) emitProgress(taskID, phase string, percent float64, detail string) {
	if w.onTaskProgress != nil {
		w.onTaskProgress(taskID, phase, percent, detail)
	}
	w.redis.UpdateTaskStatus(taskID, "running", map[string]interface{}{
		"progress": percent,
		"phase":    phase,
		"lease":    time.Now().Unix(),
	})
}

// matchTags 检查标签匹配
func (w *Worker) matchTags(required []string) bool {
	if len(required) == 0 {
		return true
	}

	tagSet := make(map[string]bool)
	for _, tag := range w.config.Tags {
		tagSet[tag] = true
	}

	for _, req := range required {
		if !tagSet[req] {
			return false
		}
	}
	return true
}

// log 日志
func (w *Worker) log(level, format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	if w.onLog != nil {
		w.onLog(level, msg)
	} else {
		log.Printf("[%s] %s", level, msg)
	}
}

// GetRunningTasks 获取运行中的任务
func (w *Worker) GetRunningTasks() []*RunningTask {
	var tasks []*RunningTask
	w.runningTasks.Range(func(key, value interface{}) bool {
		tasks = append(tasks, value.(*RunningTask))
		return true
	})
	return tasks
}

// CancelTask 取消指定任务（供外部调用，如收到后端取消指令）
func (w *Worker) CancelTask(taskID string) bool {
	if rt, ok := w.runningTasks.Load(taskID); ok {
		running := rt.(*RunningTask)
		if running.Cancel != nil {
			running.Cancel()
			return true
		}
	}
	return false
}

// GetCurrentTaskCount 获取当前任务数
func (w *Worker) GetCurrentTaskCount() int {
	return int(atomic.LoadInt32(&w.currentTasks))
}

// getHostname 获取主机名
func getHostname() string {
	hostname, err := os.Hostname()
	if err != nil {
		return "unknown"
	}
	return hostname
}

// getFileSize 获取文件大小
func getFileSize(path string) int64 {
	if stat, err := os.Stat(path); err == nil {
		return stat.Size()
	}
	return 0
}

// strconvParseInt 简易解析辅助（避免额外导入 strconv 到本文件）
func strconvParseInt(s string) (int64, error) {
	var n int64
	if s == "" {
		return 0, fmt.Errorf("empty")
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("invalid")
		}
		n = n*10 + int64(c-'0')
	}
	return n, nil
}
