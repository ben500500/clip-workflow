package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync/atomic"
	"time"
)

// WorkerHeartbeatPayload 后端 /api/workers/heartbeat 接口的请求体。
// 数据契约与 backend/app/api/workers.py 的 WorkerHeartbeatRequest 对齐。
type WorkerHeartbeatPayload struct {
	NodeID              string   `json:"node_id"`
	Hostname            string   `json:"hostname"`
	IP                  string   `json:"ip"`
	OS                  string   `json:"os"`
	Arch                string   `json:"arch"`
	FFmpegVersion       string   `json:"ffmpeg_version"`
	Tags                []string `json:"tags"`
	MaxConcurrent       int      `json:"max_concurrent"`
	CurrentTasks        int      `json:"current_tasks"`
	Status              string   `json:"status"`
	TotalTasksCompleted int      `json:"total_tasks_completed"`
	TotalTasksFailed    int      `json:"total_tasks_failed"`
	// 节点硬件编码能力（如 h264_nvenc/hevc_nvenc 等；预留 GPU 节点自动分派接口）
	EncoderCapabilities []string `json:"encoder_capabilities"`
}

// WorkerHeartbeatResponse 后端 /api/workers/heartbeat 接口的响应体。
// 兼容旧后端：enabled 字段缺失时按 true（启用）处理，不破坏旧版契约。
type WorkerHeartbeatResponse struct {
	OK       string `json:"ok"`
	NodeID   string `json:"node_id"`
	Enabled  *bool  `json:"enabled"`
}

// sendBackendHeartbeat 向后端 API 上报心跳，把节点信息同步到数据库 worker_nodes 表。
//
// 此前节点只写 Redis（slice:nodes:{id}），后端 DB 表 worker_nodes 仅在被查询/手动同步时
// 才合并 Redis 数据；若 Redis 与后端网络/权限异常，页面就会“看不到任何数据”。
// 这里直接调用后端心跳接口，保证 DB 与 Redis 双写、数据实时同步。
//
// 同时把响应中的 enabled 状态写回 w.backendEnabled（管理员 PATCH 启停节点后，
// 下一次心跳即生效：enabled=false 时 Worker 暂停领取新任务，保持心跳）。
func (w *Worker) sendBackendHeartbeat() error {
	base := strings.TrimRight(w.config.BackendURL, "/")
	if base == "" {
		return nil
	}

	payload := WorkerHeartbeatPayload{
		NodeID:              w.config.NodeID,
		Hostname:            getHostname(),
		IP:                  GetIP(),
		OS:                  GetOS(),
		Arch:                GetArch(),
		FFmpegVersion:       GetFFmpegVersion(),
		Tags:                w.config.Tags,
		MaxConcurrent:       w.config.MaxConcurrent,
		CurrentTasks:        int(atomic.LoadInt32(&w.currentTasks)),
		Status:              "online",
		TotalTasksCompleted: int(atomic.LoadInt32(&w.totalCompleted)),
		TotalTasksFailed:    int(atomic.LoadInt32(&w.totalFailed)),
		EncoderCapabilities: w.encoderCapabilities,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("序列化心跳数据失败: %w", err)
	}

	req, err := http.NewRequest(
		http.MethodPost,
		base+"/api/workers/heartbeat",
		bytes.NewReader(body),
	)
	if err != nil {
		return fmt.Errorf("创建心跳请求失败: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("心跳请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("心跳接口返回非 2xx: %d", resp.StatusCode)
	}

	// 解析响应，把 enabled 状态写回 Worker（enabled 缺失时视为启用，兼容旧后端）
	var hbResp WorkerHeartbeatResponse
	if err := json.NewDecoder(resp.Body).Decode(&hbResp); err == nil && hbResp.Enabled != nil {
		w.setBackendEnabled(*hbResp.Enabled)
	}
	return nil
}
