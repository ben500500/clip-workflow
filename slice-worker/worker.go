package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sort"
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
	// 后端心跳响应带回的启停状态（管理员 PATCH 启停节点）。
	// true=启用（可领取任务）；false=停用（暂停领取，保持心跳、当前任务跑完）。
	// 初始视为启用；旧后端/未读到 enabled 字段时保持启用，兼容旧契约。
	backendEnabled atomic.Bool
	// 本节点当前引擎版本（启动时计算，推送更新后原子更新）
	engineVersion string
	// 本节点硬件编码能力（启动时检测一次，供心跳/注册上报；预留 GPU 自动分派接口）
	encoderCapabilities []string
	// 进度整数节流表：key = taskID|phase -> 上次上报的整数百分比（emitProgress 用，
	// 防 transfer 逐 chunk 回调造成 Redis 写放大；LastProgress 心跳不受节流影响）
	progressLast sync.Map
	// 细粒度状态（2026-11-23）：当前百分比 + 最近文案，用于 STAGE 行上报与去抖
	progressNow        sync.Map
	progressDetailLast sync.Map
	// 各任务当前传输方向（download/upload）：transfer 粒度回调下载/上传共用一条，
	// 靠这张表把 phase 标对（下载占任务进度 0-10、上传 95-100，映射见 stagePercent）
	transferPhases sync.Map

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
	// 最近一次进度上报时间戳（Unix 纳秒，原子存储；emitProgress 更新）。
	// 卡死检测据此判断任务是否仍在推进，跨 goroutine 读写无数据竞争。
	LastProgress atomic.Int64
	// 是否被卡死检测强制 kill（区别于用户取消，runTask 据此走重新入队而非置为 cancelled）。
	stuckKilled atomic.Bool
}

// NewWorker 创建Worker
func NewWorker(config *Config, redis *RedisClient) *Worker {
	w := &Worker{
		config:   config,
		redis:    redis,
		executor: NewTaskExecutor(config),
		transfer: NewFileTransfer(),
		callback: NewCallbackService(config.NodeID),
	}
	// 初始视为启用；心跳响应未带 enabled 字段（旧后端）时保持启用
	w.backendEnabled.Store(true)
	return w
}

// setBackendEnabled 记录后端心跳响应带回的启停状态。
func (w *Worker) setBackendEnabled(enabled bool) {
	w.backendEnabled.Store(enabled)
}

// getBackendEnabled 返回当前后端心跳确认的启停状态。
func (w *Worker) getBackendEnabled() bool {
	return w.backendEnabled.Load()
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

	// 设置文件传输进度回调。
	// 2026-11-20 评审修复：此前这里只接 onTaskProgress（--no-tui 下是纯 Printf），
	// 传输/引擎粒度进度根本不进 Redis，前端进度条只停在阶段边界值（0-5% 假死），
	// 且 stuckTaskLoop 的 LastProgress 心跳也不刷新 → 长任务被误杀。改走 emitProgress。
	// phase 按任务当前方向标注（下载/上传共用一条回调，见 transferPhases）。
	w.transfer.SetProgressCallback(func(taskID, fileName string, downloaded, total int64) {
		percent := float64(0)
		if total > 0 {
			percent = float64(downloaded) / float64(total) * 100
		}
		phase := "download"
		if v, ok := w.transferPhases.Load(taskID); ok {
			if s, ok := v.(string); ok {
				phase = s
			}
		}
		w.emitProgress(taskID, phase, percent, fmt.Sprintf("%s: %d/%d", fileName, downloaded, total))
	})

	// 设置引擎进度回调（PROGRESS 行 → 真实进度上报；同上，勿回退到 onTaskProgress）
	w.executor.SetProgressCallback(func(taskID string, percent float64, speed string, eta string) {
		// speed 为空时不覆盖文案（引擎 PROGRESS 行不带 speed，避免「speed=」噪音，
		// 保留最近一条 STAGE 细粒度文案）
		detail := ""
		if speed != "" && speed != "=" {
			detail = fmt.Sprintf("speed=%s", speed)
		}
		w.emitProgress(taskID, "ffmpeg", percent, detail)
	})
	// 引擎细粒度阶段回调（STAGE 行 → 「钩子转码 2/3」「成品 5/10 段切割」等实时文案）
	w.executor.SetStageCallback(func(taskID string, detail string) {
		cur := 0.0
		if p, ok := w.progressNow.Load(taskID); ok {
			cur = p.(float64)
		}
		w.emitProgress(taskID, "ffmpeg", cur, detail)
	})
	// 已出成品数（OUTPUT 行 → redis outputs_done，前端「已出 N/总数」实时展示）
	w.executor.SetOutputDoneCallback(func(taskID string, done int) {
		_ = w.redis.SetOutputsDone(taskID, done)
	})
}

