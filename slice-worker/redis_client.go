package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisClient Redis客户端封装
type RedisClient struct {
	client *redis.Client
	ctx    context.Context
}

// NewRedisClient 创建Redis客户端
func NewRedisClient(redisURL string) (*RedisClient, error) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("解析Redis URL失败: %w", err)
	}

	client := redis.NewClient(opts)
	ctx := context.Background()

	// 测试连接
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("Redis连接失败: %w", err)
	}

	return &RedisClient{client: client, ctx: ctx}, nil
}

// Close 关闭连接
func (r *RedisClient) Close() error {
	return r.client.Close()
}

// nodeKey 节点信息 Hash key（契约与 Python get_worker_nodes_from_redis 对齐）
func nodeKey(nodeID string) string {
	return "slice:nodes:" + nodeID
}

// RegisterNode 注册节点
//
// 数据契约（与后端 Python 读取方保持一致）：
//   - 节点信息写入 Hash `slice:nodes:{node_id}`，并设置 TTL（3 倍心跳间隔）
//   - 同时维护 `slice:nodes:online` 在线集合与 `slice:nodes:tag:{tag}` 标签集合
func (r *RedisClient) RegisterNode(info *NodeInfo, heartbeatTTL time.Duration) error {
	fields := map[string]interface{}{
		"node_id":               info.NodeID,
		"hostname":              info.Hostname,
		"ip":                    info.IP,
		"os":                    info.OS,
		"arch":                  info.Arch,
		"ffmpeg_version":        info.FFmpegVersion,
		"max_concurrent":        info.MaxConcurrent,
		"current_tasks":         info.CurrentTasks,
		"status":                info.Status,
		"last_heartbeat":        time.Now().Unix(),
		"started_at":            info.StartedAt,
		"total_tasks_completed": info.TotalTasksCompleted,
		"total_tasks_failed":    info.TotalTasksFailed,
		"cpu_percent":           info.CPUPercent,
	}
	if len(info.Tags) > 0 {
		tagsJSON, err := json.Marshal(info.Tags)
		if err != nil {
			return err
		}
		fields["tags"] = string(tagsJSON)
	} else {
		fields["tags"] = "[]"
	}

	pipe := r.client.Pipeline()
	pipe.HSet(r.ctx, nodeKey(info.NodeID), fields)
	pipe.Expire(r.ctx, nodeKey(info.NodeID), heartbeatTTL)
	pipe.SAdd(r.ctx, "slice:nodes:online", info.NodeID)
	for _, tag := range info.Tags {
		pipe.SAdd(r.ctx, fmt.Sprintf("slice:nodes:tag:%s", tag), info.NodeID)
	}
	_, err := pipe.Exec(r.ctx)
	return err
}

// UnregisterNode 注销节点
func (r *RedisClient) UnregisterNode(nodeID string, tags []string) error {
	pipe := r.client.Pipeline()
	pipe.Del(r.ctx, nodeKey(nodeID))
	pipe.SRem(r.ctx, "slice:nodes:online", nodeID)
	for _, tag := range tags {
		pipe.SRem(r.ctx, fmt.Sprintf("slice:nodes:tag:%s", tag), nodeID)
	}
	_, err := pipe.Exec(r.ctx)
	return err
}

// Heartbeat 心跳上报（含累计完成/失败数），并刷新节点 Hash 的 TTL
func (r *RedisClient) Heartbeat(nodeID string, currentTasks, totalCompleted, totalFailed int, heartbeatTTL time.Duration) error {
	pipe := r.client.Pipeline()
	pipe.HSet(r.ctx, nodeKey(nodeID), map[string]interface{}{
		"last_heartbeat":        time.Now().Unix(),
		"current_tasks":         currentTasks,
		"total_tasks_completed": totalCompleted,
		"total_tasks_failed":    totalFailed,
		"status":                "online",
	})
	pipe.Expire(r.ctx, nodeKey(nodeID), heartbeatTTL)
	_, err := pipe.Exec(r.ctx)
	return err
}

// FetchTask 从优先级队列获取任务
func (r *RedisClient) FetchTask(streams []string, group, consumer string, timeout time.Duration) (*StreamMessage, error) {
	for _, stream := range streams {
		msgs, err := r.client.XReadGroup(r.ctx, &redis.XReadGroupArgs{
			Group:    group,
			Consumer: consumer,
			Streams:  []string{stream, ">"},
			Count:    1,
			Block:    timeout,
		}).Result()

		if err != nil || len(msgs) == 0 || len(msgs[0].Messages) == 0 {
			continue
		}

		msg := msgs[0].Messages[0]
		task, data, err := parseStreamMessage(msg)
		if err != nil {
			continue
		}

		return &StreamMessage{
			ID:      msg.ID,
			Stream:  stream,
			Task:    task,
			RawData: data,
		}, nil
	}

	return nil, nil
}

