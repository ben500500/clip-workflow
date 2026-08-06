package main

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/go-redis/redis/v9"
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

// RegisterNode 注册节点
func (r *RedisClient) RegisterNode(info *NodeInfo) error {
	data, err := json.Marshal(info)
	if err != nil {
		return err
	}

	pipe := r.client.Pipeline()
	pipe.HSet(r.ctx, "slice:nodes", info.NodeID, data)
	pipe.SAdd(r.ctx, "slice:nodes:online", info.NodeID)
	for _, tag := range info.Tags {
		pipe.SAdd(r.ctx, fmt.Sprintf("slice:nodes:tag:%s", tag), info.NodeID)
	}
	_, err = pipe.Exec(r.ctx)
	return err
}

// UnregisterNode 注销节点
func (r *RedisClient) UnregisterNode(nodeID string, tags []string) error {
	pipe := r.client.Pipeline()
	pipe.HDel(r.ctx, "slice:nodes", nodeID)
	pipe.SRem(r.ctx, "slice:nodes:online", nodeID)
	for _, tag := range tags {
		pipe.SRem(r.ctx, fmt.Sprintf("slice:nodes:tag:%s", tag), nodeID)
	}
	_, err := pipe.Exec(r.ctx)
	return err
}

// Heartbeat 心跳上报
func (r *RedisClient) Heartbeat(nodeID string, currentTasks int) error {
	return r.client.HSet(r.ctx, fmt.Sprintf("slice:nodes:%s", nodeID), map[string]interface{}{
		"last_heartbeat": time.Now().Unix(),
		"current_tasks":  currentTasks,
	}).Err()
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
		data, ok := msg.Values["data"].(string)
		if !ok {
			continue
		}

		var task SliceTask
		if err := json.Unmarshal([]byte(data), &task); err != nil {
			continue
		}

		return &StreamMessage{
			ID:      msg.ID,
			Stream:  stream,
			Task:    &task,
			RawData: data,
		}, nil
	}

	return nil, nil
}

// AckTask 确认任务完成
func (r *RedisClient) AckTask(stream, group, msgID string) error {
	return r.client.XAck(r.ctx, stream, group, msgID).Err()
}

// RequeueTask 重新入队任务
func (r *RedisClient) RequeueTask(stream, group, msgID, rawData string) error {
	// 先ACK移除当前消费记录
	r.client.XAck(r.ctx, stream, group, msgID)
	// 重新添加到队列
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

// StreamMessage Stream消息
type StreamMessage struct {
	ID      string
	Stream  string
	Task    *SliceTask
	RawData string
}

// NodeInfo 节点信息
type NodeInfo struct {
	NodeID            string   `json:"node_id"`
	Hostname          string   `json:"hostname"`
	OS                string   `json:"os"`
	Arch              string   `json:"arch"`
	FFmpegVersion     string   `json:"ffmpeg_version"`
	Tags              []string `json:"tags"`
	MaxConcurrent     int      `json:"max_concurrent"`
	CurrentTasks      int      `json:"current_tasks"`
	Status            string   `json:"status"`
	LastHeartbeat     int64    `json:"last_heartbeat"`
	IP                string   `json:"ip"`
	StartedAt         int64    `json:"started_at"`
}

// SliceTask 切片任务
type SliceTask struct {
	TaskID       string            `json:"task_id"`
	EpisodeID    string            `json:"episode_id"`
	Priority     string            `json:"priority"`
	Mode         string            `json:"mode"`
	RequiredTags []string          `json:"required_tags"`
	Source       TaskSource        `json:"source"`
	Cutlist      string            `json:"cutlist"`
	Intervals    string            `json:"intervals"`
	DedupeConfig map[string]float64 `json:"dedupe_config"`
	Output       TaskOutput        `json:"output"`
	TimeoutSec   int               `json:"timeout_seconds"`
	CreatedAt    string            `json:"created_at"`
}

// TaskSource 任务素材来源
type TaskSource struct {
	URL string `json:"url"`
}

// TaskOutput 任务输出配置
type TaskOutput struct {
	UploadURLs   map[string]string `json:"upload_urls"`
	CallbackURL  string            `json:"callback_url"`
	OutputPrefix string            `json:"output_prefix"`
}