// Run 启动Worker主循环
// checkEngine 启动时对引擎做自检，尽早暴露 Python 版本不兼容
// （引擎要求 Python 3.10+，低版本会抛 str|None TypeError）或引擎文件损坏问题
// ——否则要等第一条任务才会失败，且失败信息容易误导排查。
// 注意：不能用 `python3 -m py_compile`——engines 目录在 163 是只读 bind mount
// （:ro），py_compile 写 __pycache__ 缓存会失败；用 ast.parse 纯读取检查语法。
func (w *Worker) checkEngine() {
	enginePath := filepath.Join(w.config.EnginesPath, "slice.py")
	if _, err := os.Stat(enginePath); err != nil {
		w.log("warn", "引擎文件不存在 %s: %v（将无法处理任务）", enginePath, err)
		return
	}
	py := pythonBinary()
	script := "import sys,ast\n" +
		"if sys.version_info < (3,10):\n" +
		"  sys.stderr.write('Python %d.%d < 3.10, engine requires 3.10+\\n' % sys.version_info[:2]); sys.exit(1)\n" +
		"ast.parse(open(sys.argv[1]).read())\n" +
		"print('Python %d.%d OK' % sys.version_info[:2])"
	cmd := exec.Command(py, "-c", script, enginePath)
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
	w.log("info", "引擎自检通过: %s, 引擎=%s", strings.TrimSpace(string(out)), enginePath)
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

	// 启动卡死任务检测（issue #242 P1）：进度长时间停更的存活任务强制 kill 重投
	go w.stuckTaskLoop(ctx)

	// 专属队列消费与 Pub/Sub 唤醒监听（可选，灰度/回滚时关闭）
	var (
		directCh = make(chan *StreamMessage)
		wakeCh   = make(chan struct{}, 1)
	)
	if w.config.EnableDirectQueue {
		go w.directQueueLoop(ctx, directCh)
		go w.nodeCmdLoop(ctx, wakeCh)
		w.log("info", "节点专属队列已启用（BRPOP 超时 %ds + Pub/Sub 唤醒）", w.config.DirectQueueTimeout)
	}

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
			// 检查节点是否被管理员停用（停用后暂停领取新任务，正在执行的不受影响）。
			// 双源判定：① Redis 控制 key（取任务前直接读，立即生效）；
			// ② 后端心跳响应带回的 enabled（PATCH 后下一次心跳生效，兼容无 Redis 直连的场景）。
			// 任一方判定停用即暂停消费。
			enabled, err := w.redis.IsNodeEnabled(w.config.NodeID)
			if err == nil && !enabled {
				w.log("warn", "节点已被管理员停用（Redis 控制 key），暂停领取新任务")
				time.Sleep(3 * time.Second)
				continue
			}
			if !w.getBackendEnabled() {
				w.log("warn", "节点已被管理员停用（后端心跳响应），暂停领取新任务")
				time.Sleep(3 * time.Second)
				continue
			}
		}

		// 检查并发上限（专属队列与公共池共用 MaxConcurrent 槽位，互不挤占超限）
		if int(atomic.LoadInt32(&w.currentTasks)) >= w.config.MaxConcurrent {
			time.Sleep(500 * time.Millisecond)
			continue
		}

		// 取任务优先级：专属队列（BRPOP）> 公共 Stream（XReadGroup）
		msg := w.fetchNextTask(directCh, wakeCh, streams)
		if msg == nil {
			continue
		}

		// 检查标签匹配
		if !w.matchTags(msg.Task.RequiredTags) {
			w.log("debug", "标签不匹配，重新入队: %s", msg.Task.TaskID)
			w.requeue(msg)
			continue
		}

		// 启动任务
		go w.runTask(msg)
	}
}

// fetchNextTask 按「专属队列优先、公共池回落」的规则取一条任务。
//
//   - directCh：专属队列消费 goroutine（BRPOP）投递
//   - wakeCh：Pub/Sub 唤醒信号，收到后立即非阻塞取一次专属队列
//   - 两者皆无且专属队列为空时，回落公共 Stream（XReadGroup，1s 超时）
func (w *Worker) fetchNextTask(directCh <-chan *StreamMessage, wakeCh <-chan struct{}, streams []string) *StreamMessage {
	if w.config.EnableDirectQueue {
		select {
		case msg := <-directCh:
			return msg
		case <-wakeCh:
			// 唤醒即取：立即非阻塞取一次专属队列，实现毫秒级感知
			if msg, err := w.redis.FetchDirectTaskNow(w.config.NodeID); err == nil && msg != nil {
				return msg
			}
			// 唤醒时队列已被 BRPOP 取走或确实为空：不回落公共池，等下轮 directCh 投递
			return nil
		default:
			// 专属队列空 → 回落公共池
		}
	}

	msg, err := w.redis.FetchTask(streams, "workers", w.config.NodeID, 1*time.Second)
	if err != nil {
		w.log("error", "获取任务失败: %v", err)
		time.Sleep(1 * time.Second)
		return nil
	}
	return msg
}

// directQueueLoop 专属队列消费 goroutine：BRPOP 阻塞取任务，队列空时最多阻塞
// DirectQueueTimeout 秒再进入下一轮，作为 Pub/Sub 唤醒丢失时的兜底。
func (w *Worker) directQueueLoop(ctx context.Context, out chan<- *StreamMessage) {
	timeout := time.Duration(w.config.DirectQueueTimeout) * time.Second
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		msg, err := w.redis.FetchDirectTask(w.config.NodeID, timeout)
		if err != nil {
			w.log("error", "专属队列取任务失败: %v", err)
			// 出错时短睡，避免 Redis 抖动时忙轮询
			time.Sleep(500 * time.Millisecond)
			continue
		}
		if msg == nil {
			continue
		}
		select {
		case out <- msg:
		case <-ctx.Done():
			return
		}
	}
}

// nodeCmdLoop 订阅节点指令通道，把 wake 唤醒信号转发到 wakeCh（尽力而为）。
// 唤醒丢失不影响任务送达：专属队列的 BRPOP 短超时轮询作为兜底。
func (w *Worker) nodeCmdLoop(ctx context.Context, wake chan<- struct{}) {
	ch, ps, err := w.redis.SubscribeNodeCmd(w.config.NodeID)
	if err != nil {
		w.log("warn", "订阅节点指令通道失败（唤醒不可用，BRPOP 兜底）: %v", err)
		return
	}
	defer ps.Close()

	for {
		select {
		case <-ctx.Done():
			return
		case payload, ok := <-ch:
			if !ok {
				return // 通道已关闭
			}
			var cmd struct {
				Type string `json:"type"`
			}
			if err := json.Unmarshal([]byte(payload), &cmd); err != nil || cmd.Type != "wake" {
				continue
			}
			// 非阻塞投递唤醒信号（channel 已满说明已有待处理唤醒，丢弃即可）
			select {
			case wake <- struct{}{}:
			default:
			}
		}
	}
}