// parseStreamMessage 解析 Stream 消息为 SliceTask
func parseStreamMessage(msg redis.XMessage) (*SliceTask, string, error) {
	data, ok := msg.Values["data"].(string)
	if !ok {
		return nil, "", fmt.Errorf("消息缺少 data 字段")
	}
	var task SliceTask
	if err := json.Unmarshal([]byte(data), &task); err != nil {
		return nil, "", err
	}
	return &task, data, nil
}

// AckTask 确认任务完成（从 PEL 移除）
func (r *RedisClient) AckTask(stream, group, msgID string) error {
	return r.client.XAck(r.ctx, stream, group, msgID).Err()
}

// RequeueTask 重新入队任务（用于标签不匹配或延迟重试）
func (r *RedisClient) RequeueTask(stream, rawData string) error {
	return r.client.XAdd(r.ctx, &redis.XAddArgs{
		Stream: stream,
		Values: map[string]interface{}{"data": rawData},
	}).Err()
}

// CreateConsumerGroup 创建消费者组
func (r *RedisClient) CreateConsumerGroup(stream, group string) error {
	err := r.client.XGroupCreateMkStream(r.ctx, stream, group, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		return err
	}
	return nil
}

// ClaimStaleTasks 从 PEL 中认领超时未完成（Worker 崩溃遗留）的任务。
//
// 返回被认领且可重新处理的消息列表；认领前会检查任务 Hash 的租约（lease），
// 若任务正被其他存活 Worker 处理，则不会重复认领。
func (r *RedisClient) ClaimStaleTasks(streams []string, group, consumer string, minIdle time.Duration) ([]*StreamMessage, error) {
	var claimed []*StreamMessage
	for _, stream := range streams {
		res, _, err := r.client.XAutoClaim(r.ctx, &redis.XAutoClaimArgs{
			Stream:   stream,
			Group:    group,
			Consumer: consumer,
			MinIdle:  minIdle,
			Start:    "0-0",
			Count:    100,
		}).Result()
		if err != nil {
			continue
		}
		for _, msg := range res {
			task, data, err := parseStreamMessage(msg)
			if err != nil {
				continue
			}
			claimed = append(claimed, &StreamMessage{
				ID:      msg.ID,
				Stream:  stream,
				Task:    task,
				RawData: data,
			})
		}
	}
	return claimed, nil
}

// UpdateTaskStatus 更新任务状态
func (r *RedisClient) UpdateTaskStatus(taskID string, status string, extra map[string]interface{}) error {
	fields := map[string]interface{}{
		"status": status,
	}
	for k, v := range extra {
		fields[k] = v
	}
	return r.client.HSet(r.ctx, fmt.Sprintf("slice:task:%s", taskID), fields).Err()
}

// TouchTask 刷新运行中任务租约（供其他 Worker 判定任务是否仍在处理）
func (r *RedisClient) TouchTask(taskID string) error {
	return r.client.HSet(r.ctx, fmt.Sprintf("slice:task:%s", taskID), map[string]interface{}{
		"lease": time.Now().Unix(),
	}).Err()
}

