package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

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
func (w *Worker) Run(ctx context.Context) error {
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
	}

	if err := w.redis.RegisterNode(nodeInfo, w.config.HeartbeatTTL()); err != nil {
		return fmt.Errorf("注册节点失败: %w", err)
	}
	w.log("info", "节点注册成功: %s", w.config.NodeID)

	// 确保退出时注销
	defer func() {
		w.redis.UnregisterNode(w.config.NodeID, w.config.Tags)
		w.log("info", "节点已注销")
	}()

	// 创建消费者组
	streams := []string{"slice:tasks:high", "slice:tasks:normal", "slice:tasks:low"}
	for _, stream := range streams {
		if err := w.redis.CreateConsumerGroup(stream, "workers"); err != nil {
			w.log("warn", "创建消费者组失败 %s: %v", stream, err)
		}
	}

	// 启动心跳
	go w.heartbeatLoop(ctx)

	// 启动 PEL 恢复（认领崩溃遗留的未完成消息）
	go w.claimLoop(ctx)

	// 主消费循环
	w.log("info", "开始消费任务，最大并发: %d", w.config.MaxConcurrent)
	for {
		select {
		case <-ctx.Done():
			w.log("info", "收到退出信号")
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

// claimLoop 定期从 PEL 认领超时未完成的任务（Worker 崩溃恢复）
func (w *Worker) claimLoop(ctx context.Context) {
	streams := []string{"slice:tasks:high", "slice:tasks:normal", "slice:tasks:low"}
	// 认领阈值：任务进入 PEL 超过 minIdle 且无租约的视为孤儿任务
	minIdle := time.Duration(w.config.HeartbeatInterval) * 3 * time.Second
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
					if time.Now().Unix()-leaseTS < int64(w.config.HeartbeatInterval)*3 {
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
	w.redis.UpdateTaskStatus(task.TaskID, "running", map[string]interface{}{
		"node_id":    w.config.NodeID,
		"started_at": time.Now().Unix(),
		"lease":      time.Now().Unix(),
	})

	// 启动取消监听：轮询 Redis 中任务是否被后端标记为 cancelled
	go w.watchCancellation(taskCtx, task.TaskID, cancel)

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
			w.redis.Heartbeat(w.config.NodeID, current, completed, failed, w.config.HeartbeatTTL())
		}
	}
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
