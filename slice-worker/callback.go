package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// TaskCallback 任务回调数据
type TaskCallback struct {
	TaskID      string           `json:"task_id"`
	Status      string           `json:"status"`
	NodeID      string           `json:"node_id"`
	Outputs     []OutputFileInfo `json:"outputs"`
	OutputCount int              `json:"output_count"`
	Error       string           `json:"error"`
	Progress    float64          `json:"progress,omitempty"`
	Phase       string           `json:"phase,omitempty"`
	CompletedAt string           `json:"completed_at,omitempty"`
}

// OutputFileInfo 输出文件信息
type OutputFileInfo struct {
	FileName string  `json:"file_name"`
	FileKey  string  `json:"file_key"`
	FileSize int64   `json:"file_size"`
	Duration float64 `json:"duration,omitempty"`
}

// CallbackService 回调服务
type CallbackService struct {
	client *http.Client
	nodeID string
	token  string
}

// NewCallbackService 创建回调服务
func NewCallbackService(nodeID string) *CallbackService {
	return &CallbackService{
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
		nodeID: nodeID,
	}
}

// SetToken 设置回调认证 Token（由任务 payload 中的 callback_token 注入）
func (cs *CallbackService) SetToken(token string) {
	cs.token = token
}

// SendCallback 发送任务完成回调
func (cs *CallbackService) SendCallback(callbackURL string, data *TaskCallback) error {
	if callbackURL == "" {
		return nil // 没有配置回调URL，跳过
	}

	data.NodeID = cs.nodeID
	data.CompletedAt = time.Now().UTC().Format(time.RFC3339)

	body, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("序列化回调数据失败: %w", err)
	}

	req, err := http.NewRequest("POST", callbackURL, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("创建回调请求失败: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if cs.token != "" {
		req.Header.Set("X-Worker-Token", cs.token)
	}

	resp, err := cs.client.Do(req)
	if err != nil {
		return fmt.Errorf("发送回调请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("回调返回非200状态码: %d", resp.StatusCode)
	}

	return nil
}
