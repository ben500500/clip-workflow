package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// engineExclude 计算/打包引擎版本时排除的目录与文件（与后端 _ENGINE_EXCLUDE 对齐）。
// 避免把缓存/编译产物/文档等无关文件纳入版本判定与下发。
var engineExclude = map[string]bool{
	"__pycache__": true,
	".pyc":        true,
	".pyo":        true,
	".git":        true,
	".DS_Store":   true,
	".gitignore":  true,
	"README.md":   true,
}

// nodeUpdateCommand 对应后端写入 `slice:node-update:{node_id}` 的指令结构。
type nodeUpdateCommand struct {
	TargetVersion string `json:"target_version"`
	RequestedAt   string `json:"requested_at"`
}

// ComputeEngineVersion 计算本地引擎目录版本（与后端算法一致）：
// 遍历目录下所有应下发文件，汇总「相对路径 + 内容」的 SHA256，取前 12 位十六进制。
// 任一文件内容/新增/删除变化都会导致版本变化，用于节点判断是否需要更新。
func ComputeEngineVersion(enginesDir string) (string, error) {
	h := sha256.New()
	files, err := listEngineFiles(enginesDir)
	if err != nil {
		return "", err
	}
	for _, fp := range files {
		rel, rerr := filepath.Rel(enginesDir, fp)
		if rerr != nil {
			continue
		}
		h.Write([]byte(rel))
		data, rerr := os.ReadFile(fp)
		if rerr != nil {
			continue
		}
		h.Write(data)
	}
	return hex.EncodeToString(h.Sum(nil))[:12], nil
}

// listEngineFiles 递归列出引擎目录下应下发/纳入版本判定的普通文件（排除缓存）。
func listEngineFiles(enginesDir string) ([]string, error) {
	var out []string
	err := filepath.Walk(enginesDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil // 跳过无权限/异常文件
		}
		if info.IsDir() {
			if engineExclude[info.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		if engineExclude[info.Name()] {
			return nil
		}
		out = append(out, path)
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(out)
	return out, nil
}

// PullEngineUpdate 从后端下载引擎更新包（tar.gz），解压到目标目录。
//
// 通过 HTTP GET `{backend}/api/workers/engines/package` 获取服务器端最新引擎包，
// 解压后返回新引擎版本号。下载失败/解压失败返回 error。
func PullEngineUpdate(backendURL, enginesDir string) (string, error) {
	base := strings.TrimRight(backendURL, "/")
	if base == "" {
		return "", fmt.Errorf("后端地址为空，无法拉取引擎更新")
	}
	url := base + "/api/workers/engines/package"

	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Get(url)
	if err != nil {
		return "", fmt.Errorf("请求引擎更新包失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("拉取引擎更新包返回非 2xx: %d", resp.StatusCode)
	}

	// 读取更新包
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("读取引擎更新包失败: %w", err)
	}

	// 解压到目标目录
	if err := extractTarGz(body, enginesDir); err != nil {
		return "", fmt.Errorf("解压引擎更新包失败: %w", err)
	}

	// 计算应用后的版本
	newVersion, err := ComputeEngineVersion(enginesDir)
	if err != nil {
		return "", fmt.Errorf("计算更新后引擎版本失败: %w", err)
	}
	return newVersion, nil
}

// extractTarGz 把 tar.gz 字节流解压到目标目录（覆盖式更新）。
// 安全措施：拒绝路径穿越（../）、绝对路径；解压到目标目录内。
func extractTarGz(data []byte, destDir string) error {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return err
	}
	defer gz.Close()

	tr := tar.NewReader(gz)
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return err
	}

	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}

		// 安全校验：防止路径穿越
		name := filepath.Clean(hdr.Name)
		if strings.HasPrefix(name, "..") || strings.HasPrefix(name, "/") {
			return fmt.Errorf("引擎更新包包含非法路径: %s", hdr.Name)
		}
		target := filepath.Join(destDir, name)
		// 确保目标在 destDir 内
		rel, err := filepath.Rel(destDir, target)
		if err != nil || strings.HasPrefix(rel, "..") {
			return fmt.Errorf("引擎更新包路径越界: %s", hdr.Name)
		}

		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
				return err
			}
			// 先写临时文件再重命名，避免半截文件污染
			tmp := target + ".tmp"
			f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0755)
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				f.Close()
				os.Remove(tmp)
				return err
			}
			if err := f.Close(); err != nil {
				os.Remove(tmp)
				return err
			}
			if err := os.Rename(tmp, target); err != nil {
				os.Remove(tmp)
				return err
			}
		}
	}
	return nil
}

// readUpdateCommandJSON 解析 Redis 更新指令（JSON 字符串）。
func readUpdateCommandJSON(raw string) (*nodeUpdateCommand, error) {
	var cmd nodeUpdateCommand
	if err := json.Unmarshal([]byte(raw), &cmd); err != nil {
		return nil, err
	}
	if cmd.TargetVersion == "" {
		return nil, fmt.Errorf("更新指令缺少目标版本")
	}
	return &cmd, nil
}
