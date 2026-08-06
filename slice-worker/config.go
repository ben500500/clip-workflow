package main

import (
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
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
	// 任务失败重试次数（0 表示不重试）
	MaxRetries int `json:"max_retries"`
	// 任务失败重试延迟（秒）
	RetryDelay int `json:"retry_delay"`
	// 节点心跳 Hash 的 TTL（秒），默认 3 * HeartbeatInterval
	NodeTTL int `json:"node_ttl"`
	// 后端 API 地址（用于获取输出上传 URL 等，默认 http://backend:8080）
	BackendURL string `json:"backend_url"`
	// CPU 资源分配百分比（默认 50，表示本节点切片最多使用 50% 的 CPU 资源）
	CPUPercent int `json:"cpu_percent"`
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
		MaxRetries:        2,
		RetryDelay:        30,
		NodeTTL:           0,
		BackendURL:        "http://backend:8080",
		CPUPercent:        50,
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

	// CPU 分配比例范围约束：1 ~ 100，默认 50
	if cfg.CPUPercent < 1 || cfg.CPUPercent > 100 {
		cfg.CPUPercent = 50
	}

	return cfg, nil
}

// ClampCPUPercent 将 CPU 分配比例约束在 1~100 范围内（供动态调整时使用）
func ClampCPUPercent(v int) int {
	if v < 1 {
		return 1
	}
	if v > 100 {
		return 100
	}
	return v
}

// HeartbeatTTL 返回节点 Hash 的 TTL（默认 3 倍心跳间隔）
func (c *Config) HeartbeatTTL() time.Duration {
	if c.NodeTTL > 0 {
		return time.Duration(c.NodeTTL) * time.Second
	}
	return time.Duration(3*c.HeartbeatInterval) * time.Second
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
//
// 使用标准库 net 包遍历本机所有非回环 IPv4 地址，优先返回内网/可达地址。
// 相比调用 hostname -I，不依赖外部命令（Docker 精简镜像或某些环境可能没有该命令），
// 并且能正确处理多网卡、容器网络等场景，避免返回空值导致 IP 列无法显示。
func GetIP() string {
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return "unknown"
	}

	// 第一遍优先返回私网 IPv4（最常见的容器/内网节点场景）
	for _, addr := range addrs {
		ipNet, ok := addr.(*net.IPNet)
		if !ok {
			continue
		}
		ip4 := ipNet.IP.To4()
		if ip4 == nil {
			continue
		}
		if ip4.IsLoopback() {
			continue
		}
		if isPrivateIPv4(ip4) {
			return ip4.String()
		}
	}

	// 第二遍兜底返回任意非回环 IPv4
	for _, addr := range addrs {
		ipNet, ok := addr.(*net.IPNet)
		if !ok {
			continue
		}
		ip4 := ipNet.IP.To4()
		if ip4 == nil || ip4.IsLoopback() {
			continue
		}
		return ip4.String()
	}

	return "unknown"
}

// isPrivateIPv4 判断是否为私网 IPv4 地址（10/8、172.16/12、192.168/16、169.254/16）
func isPrivateIPv4(ip net.IP) bool {
	return ip.IsPrivate() || ip.IsLinkLocalUnicast()
}