// requeue 任务标签不匹配时按来源放回：专属队列任务回本节点队尾，公共 Stream 任务 XAdd 回原流。
func (w *Worker) requeue(msg *StreamMessage) {
	if msg.Stream == "direct" {
		if err := w.redis.RequeueDirectTask(w.config.NodeID, msg.RawData); err != nil {
			w.log("error", "专属队列任务重新入队失败: %v", err)
		}
		return
	}
	if err := w.redis.RequeueTask(msg.Stream, msg.RawData); err != nil {
		w.log("error", "任务重新入队失败: %v", err)
	}
}

// cleanupOrphanDirs 启动时清理孤儿临时目录。
//
// 场景：worker 被强杀（如 docker compose --force-recreate 或 OOM）时，正在处理的
// 任务进程被 SIGKILL，runTask 的 defer 清理未执行，任务目录（含下载的源视频、
// 中间文件）残留。重启后这些消息会被幂等检测跳过（终态直接 ACK），不再触发清理，
// 需要在此兜底。
//
// TempDir 为多 worker 共享卷，每个 worker 的任务目录都在自己的
// TempDir/{node_id}/ 子目录下（见 runTask）：本函数只扫描本节点的子目录，
// 绝不触碰其他节点正在使用的目录。对每个 UUID 任务目录查 redis 任务状态，
// 仅当「无对应任务 / 任务已终态」时才清理；running/pending 的目录必须跳过。
func (w *Worker) cleanupOrphanDirs() {
	nodeRoot := filepath.Join(w.config.TempDir, w.config.NodeID)
	entries, err := os.ReadDir(nodeRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return
		}
		w.log("warn", "扫描临时目录失败: %v", err)
		return
	}
	removed := 0
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		dir := filepath.Join(nodeRoot, name)
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

	// 启动时立即做一次 PEL 恢复 + pending 可观测日志：
	// Worker 刚重启（或从 crash 恢复）时，上一次会话遗留的 PEL 消息需要尽快认领，
	// 否则会永久卡 pending（本 issue P1 背景）。先跑一次再进入周期循环。
	w.claimOnce(streams, minIdle, true)

	ticker := time.NewTicker(minIdle)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			w.claimOnce(streams, minIdle, false)
		}
	}
}

// claimOnce 执行一次 PEL 认领（XAUTOCLAIM）。
// startup 为 true 时额外输出 pending 数量/消息 ID 日志，满足「Worker 启动时对
// pending 消息做 XAUTOCLAIM/至少打日志提示」的可观测要求。
func (w *Worker) claimOnce(streams []string, minIdle time.Duration, startup bool) {
	claimed, err := w.redis.ClaimStaleTasks(streams, "workers", w.config.NodeID, minIdle)
	if err != nil {
		w.log("error", "PEL 认领失败: %v", err)
		return
	}
	if startup {
		// 启动时即使无可认领任务也输出 pending 概况，便于排查「消息卡 PEL」问题
		w.logPendingOverview(streams)
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

// logPendingOverview 输出本节点 consumer 在 PEL 中的 pending 消息概况（可观测）。
func (w *Worker) logPendingOverview(streams []string) {
	for _, stream := range streams {
		p, err := w.redis.PendingOverview(stream, "workers", w.config.NodeID)
		if err != nil {
			w.log("debug", "查询 %s pending 概况失败: %v", stream, err)
			continue
		}
		if p > 0 {
			w.log("warn", "启动时检测到本节点在 %s 的 PEL 有 %d 条 pending 消息（将 XAUTOCLAIM 认领）", stream, p)
		} else {
			w.log("info", "启动时 %s PEL 无 pending 消息", stream)
		}
	}
}

// stuckTaskLoop 卡死任务检测（issue #242 P1）。
//
// 背景：worker 进程活着但某任务卡死（如 ffmpeg 挂起），此时消费者未断开，
// XAutoClaim 不会认领（它只认领 idle 过久且租约过期的 PEL 消息），任务会永久
// running。这里在本节点内存里跟踪每个运行任务的最近进度时间戳（emitProgress 刷新，
// 与 claimLoop 用的 Redis lease 解耦——leaseRenewal 每 30s 无条件续期会掩盖挂起），
// 若某存活任务的进度停更超过阈值，则强制 kill 引擎进程树并重新入队，释放 worker 槽位。
func (w *Worker) stuckTaskLoop(ctx context.Context) {
	minutes := w.config.StuckTaskMinutes
	if minutes <= 0 {
		w.log("info", "卡死任务检测已禁用（stuck_task_minutes=0）")
		return
	}
	stuckAfter := time.Duration(minutes) * time.Minute
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			w.runningTasks.Range(func(key, value interface{}) bool {
				rt := value.(*RunningTask)
				// 已被卡死 kill 正在清理/重投的任务不再重复处理
				if rt.stuckKilled.Load() {
					return true
				}
				if time.Since(time.Unix(0, rt.LastProgress.Load())) < stuckAfter {
					return true // 仍在推进，跳过
				}
				w.log("warn", "检测到卡死任务: %s（进度已停更 %s），强制 kill 并重投",
					rt.Task.TaskID, time.Since(time.Unix(0, rt.LastProgress.Load())).Round(time.Minute))
				rt.stuckKilled.Store(true)
				// 取消 context（exec.CommandContext 会杀掉引擎进程树）。
				// 重新入队在 runTask 退出时（handleTaskError 识别 stuckKilled）统一执行，
				// 避免与旧 runTask 的清理/去重产生竞态，也不会丢重投消息。
				rt.Cancel()
				return true
			})
		}
	}
}

