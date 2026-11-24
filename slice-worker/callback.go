package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
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

// SendCallback 发送任务完成回调。
//
// 带重试（2026-11-25 三机实测补强）：此前回调只发一次，网络抖动/后端重启/
// 瞬时 5xx 任一命中，任务终态就永远同步不到后端——DB 里长期 running，
// 后续只能靠 30 分钟僵尸巡检兜（实测 2eec9a10 就是这样卡住的）。
// 现对「网络错误 + 5xx + 408/429」做 3 次指数退避重试（1s/2s/4s）；
// 4xx（如 401 token 错、422 校验错）不重试——重发结果一样，只浪费时间。
func (cs *CallbackService) SendCallback(callbackURL string, data *TaskCallback) error {
	if callbackURL == "" {
		return nil // 没有配置回调URL，跳过
	}

	var lastErr error
	backoff := time.Second
	for attempt := 1; attempt <= 3; attempt++ {
		err, retryable := cs.sendOnce(callbackURL, data)
		if err == nil {
			return nil
		}
		lastErr = err
		if !retryable || attempt == 3 {
			return err
		}
		time.Sleep(backoff)
		backoff *= 2
	}
	return lastErr
}

// sendOnce 单次回调投递，返回 (错误, 是否值得重试)
func (cs *CallbackService) sendOnce(callbackURL string, data *TaskCallback) (error, bool) {
	data.NodeID = cs.nodeID
	data.CompletedAt = time.Now().UTC().Format(time.RFC3339)

	body, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("序列化回调数据失败: %w", err), false
	}

	req, err := http.NewRequest("POST", callbackURL, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("创建回调请求失败: %w", err), false
	}
	req.Header.Set("Content-Type", "application/json")
	if cs.token != "" {
		req.Header.Set("X-Worker-Token", cs.token)
	}

	resp, err := cs.client.Do(req)
	if err != nil {
		// 网络层错误（连接拒绝/超时/DNS）：值得重试
		return fmt.Errorf("发送回调请求失败: %w", err), true
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		// 带上响应体前 300 字节：422/500 这类校验错误不看 body 根本无从排查
		// （2026-11-24 三机实测：180 节点失败回调 422，只看状态码抓瞎）
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 300))
		// 5xx 与 408/429 属可恢复（后端重启/限流），4xx 重发无意义
		retryable := resp.StatusCode >= 500 || resp.StatusCode == 408 || resp.StatusCode == 429
		return fmt.Errorf("回调返回非200状态码: %d, body: %s", resp.StatusCode, string(respBody)), retryable
	}

	return nil, false
}
