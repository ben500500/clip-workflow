package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

// TaskCallback 任务回调数据
type TaskCallback struct {
	TaskID      string             `json:"task_id"`
	Status      string             `json:"status"`
	NodeID      string             `json:"node_id"`
	Outputs     []OutputFileInfo   `json:"outputs"`
	OutputCount int                `json:"output_count"`
	Error       string             `json:"error"`
	Progress    float64            `json:"progress,omitempty"`
	Phase       string             `json:"phase,omitempty"`
	CompletedAt string             `json:"completed_at,omitempty"`
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

// SendProgressCallback 发送进度回调
func (cs *CallbackService) SendProgressCallback(callbackURL string, taskID string, progress float64, phase string) error {
	if callbackURL == "" {
		return nil
	}

	data := TaskCallback{
		TaskID:   taskID,
		Status:   "progress",
		NodeID:   cs.nodeID,
		Progress: progress,
		Phase:    phase,
	}

	body, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("序列化进度数据失败: %w", err)
	}

	req, err := http.NewRequest("POST", callbackURL, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("创建进度回调请求失败: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := cs.client.Do(req)
	if err != nil {
		// 进度回调失败不中断任务，只记录日志
		return err
	}
	defer resp.Body.Close()

	return nil
}

// BuildOutputFileInfo 从输出文件路径构建输出文件信息
func BuildOutputFileInfo(outputPath string, outputPrefix string) OutputFileInfo {
	info := OutputFileInfo{
		FileName: filepath.Base(outputPath),
		FileSize: 0,
	}

	// 获取文件大小
	if stat, err := os.Stat(outputPath); err == nil {
		info.FileSize = stat.Size()
	}

	// 构建 file_key（相对于 MinIO bucket 的路径）
	info.FileKey = outputPrefix + info.FileName

	return info
}