// IsTaskCancelled 检查任务是否被后端标记为取消
func (r *RedisClient) IsTaskCancelled(taskID string) (bool, error) {
	status, err := r.client.HGet(r.ctx, fmt.Sprintf("slice:task:%s", taskID), "status").Result()
	if err == redis.Nil {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return status == "cancelled", nil
}

// ExpireTaskStatus 为任务状态 Hash 设置 TTL（任务终态后清理）
func (r *RedisClient) ExpireTaskStatus(taskID string, ttl time.Duration) error {
	return r.client.Expire(r.ctx, fmt.Sprintf("slice:task:%s", taskID), ttl).Err()
}

// GetTaskHash 读取任务状态 Hash（用于去重判定）
func (r *RedisClient) GetTaskHash(taskID string) (map[string]string, error) {
	return r.client.HGetAll(r.ctx, fmt.Sprintf("slice:task:%s", taskID)).Result()
}

// IsNodeEnabled 检查节点是否被管理员停用（停用后不再领取新任务）
func (r *RedisClient) IsNodeEnabled(nodeID string) (bool, error) {
	val, err := r.client.Get(r.ctx, fmt.Sprintf("slice:node-enabled:%s", nodeID)).Result()
	if err == redis.Nil {
		return true, nil
	}
	if err != nil {
		return true, err
	}
	return val != "0" && val != "false", nil
}

// GetNodeCPUPercent 读取节点 CPU 分配比例控制 key（1~100）。
// 若未设置则返回 fallback（默认取 worker.json 中的 cpu_percent，默认 50）。
func (r *RedisClient) GetNodeCPUPercent(nodeID string, fallback int) (int, error) {
	val, err := r.client.Get(r.ctx, fmt.Sprintf("slice:node-cpu-percent:%s", nodeID)).Result()
	if err == redis.Nil {
		return fallback, nil
	}
	if err != nil {
		return fallback, err
	}
	n, err := strconv.Atoi(strings.TrimSpace(val))
	if err != nil {
		return fallback, nil
	}
	if n < 1 {
		n = 1
	}
	if n > 100 {
		n = 100
	}
	return n, nil
}

// SetNodeEnabled 设置节点启用/停用状态（与后端 /workers/{id}/enable|disable 共用 Redis key）
func (r *RedisClient) SetNodeEnabled(nodeID string, enabled bool) error {
	val := "1"
	if !enabled {
		val = "0"
	}
	return r.client.Set(r.ctx, fmt.Sprintf("slice:node-enabled:%s", nodeID), val, 0).Err()
}

// SetNodeCPUPercent 设置节点 CPU 资源分配比例（1~100）。
// 与后端 /workers/{id}/cpu-percent 共用 Redis key，Worker 下次领取任务前生效。
func (r *RedisClient) SetNodeCPUPercent(nodeID string, percent int) error {
	if percent < 1 {
		percent = 1
	}
	if percent > 100 {
		percent = 100
	}
	return r.client.Set(r.ctx, fmt.Sprintf("slice:node-cpu-percent:%s", nodeID), strconv.Itoa(percent), 0).Err()
}

// StreamMessage Stream消息
type StreamMessage struct {
	ID      string
	Stream  string
	Task    *SliceTask
	RawData string
}

// NodeInfo 节点信息
type NodeInfo struct {
	NodeID              string   `json:"node_id"`
	Hostname            string   `json:"hostname"`
	OS                  string   `json:"os"`
	Arch                string   `json:"arch"`
	FFmpegVersion       string   `json:"ffmpeg_version"`
	Tags                []string `json:"tags"`
	MaxConcurrent       int      `json:"max_concurrent"`
	CurrentTasks        int      `json:"current_tasks"`
	Status              string   `json:"status"`
	LastHeartbeat       int64    `json:"last_heartbeat"`
	IP                  string   `json:"ip"`
	StartedAt           int64    `json:"started_at"`
	TotalTasksCompleted int      `json:"total_tasks_completed"`
	TotalTasksFailed    int      `json:"total_tasks_failed"`
	CPUPercent          int      `json:"cpu_percent"`
}

// SliceTask 切片任务
type SliceTask struct {
	TaskID         string             `json:"task_id"`
	EpisodeID      string             `json:"episode_id"`
	Priority       string             `json:"priority"`
	Mode           string             `json:"mode"`
	RequiredTags   []string           `json:"required_tags"`
	Source         TaskSource         `json:"source"`
	Cutlist        string             `json:"cutlist"`
	Intervals      string             `json:"intervals"`
	DedupeConfig   map[string]float64 `json:"dedupe_config"`
	// 自定义文字水印配置（可选，后端透传，引擎叠加动态文字水印）
	Watermark      map[string]interface{} `json:"watermark"`
	Output         TaskOutput             `json:"output"`
	TimeoutSec     int                    `json:"timeout_seconds"`
	SourceDuration float64                `json:"source_duration"`
	RetryCount     int                    `json:"retry_count"`
	RetryAt        int64                  `json:"retry_at,omitempty"`
	CreatedAt      string                 `json:"created_at"`
}

// TaskSource 任务素材来源
type TaskSource struct {
	URL string `json:"url"`
}

// TaskOutput 任务输出配置
type TaskOutput struct {
	// UploadURL 为后端提供的"按输出文件逐一申请 presigned PUT URL"的端点，
	// Worker 上传每个输出文件前调用该端点获取精确绑定 object key 的上传地址。
	UploadURL    string `json:"upload_url"`
	CallbackURL  string `json:"callback_url"`
	OutputPrefix string `json:"output_prefix"`
	// CallbackToken 为回调/上传接口认证 Token，防止伪造回调
	CallbackToken string `json:"callback_token,omitempty"`
}
