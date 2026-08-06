package main

import (
	"context"
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
	config     *Config
	redis      *RedisClient
	executor   *TaskExecutor
	transfer   *FileTransfer
	callback   *CallbackService

	// 状态
	currentTasks int32
	runningTasks sync.Map // taskID -> *RunningTask

	// 回调
	onTaskStart   func(task *SliceTask)
	onTaskProgress func(taskID string, phase string, percent float64, detail string)
	onTaskComplete func(taskID string, outputs []string)
	onTaskError   func(taskID string, err error)
	onLog         func(level string, msg string)
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

	// 设置ffmpeg进度回调
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
		NodeID:        w.config.NodeID,
		Hostname:      getHostname(),
		OS:            GetOS(),
		Arch:          GetArch(),
		FFmpegVersion: GetFFmpegVersion(),
		Tags:          w.config.Tags,
		MaxConcurrent: w.config.MaxConcurrent,
		CurrentTasks:  0,
		Status:        "online",
		LastHeartbeat: time.Now().Unix(),
		IP:            GetIP(),
		StartedAt:     time.Now().Unix(),
	}

	if err := w.redis.RegisterNode(nodeInfo); err != nil {
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

	// 主消费循环
	w.log("info", "开始消费任务，最大并发: %d", w.config.MaxConcurrent)
	for {
		select {
		case <-ctx.Done():
			w.log("info", "收到退出信号")
			return nil
		default:
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
				w.redis.RequeueTask(msg.Stream, "workers", msg.ID, msg.RawData)
				continue
			}

			// 启动任务
			go w.runTask(msg)
		}
	}
}

// runTask 执行单个任务
func (w *Worker) runTask(msg *StreamMessage) {
	task := msg.Task
	taskCtx, cancel := context.WithTimeout(context.Background(), time.Duration(task.TimeoutSec)*time.Second)
	defer cancel()

	// 记录运行中的任务
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
	if w.onTaskStart != nil {
		w.onTaskStart(task)
	}

	// 更新状态
	w.redis.UpdateTaskStatus(task.TaskID, "running", map[string]interface{}{
		"node_id":   w.config.NodeID,
		"started_at": time.Now().Unix(),
	})

	// 创建临时目录
	taskDir := filepath.Join(w.config.TempDir, task.TaskID)
	os.MkdirAll(taskDir, 0755)
	defer os.RemoveAll(taskDir)

	// 1. 下载素材
	sourcePath := filepath.Join(taskDir, "source.mp4")
	w.onTaskProgress(task.TaskID, "download", 0, "开始下载素材")
	if err := w.transfer.DownloadFile(task.Source.URL, sourcePath, task.TaskID); err != nil {
		w.handleTaskError(task, msg, fmt.Errorf("下载素材失败: %w", err))
		return
	}
	w.onTaskProgress(task.TaskID, "download", 100, "素材下载完成")

	// 2. 发送ffmpeg进度回调
	w.callback.SendProgressCallback(task.Output.CallbackURL, task.TaskID, 0, "ffmpeg")

	// 3. 执行切片
	outputDir := filepath.Join(taskDir, "output")
	w.onTaskProgress(task.TaskID, "ffmpeg", 0, "开始切片")
	outputs, err := w.executor.ExecuteTask(task, sourcePath, outputDir)
	if err != nil {
		w.handleTaskError(task, msg, fmt.Errorf("切片执行失败: %w", err))
		return
	}
	w.onTaskProgress(task.TaskID, "ffmpeg", 100, "切片完成")
	w.callback.SendProgressCallback(task.Output.CallbackURL, task.TaskID, 50, "ffmpeg")

	// 4. 上传结果
	w.onTaskProgress(task.TaskID, "upload", 0, "开始上传结果")
	for i, outputPath := range outputs {
		fileName := filepath.Base(outputPath)
		// 匹配上传URL
		uploadURL := ""
		for clipName, url := range task.Output.UploadURLs {
			if strings.Contains(fileName, clipName) {
				uploadURL = url
				break
			}
		}
		if uploadURL == "" {
			// 使用通用URL模式
			uploadURL = fmt.Sprintf("%s/%s", task.Output.UploadURLs["default"], fileName)
		}

		progress := float64(i+1) / float64(len(outputs)) * 100
		w.onTaskProgress(task.TaskID, "upload", progress, fmt.Sprintf("上传 %s", fileName))

		if err := w.transfer.UploadFileWithProgress(outputPath, uploadURL, task.TaskID); err != nil {
			w.handleTaskError(task, msg, fmt.Errorf("上传结果失败: %w", err))
			return
		}
	}
	w.onTaskProgress(task.TaskID, "upload", 100, "上传完成")
	w.callback.SendProgressCallback(task.Output.CallbackURL, task.TaskID, 80, "upload")

	// 5. 构建输出文件信息，准备回调
	var outputFiles []OutputFileInfo
	outputPrefix := task.Output.OutputPrefix
	for _, outputPath := range outputs {
		info := BuildOutputFileInfo(outputPath, outputPrefix)
		outputFiles = append(outputFiles, info)
	}

	// 6. ACK确认
	if err := w.redis.AckTask(msg.Stream, "workers", msg.ID); err != nil {
		w.log("error", "ACK失败: %v", err)
	}

	// 7. 更新状态到Redis
	w.redis.UpdateTaskStatus(task.TaskID, "completed", map[string]interface{}{
		"completed_at": time.Now().Unix(),
		"output_count": len(outputs),
	})

	// 8. 发送HTTP回调通知后端
	if task.Output.CallbackURL != "" {
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

	w.log("info", "任务完成: %s, 输出: %d 个文件", task.TaskID, len(outputs))
	if w.onTaskComplete != nil {
		w.onTaskComplete(task.TaskID, outputs)
	}
}

// handleTaskError 处理任务错误
func (w *Worker) handleTaskError(task *SliceTask, msg *StreamMessage, err error) {
	w.log("error", "任务失败: %s - %v", task.TaskID, err)

	w.redis.UpdateTaskStatus(task.TaskID, "failed", map[string]interface{}{
		"error":        err.Error(),
		"failed_at":    time.Now().Unix(),
	})

	// 发送失败回调
	if task.Output.CallbackURL != "" {
		callbackData := &TaskCallback{
			TaskID: task.TaskID,
			Status: "failed",
			Error:  err.Error(),
		}
		if cbErr := w.callback.SendCallback(task.Output.CallbackURL, callbackData); cbErr != nil {
			w.log("warn", "失败回调通知错误: %v", cbErr)
		}
	}

	if w.onTaskError != nil {
		w.onTaskError(task.TaskID, err)
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
			w.redis.Heartbeat(w.config.NodeID, current)
		}
	}
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
