package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"runtime"
	"strings"
)

// Config Worker配置
type Config struct {
	NodeID            string   `json:"node_id"`
	RedisURL          string   `json:"redis_url"`
	Tags              []string `json:"tags"`
	MaxConcurrent     int      `json:"max_concurrent"`
	EnginesPath       string   `json:"engines_path"`
	TempDir           string   `json:"temp_dir"`
	LogLevel          string   `json:"log_level"`
	HeartbeatInterval int      `json:"heartbeat_interval"` // 秒
	TaskTimeout       int      `json:"task_timeout"`       // 秒
}

// DefaultConfig 默认配置
func DefaultConfig() *Config {
	hostname, _ := os.Hostname()
	return &Config{
		NodeID:            hostname,
		RedisURL:          "redis://localhost:6379",
		Tags:              []string{"cpu"},
		MaxConcurrent:     2,
		EnginesPath:       "./engines",
		TempDir:           "/tmp/slice-worker",
		LogLevel:          "info",
		HeartbeatInterval: 10,
		TaskTimeout:       7200,
	}
}

// LoadConfig 加载配置
func LoadConfig(path string) (*Config, error) {
	cfg := DefaultConfig()

	data, err := os.ReadFile(path)
	if err != nil {
		return cfg, nil // 使用默认配置
	}

	if err := json.Unmarshal(data, cfg); err != nil {
		return nil, err
	}

	return cfg, nil
}

// GetOS 获取操作系统
func GetOS() string {
	return runtime.GOOS
}

// GetArch 获取架构
func GetArch() string {
	return runtime.GOARCH
}

// GetFFmpegVersion 获取ffmpeg版本
func GetFFmpegVersion() string {
	cmd := exec.Command("ffmpeg", "-version")
	out, err := cmd.Output()
	if err != nil {
		return "unknown"
	}
	lines := strings.Split(string(out), "\n")
	if len(lines) > 0 {
		return strings.TrimSpace(lines[0])
	}
	return "unknown"
}

// GetIP 获取本机IP
func GetIP() string {
	cmd := exec.Command("hostname", "-I")
	out, err := cmd.Output()
	if err != nil {
		// macOS fallback
		cmd = exec.Command("ipconfig", "getifaddr", "en0")
		out, err = cmd.Output()
		if err != nil {
			return "unknown"
		}
	}
	return strings.TrimSpace(strings.Split(string(out), " ")[0])
}