// requeueStuckTask 卡死任务重新入队：向原 Stream 重新投递一份，并把当前 PEL 消息 ACK 掉，
// 避免残留。runTask 随后的退出路径会识别 stuckKilled，走重投清理而非置为 cancelled。
// 重投次数受 MaxRetries 限制：反复卡死的任务重投耗尽后直接置为 failed，避免无限循环。
func (w *Worker) requeueStuckTask(rt *RunningTask) {
	if rt == nil || rt.Task == nil {
		return
	}
	taskID := rt.Task.TaskID
	// 递增重投次数（用任务自身的 RetryCount，随重投消息透传，跨次累加），
	// 超过 MaxRetries 则直接置为 failed，避免反复卡死的任务无限循环重投
	rt.Task.RetryCount++
	if rt.Task.RetryCount > w.config.MaxRetries {
		w.log("error", "卡死任务 %s 重投次数耗尽（%d 次），标记失败", taskID, w.config.MaxRetries)
		w.redis.UpdateTaskStatus(taskID, "failed", map[string]interface{}{
			"error":     "任务反复卡死，重投次数耗尽",
			"failed_at": time.Now().Unix(),
		})
		w.redis.ExpireTaskStatus(taskID, 7*24*time.Hour)
		// ACK 掉当前 PEL 消息，避免残留
		w.redis.AckTask(rt.Stream, "workers", rt.MsgID)
		return
	}

	data, err := json.Marshal(rt.Task)
	if err != nil {
		w.log("error", "卡死任务重投序列化失败: %v", err)
		return
	}
	// 任务 hash 置为 pending，避免被误判为终态
	w.redis.UpdateTaskStatus(taskID, "pending", map[string]interface{}{
		"error":    "卡死任务被强制重投",
		"retry_at": time.Now().Unix(),
	})
	// direct 队列任务（服务器指定派发）重投必须压回节点专属 LIST：
	// rt.Stream == "direct" 是 buildDirectMessage 的合成标记（无对应消费流），
	// 此前 RequeueTask 直接 XADD 到名为 "direct" 的 Stream —— 没有任何消费者
	// 读它，任务从此永久 pending（2026-11-21 实测踩中：0f08daa1 二次卡死后
	// 悬挂 6 分钟无人认领）。
	if rt.Stream == "direct" {
		nodeID := rt.Task.TargetNodeID
		if nodeID == "" {
			nodeID = w.config.NodeID // 目标节点缺失时回退当前节点，至少不丢任务
		}
		if err := w.redis.RequeueDirectTask(nodeID, string(data)); err != nil {
			w.log("error", "卡死任务重投入队失败(direct→%s): %v", nodeID, err)
			return
		}
		w.log("info", "卡死任务 %s 已重投到节点 %s 专属队列（第 %d 次重试）", taskID, nodeID, rt.Task.RetryCount)
		return
	}
	if err := w.redis.RequeueTask(rt.Stream, string(data)); err != nil {
		w.log("error", "卡死任务重投入队失败: %v", err)
		return
	}
	// ACK 掉当前 PEL 消息，让重投的那份成为唯一在途任务
	if err := w.redis.AckTask(rt.Stream, "workers", rt.MsgID); err != nil {
		w.log("error", "卡死任务 PEL ACK 失败: %v", err)
	}
}

