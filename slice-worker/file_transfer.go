package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

// FileTransfer 文件传输管理
type FileTransfer struct {
	client     *http.Client
	onProgress func(taskID string, fileName string, downloaded, total int64)
}

// NewFileTransfer 创建文件传输管理器
func NewFileTransfer() *FileTransfer {
	return &FileTransfer{
		client: &http.Client{
			Timeout: 30 * time.Minute, // 大文件需要较长超时
		},
	}
}

// SetProgressCallback 设置进度回调
func (ft *FileTransfer) SetProgressCallback(cb func(taskID string, fileName string, downloaded, total int64)) {
	ft.onProgress = cb
}

// DownloadFile 下载文件（带进度回调与取消支持）
func (ft *FileTransfer) DownloadFile(ctx context.Context, url, destPath, taskID string) error {
	// 创建目标目录
	if err := os.MkdirAll(filepath.Dir(destPath), 0755); err != nil {
		return fmt.Errorf("创建目录失败: %w", err)
	}

	// 发起请求（支持 context 取消）
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fmt.Errorf("创建下载请求失败: %w", err)
	}

	resp, err := ft.client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return fmt.Errorf("下载已取消: %w", ctx.Err())
		}
		return fmt.Errorf("下载请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("下载失败，HTTP状态: %d", resp.StatusCode)
	}

	// 创建目标文件
	out, err := os.Create(destPath)
	if err != nil {
		return fmt.Errorf("创建文件失败: %w", err)
	}
	defer out.Close()

	// 带进度的拷贝
	total := resp.ContentLength
	var downloaded int64
	buf := make([]byte, 32*1024) // 32KB buffer

	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("下载已取消: %w", ctx.Err())
		default:
		}

		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, writeErr := out.Write(buf[:n]); writeErr != nil {
				return fmt.Errorf("写入文件失败: %w", writeErr)
			}
			downloaded += int64(n)

			// 进度回调
			if ft.onProgress != nil {
				fileName := filepath.Base(destPath)
				ft.onProgress(taskID, fileName, downloaded, total)
			}
		}
		if readErr != nil {
			if readErr == io.EOF {
				break
			}
			return fmt.Errorf("读取数据失败: %w", readErr)
		}
	}

	return nil
}

// UploadFile 上传文件（PUT方式，用于MinIO Presigned URL）
func (ft *FileTransfer) UploadFile(ctx context.Context, filePath, uploadURL, taskID string) error {
	// 打开文件
	file, err := os.Open(filePath)
	if err != nil {
		return fmt.Errorf("打开文件失败: %w", err)
	}
	defer file.Close()

	// 获取文件大小
	stat, err := file.Stat()
	if err != nil {
		return fmt.Errorf("获取文件信息失败: %w", err)
	}

	// 创建请求
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, uploadURL, file)
	if err != nil {
		return fmt.Errorf("创建请求失败: %w", err)
	}
	req.ContentLength = stat.Size()
	req.Header.Set("Content-Type", "video/mp4")

	// 发起请求
	resp, err := ft.client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return fmt.Errorf("上传已取消: %w", ctx.Err())
		}
		return fmt.Errorf("上传请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("上传失败，HTTP状态: %d, 响应: %s", resp.StatusCode, string(body))
	}

	return nil
}

// UploadFileWithProgress 带进度回调的上传
func (ft *FileTransfer) UploadFileWithProgress(ctx context.Context, filePath, uploadURL, taskID string) error {
	// 打开文件
	file, err := os.Open(filePath)
	if err != nil {
		return fmt.Errorf("打开文件失败: %w", err)
	}
	defer file.Close()

	stat, err := file.Stat()
	if err != nil {
		return fmt.Errorf("获取文件信息失败: %w", err)
	}

	// 包装Reader带进度
	reader := &progressReader{
		reader:   file,
		total:    stat.Size(),
		taskID:   taskID,
		fileName: filepath.Base(filePath),
		callback: ft.onProgress,
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPut, uploadURL, reader)
	if err != nil {
		return fmt.Errorf("创建请求失败: %w", err)
	}
	req.ContentLength = stat.Size()
	req.Header.Set("Content-Type", "video/mp4")

	resp, err := ft.client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return fmt.Errorf("上传已取消: %w", ctx.Err())
		}
		return fmt.Errorf("上传请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("上传失败，HTTP状态: %d, 响应: %s", resp.StatusCode, string(body))
	}

	return nil
}

// uploadURLResponse 后端申请上传 URL 的响应
type uploadURLResponse struct {
	UploadURL string `json:"upload_url"`
	FileKey   string `json:"file_key"`
}

// GetUploadURL 向后端申请输出文件的上传 URL。
//
// 修复"单 URL 拼文件名导致 MinIO 签名失效"问题：
// 每个输出文件都通过后端生成精确绑定 object key 的 presigned PUT URL。
func (ft *FileTransfer) GetUploadURL(ctx context.Context, backendURL, taskID, fileName, token string) (string, string, error) {
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		fmt.Sprintf("%s/api/slice-tasks/%s/upload-url?file_name=%s", backendURL, taskID, filepath.Base(fileName)),
		nil,
	)
	if err != nil {
		return "", "", fmt.Errorf("创建上传URL请求失败: %w", err)
	}
	if token != "" {
		req.Header.Set("X-Worker-Token", token)
	}

	resp, err := ft.client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("申请上传URL失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", "", fmt.Errorf("申请上传URL失败，HTTP状态: %d: %s", resp.StatusCode, string(body))
	}

	var data uploadURLResponse
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return "", "", fmt.Errorf("解析上传URL响应失败: %w", err)
	}
	if data.UploadURL == "" {
		return "", "", fmt.Errorf("上传URL为空")
	}

	return data.UploadURL, data.FileKey, nil
}

// progressReader 带进度的Reader
type progressReader struct {
	reader   io.Reader
	total    int64
	read     int64
	taskID   string
	fileName string
	callback func(taskID string, fileName string, downloaded, total int64)
}

func (pr *progressReader) Read(p []byte) (n int, err error) {
	n, err = pr.reader.Read(p)
	pr.read += int64(n)
	if pr.callback != nil {
		pr.callback(pr.taskID, pr.fileName, pr.read, pr.total)
	}
	return
}