// runTask 执行单个任务
func (w *Worker) runTask(msg *StreamMessage) {
	task := msg.Task

	// 去重：若任务已在运行中则跳过
	if _, exists := w.runningTasks.Load(task.TaskID); exists {
		return
	}

	// 幂等：若任务已达终态（completed/failed/cancelled），直接确认跳过，
	// 避免残留消息被重复执行导致状态被污染（已完成的成品不重复生成）。
	if hash, err := w.redis.GetTaskHash(task.TaskID); err == nil {
		if st := hash["status"]; st == "completed" || st == "failed" || st == "cancelled" {
			w.log("info", "任务 %s 已处于终态(%s)，跳过重复执行", task.TaskID, st)
			w.ackMessage(msg)
			return
		}
	}

	// 跨节点原子认领：同一任务只允许一个 Worker 处理。
	// 背景：任务可能因 PEL 认领（XAUTOCLAIM）或重复入队被两个 Worker 同时拿到，
	// 历史实现各自在共享 TempDir 下写同一 taskID 目录导致互相覆盖/误删（临时目录消失）。
	// 这里用 Redis SETNX 租约做互斥：认领成功才真正开工，失败说明已被其他节点处理，
	// 直接 ACK 掉本副本避免重复执行；租约由 leaseRenewal 周期续期，崩溃后自动过期可接管。
	leaseTTL := time.Duration(task.TimeoutSec) * time.Second
	if leaseTTL <= 0 {
		leaseTTL = time.Duration(w.config.TaskTimeout) * time.Second
	}
	if leaseTTL < 10*time.Minute {
		leaseTTL = 10 * time.Minute
	}
	acquired, err := w.redis.TryAcquireTaskLease(task.TaskID, w.config.NodeID, leaseTTL)
	if err != nil {
		// 认领异常保守放行（Redis 抖动时不阻塞任务，仍有下方租约续期兜底）
		w.log("warn", "任务 %s 认领异常: %v", task.TaskID, err)
	} else if !acquired {
		w.log("warn", "任务 %s 正被其他节点处理，跳过本副本并 ACK", task.TaskID)
		if ackErr := w.redis.AckTask(msg.Stream, "workers", msg.ID); ackErr != nil {
			w.log("error", "任务 %s 重复副本 ACK 失败: %v", task.TaskID, ackErr)
		}
		return
	}

	timeout := time.Duration(task.TimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = time.Duration(w.config.TaskTimeout) * time.Second
	}
	taskCtx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	// 任务退出（完成/失败/取消/超时）时释放认领租约，允许后续重试或其他节点接管
	defer w.redis.ReleaseTaskLease(task.TaskID, w.config.NodeID)

	// 记录运行中的任务（Cancel 可在取消接口中调用）
	rt := &RunningTask{
		Task:      task,
		MsgID:     msg.ID,
		Stream:    msg.Stream,
		StartTime: time.Now(),
		Cancel:    cancel,
	}
	rt.LastProgress.Store(time.Now().UnixNano())
	w.runningTasks.Store(task.TaskID, rt)
	atomic.AddInt32(&w.currentTasks, 1)
	defer func() {
		// 仅删除/递减当前这个 rt（卡死重投时旧 rt 已在 handleTaskError 中先被清理，
		// 这里通过指针一致性避免误删新 runTask 存入的同 TaskID 记录）。
		if cur, ok := w.runningTasks.Load(task.TaskID); ok && cur == rt {
			w.runningTasks.Delete(task.TaskID)
			atomic.AddInt32(&w.currentTasks, -1)
		}
		// 清理本任务的进度节流表与传输方向标注（防长生命周期 worker 内存缓涨）
		w.progressLast.Range(func(k, _ interface{}) bool {
			if ks, ok := k.(string); ok && strings.HasPrefix(ks, task.TaskID+"|") {
				w.progressLast.Delete(k)
			}
			return true
		})
		w.transferPhases.Delete(task.TaskID)
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
	// 目录按 node_id 隔离（TempDir/{node_id}/{task_id}）：即使同一任务被两个 Worker
	// 同时认领（如 PEL 重复），各自在独立目录下载/切片，互不覆盖、互不误删。
	taskDir := filepath.Join(w.config.TempDir, w.config.NodeID, task.TaskID)
	os.MkdirAll(taskDir, 0755)
	defer os.RemoveAll(taskDir)

	// 1. 下载素材（断点续传优化：重启后 source.mp4 若已存在则直接复用，避免重复下载）
	sourcePath := filepath.Join(taskDir, "source.mp4")
	if _, statErr := os.Stat(sourcePath); statErr != nil {
		w.transferPhases.Store(task.TaskID, "download")
		w.emitProgress(task.TaskID, "download", 0, "开始下载素材")
		if err := w.transfer.DownloadFile(taskCtx, task.Source.URL, sourcePath, task.TaskID); err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("下载素材失败: %w", err))
			return
		}
	} else {
		w.log("info", "断点续传: 任务 %s 复用已存在素材", task.TaskID)
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

	// 1.6 下载视频封面（如有），写入本地 path 供引擎作为视频首帧叠加
	if task.Cover.URL != "" {
		// presigned URL 带签名查询参数（?X-Amz-...），直接 filepath.Ext(URL) 会把查询串
		// 带进扩展名（如 cover.png?X-Amz-Algorithm=...）→ 文件名超长 file name too long。
		// 先解析 URL 取 Path 再取扩展名。
		coverExt := ".jpg"
		if u, err := url.Parse(task.Cover.URL); err == nil && u.Path != "" {
			if e := filepath.Ext(u.Path); e != "" {
				coverExt = e
			}
		}
		coverPath := filepath.Join(taskDir, "cover"+coverExt)
		if err := w.transfer.DownloadFile(taskCtx, task.Cover.URL, coverPath, task.TaskID); err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("下载封面图片失败: %w", err))
			return
		}
		task.Cover.Path = coverPath
	}

	// 1.7 下载钩子视频（如有），写入本地 path 供引擎作为片头拼接（[封面][钩子][本体]）。
	// 支持文件夹方式（多个钩子），全部下载，引擎每个成品切片按顺序循环取一个。
	for i := range task.Hooks {
		if task.Hooks[i].URL == "" {
			continue
		}
		// presigned URL 带签名查询参数，先解析 URL 取 Path 再取扩展名。
		hookExt := ".mp4"
		if u, err := url.Parse(task.Hooks[i].URL); err == nil && u.Path != "" {
			if e := filepath.Ext(u.Path); e != "" {
				hookExt = e
			}
		}
		hookPath := filepath.Join(taskDir, fmt.Sprintf("hook_%d%s", i, hookExt))
		if err := w.transfer.DownloadFile(taskCtx, task.Hooks[i].URL, hookPath, task.TaskID); err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("下载钩子视频失败: %w", err))
			return
		}
		task.Hooks[i].Path = hookPath
	}

	// 1.8 下载片尾视频（如有），写入本地 path 供引擎拼接到每个成品末尾（[...][本体][片尾]）
	if task.Outro.URL != "" {
		outroExt := ".mp4"
		if u, err := url.Parse(task.Outro.URL); err == nil && u.Path != "" {
			if e := filepath.Ext(u.Path); e != "" {
				outroExt = e
			}
		}
		outroPath := filepath.Join(taskDir, "outro"+outroExt)
		if err := w.transfer.DownloadFile(taskCtx, task.Outro.URL, outroPath, task.TaskID); err != nil {
			w.handleTaskError(taskCtx, task, msg, fmt.Errorf("下载片尾视频失败: %w", err))
			return
		}
		task.Outro.Path = outroPath
	}

	// 2. 执行切片（引擎内部会解析 PROGRESS 并回调真实进度）
	w.emitProgress(task.TaskID, "ffmpeg", 0, "开始切片")
	outputDir := filepath.Join(taskDir, "output")
	outputs, err := w.executor.ExecuteTask(taskCtx, task, sourcePath, outputDir)
	if err != nil {
		// 失败保留已出成品（2026-11-24 用户需求）：引擎失败/超时/取消前已完整产出
		// 的成品随错误带回（outputs 非空时），最终失败/取消路径会上传入库，
		// 不随失败丢弃；若走 worker 内自动重试则不重复上传（断点续传接着跑）。
		w.handleTaskError(taskCtx, task, msg, fmt.Errorf("切片执行失败: %w", err), outputs)
		return
	}
	w.emitProgress(task.TaskID, "ffmpeg", 100, "切片完成")

	// 3. 上传结果（3 路并发：预签名 URL 申请 + PUT 上传）。
	// 2026-11-20 评审：100 成品串行上传尾延迟 2-3 分钟，3 路并发内网千兆足够吃满；
	// 进度按「完成数」原子推进（并发下序号 i 不再等于完成序），首错快速失败。
	w.transferPhases.Store(task.TaskID, "upload")
	w.emitProgress(task.TaskID, "upload", 0, "开始上传结果")
	uploadCtx, uploadCancel := context.WithCancel(taskCtx)
	defer uploadCancel()
	outputFiles := make([]OutputFileInfo, len(outputs))
	var uploadWG sync.WaitGroup
	uploadSem := make(chan struct{}, 3) // 并发上限：3 路
	var uploadedCount int32
	var uploadErrMu sync.Mutex
	var uploadErr error
	for i, outputPath := range outputs {
		uploadWG.Add(1)
		go func(idx int, path string) {
			defer uploadWG.Done()
			uploadSem <- struct{}{}
			defer func() { <-uploadSem }()

			uploadErrMu.Lock()
			abort := uploadErr != nil
			uploadErrMu.Unlock()
			if abort {
				return
			}
			select {
			case <-uploadCtx.Done():
				return
			default:
			}

			fileName := filepath.Base(path)

			// 申请精确绑定 object key 的上传 URL
			uploadURL, fileKey, err := w.transfer.GetUploadURL(uploadCtx, w.config.BackendURL, task.TaskID, fileName, task.Output.CallbackToken)
			if err != nil {
				uploadErrMu.Lock()
				if uploadErr == nil {
					uploadErr = fmt.Errorf("获取上传URL失败(%s): %w", fileName, err)
					uploadCancel()
				}
				uploadErrMu.Unlock()
				return
			}

			if err := w.transfer.UploadFileWithProgress(uploadCtx, path, uploadURL, task.TaskID); err != nil {
				uploadErrMu.Lock()
				if uploadErr == nil {
					uploadErr = fmt.Errorf("上传结果失败(%s): %w", fileName, err)
					uploadCancel()
				}
				uploadErrMu.Unlock()
				return
			}

			outputFiles[idx] = OutputFileInfo{
				FileName: fileName,
				FileKey:  fileKey,
				FileSize: getFileSize(path),
			}
			n := atomic.AddInt32(&uploadedCount, 1)
			w.emitProgress(task.TaskID, "upload", float64(n)/float64(len(outputs))*100, fmt.Sprintf("上传 %d/%d：%s", n, len(outputs), fileName))
		}(i, outputPath)
	}
	uploadWG.Wait()
	if uploadErr != nil {
		w.handleTaskError(taskCtx, task, msg, uploadErr)
		return
	}
	// 2026-11-21 架构复评：取消恰好落在所有 goroutine 开工前时，全部走 ctx 早退、
	// uploadErr 为 nil——若不复查会带零值 outputFiles 走 completed（假完成）。
	if int(atomic.LoadInt32(&uploadedCount)) < len(outputs) {
		w.handleTaskError(taskCtx, task, msg, fmt.Errorf("上传在任务取消/中止时未完成 (%d/%d)", uploadedCount, len(outputs)))
		return
	}
	w.emitProgress(task.TaskID, "upload", 100, "上传完成")

	// 4. 确认完成（Stream 消息从 PEL 移除；专属队列消息取出即确认，无需处理）
	w.ackMessage(msg)

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
func (w *Worker) handleTaskError(taskCtx context.Context, task *SliceTask, msg *StreamMessage, err error, partialOutputs ...[]string) {
	w.log("error", "任务失败: %s - %v", task.TaskID, err)

	// 卡死检测强制 kill：任务已超时无进度，runTask 即将退出。这里先清理 runningTasks
	// （删除当前 rt + 递减并发槽，先于重投执行，避免新 runTask 的同 TaskID 去重误跳），
	// 再重新入队，当前 PEL 消息由 requeueStuckTask 一并 ACK。
	if rt, ok := w.runningTasks.Load(task.TaskID); ok && rt.(*RunningTask).stuckKilled.Load() {
		w.log("warn", "任务 %s 因卡死被强制终止，重新入队", task.TaskID)
		w.runningTasks.Delete(task.TaskID)
		atomic.AddInt32(&w.currentTasks, -1)
		w.requeueStuckTask(rt.(*RunningTask))
		return
	}

	// 失败保留已出成品：终态（取消/重试耗尽）时把已完整产出的成品上传入库；
	// 走自动重试分支则不上传（断点续传接着跑，避免重复上传）。

	// 区分取消 / 超时：取消不重试，超时按可重试处理
	if taskCtx.Err() == context.Canceled || strings.Contains(err.Error(), "已取消") {
		keptOutputs := w.uploadPartialOutputs(task, firstOutputs(partialOutputs))
		w.redis.UpdateTaskStatus(task.TaskID, "cancelled", map[string]interface{}{
			"error":     "任务已取消",
			"failed_at": time.Now().Unix(),
		})
		// cancelled 也设置 TTL，避免历史取消任务的 hash 永久残留
		w.redis.ExpireTaskStatus(task.TaskID, 7*24*time.Hour)
		w.ackMessage(msg)
		atomic.AddInt32(&w.totalFailed, 1)
		w.sendFailureCallback(task, "任务已取消", keptOutputs)
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
			// 重新发布：专属队列任务回本节点队尾，公共 Stream 任务 XAdd 回原流
			data, mErr := json.Marshal(task)
			if mErr != nil {
				w.log("error", "任务重试序列化失败: %v", mErr)
				return
			}
			if msg.Stream == "direct" {
				if rerr := w.redis.RequeueDirectTask(w.config.NodeID, string(data)); rerr != nil {
					w.log("error", "专属队列任务重试重新入队失败: %v", rerr)
				}
				return
			}
			if rerr := w.redis.RequeueTask(msg.Stream, string(data)); rerr != nil {
				w.log("error", "任务重试重新入队失败: %v", rerr)
			}
		})
		// 当前消息从 PEL 中确认掉（专属队列消息取出即确认，无需处理）
		w.ackMessage(msg)
		return
	}

	// 重试耗尽，标记失败
	keptOutputs := w.uploadPartialOutputs(task, firstOutputs(partialOutputs))
	w.redis.UpdateTaskStatus(task.TaskID, "failed", map[string]interface{}{
		"error":     err.Error(),
		"failed_at": time.Now().Unix(),
	})
	w.redis.ExpireTaskStatus(task.TaskID, 7*24*time.Hour)
	atomic.AddInt32(&w.totalFailed, 1)
	w.sendFailureCallback(task, err.Error(), keptOutputs)

	// 确认移除 PEL 中的消息（专属队列消息取出即确认，无需处理）
	w.ackMessage(msg)

	if w.onTaskError != nil {
		w.onTaskError(task.TaskID, err)
	}
}

// ackMessage 确认任务消息：公共 Stream 消息 XAck（从 PEL 移除），专属队列消息
// 在 BRPOP/LPOP 弹出时即已确认删除，这里无操作。
func (w *Worker) ackMessage(msg *StreamMessage) {
	if msg == nil || msg.Stream == "direct" {
		return
	}
	if err := w.redis.AckTask(msg.Stream, "workers", msg.ID); err != nil {
		w.log("error", "ACK失败: %v", err)
	}
}

// sendFailureCallback 发送失败回调（失败保留：keptOutputs 非空时一并上报，
// 后端入库为失败任务的可下载成品）
func (w *Worker) sendFailureCallback(task *SliceTask, errMsg string, keptOutputs ...[]OutputFileInfo) {
	if task.Output.CallbackURL == "" {
		return
	}
	// 失败回调同样要带 Worker Token：成功回调路径在发送前显式 SetToken，
	// 这里必须补上——否则全新 worker 进程（未发过成功回调）token 为空，
	// 后端 401 拒收，失败保留的成品入库会静默丢失（2026-11-24 实测踩中）。
	w.callback.SetToken(task.Output.CallbackToken)
	callbackData := &TaskCallback{
		TaskID: task.TaskID,
		Status: "failed",
		Error:  errMsg,
		// 显式空数组而非 nil：nil slice 序列化成 null，后端 pydantic
		// outputs: list[dict] 会以 422 list_type 拒收整条失败回调
		// （2026-11-24 三机实测：无保留成品的失败回调全部 422 丢失）
		Outputs: make([]OutputFileInfo, 0),
	}
	if kept := firstFileInfo(keptOutputs); len(kept) > 0 {
		callbackData.Outputs = kept
		callbackData.OutputCount = len(kept)
	}
	if cbErr := w.callback.SendCallback(task.Output.CallbackURL, callbackData); cbErr != nil {
		w.log("warn", "失败回调通知错误: %v", cbErr)
	}
}

// firstOutputs 取可变参数里的第一个非空路径列表（无则 nil）。
func firstOutputs(lists [][]string) []string {
	for _, l := range lists {
		if len(l) > 0 {
			return l
		}
	}
	return nil
}

// firstFileInfo 取可变参数里的第一个非空文件信息列表（无则 nil）。
func firstFileInfo(lists [][]OutputFileInfo) []OutputFileInfo {
	for _, l := range lists {
		if len(l) > 0 {
			return l
		}
	}
	return nil
}

// uploadPartialOutputs 失败保留：逐个 best-effort 上传已完整产出的成品，
// 返回成功上传的文件信息。上传失败只记日志不阻断失败回调（成品文件仍留在
// 任务目录，断点续传重跑时可复用）。
func (w *Worker) uploadPartialOutputs(task *SliceTask, paths []string) []OutputFileInfo {
	if len(paths) == 0 || task.Output.CallbackURL == "" {
		return nil
	}
	w.log("info", "任务 %s 失败保留: 开始上传 %d 个已出成品", task.TaskID, len(paths))
	ctx := context.Background()
	var kept []OutputFileInfo
	for _, path := range paths {
		fileName := filepath.Base(path)
		uploadURL, fileKey, err := w.transfer.GetUploadURL(ctx, w.config.BackendURL, task.TaskID, fileName, task.Output.CallbackToken)
		if err != nil {
			w.log("warn", "失败保留上传URL失败(%s): %v", fileName, err)
			continue
		}
		if err := w.transfer.UploadFileWithProgress(ctx, path, uploadURL, task.TaskID); err != nil {
			w.log("warn", "失败保留上传失败(%s): %v", fileName, err)
			continue
		}
		kept = append(kept, OutputFileInfo{
			FileName: fileName,
			FileKey:  fileKey,
			FileSize: getFileSize(path),
		})
	}
	if len(kept) > 0 {
		w.log("info", "任务 %s 失败保留: 已上传 %d/%d 个成品", task.TaskID, len(kept), len(paths))
	}
	return kept
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
	// 认领租约 TTL 与任务超时对齐（runTask 里认领时用的同一值），续期期间保持新鲜
	ttl := time.Duration(w.config.TaskTimeout) * time.Second
	if ttl < 10*time.Minute {
		ttl = 10 * time.Minute
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := w.redis.TouchTask(taskID); err != nil {
				w.log("warn", "任务 %s 租约续期失败: %v", taskID, err)
			}
			// 同步刷新跨节点认领租约：若租约已被其他节点接管（如本节点长时间暂停），
			// RefreshTaskLease 返回 false，说明本节点不应继续处理，放弃执行
			if ok, rerr := w.redis.RefreshTaskLease(taskID, w.config.NodeID, ttl); rerr != nil {
				w.log("warn", "任务 %s 认领租约续期失败: %v", taskID, rerr)
			} else if !ok {
				w.log("warn", "任务 %s 认领租约已被其他节点接管，终止本副本", taskID)
				if rt, exists := w.runningTasks.Load(taskID); exists {
					if rt.(*RunningTask).Cancel != nil {
						rt.(*RunningTask).Cancel()
					}
				}
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

// stagePercent 把各阶段原始 0-100 百分比映射为「任务级」单调百分比：
// 下载/传输 0-10、切片(ffmpeg，引擎任务级 0-100) 10-95、上传 95-100。
// 背景（2026-11-20 评审）：后端进度回写用 max() 防回退，各阶段各自 0-100 会互相
// 粘滞（素材下载到 100% 后切片阶段永远停在 100%）；映射成单调区间后进度条全程可读。
func stagePercent(phase string, percent float64) float64 {
	switch phase {
	case "download", "transfer":
		return percent * 0.10
	case "upload":
		return 95.0 + percent*0.05
	default: // ffmpeg 及其它
		return 10.0 + percent*0.85
	}
}

// emitProgress 上报进度（写入 Redis 供后端查询真实进度 + 刷新卡死检测心跳）。
// 2026-11-20 评审改造：
//  1. 百分比经 stagePercent 映射为任务级单调值；
//  2. 整数百分比节流：未跨档时只 TouchLease 续约（防 transfer 逐 chunk 写放大），
//     但 LastProgress 心跳无条件刷新——同一档位内的细分打点（引擎阶段 tick）
//     仍能证明「任务在推进」，避免 stuckTaskLoop 误杀；
//  3. 引擎/传输回调统一从 SetCallbacks 接到这里（此前 --no-tui 下只进 Printf）。
func (w *Worker) emitProgress(taskID, phase string, percent float64, detail string) {
	// 日志回调：保留原始百分比，便于日志与引擎输出对表
	if w.onTaskProgress != nil {
		w.onTaskProgress(taskID, phase, percent, detail)
	}
	// 心跳：无条件刷新卡死检测时间戳（优先级最高，任何进度行都证明"仍在推进"）
	if rt, ok := w.runningTasks.Load(taskID); ok {
		rt.(*RunningTask).LastProgress.Store(time.Now().UnixNano())
	}
	staged := stagePercent(phase, percent)
	key := taskID + "|" + phase
	pct := int(staged)
	// 记录当前百分比（STAGE 行上报细粒度文案时需要）
	w.progressNow.Store(taskID, staged)
	prevDetail := ""
	if d, ok := w.progressDetailLast.Load(taskID); ok {
		prevDetail = d.(string)
	}
	if prev, ok := w.progressLast.Load(key); ok && prev.(int) == pct && prevDetail == detail {
		// 百分比与文案都未变化：轻量续 lease（TouchTask 只 HSet lease 字段），跳过完整状态写
		_ = w.redis.TouchTask(taskID)
		return
	}
	w.progressLast.Store(key, pct)
	if detail != "" {
		w.progressDetailLast.Store(taskID, detail)
	}
	// 只写进度三件套不写 status（防 cancelled 标记被覆盖，见 WriteProgress 注释）
	_ = w.redis.WriteProgress(taskID, staged, phase, detail)
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

// RunningTaskInfo 运行中任务的托盘展示快照：任务 ID、进度百分比、最近阶段文案、已运行时长。
type RunningTaskInfo struct {
	TaskID  string
	Percent float64
	Detail  string
	Elapsed time.Duration
}

// GetRunningTaskInfos 返回本节点运行中任务的展示快照（托盘「当前任务」子菜单用）。
// 进度与阶段文案取自 emitProgress/STAGE 的内存缓存（progressNow/progressDetailLast），
// 与卡死检测同源，无额外网络开销。按任务 ID 排序保证菜单展示稳定。
func (w *Worker) GetRunningTaskInfos() []RunningTaskInfo {
	out := make([]RunningTaskInfo, 0, w.GetCurrentTaskCount())
	w.runningTasks.Range(func(_, value any) bool {
		rt, ok := value.(*RunningTask)
		if !ok || rt.Task == nil {
			return true
		}
		info := RunningTaskInfo{TaskID: rt.Task.TaskID, Elapsed: time.Since(rt.StartTime)}
		if p, ok := w.progressNow.Load(rt.Task.TaskID); ok {
			if f, isF := p.(float64); isF {
				info.Percent = f
			}
		}
		if d, ok := w.progressDetailLast.Load(rt.Task.TaskID); ok {
			if s, isS := d.(string); isS {
				info.Detail = s
			}
		}
		out = append(out, info)
		return true
	})
	sort.Slice(out, func(i, j int) bool { return out[i].TaskID < out[j].TaskID })
	return out
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
