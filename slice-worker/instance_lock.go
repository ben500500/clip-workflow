package main

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
)

// 单实例锁：防止同一节点（node-id）启动多个 worker 实例。
//
// 背景：macOS 托盘模式曾因误启两个实例导致菜单栏出现两个图标、
// 心跳互相覆盖。这里用「节点配置目录下的锁文件 + PID 存活校验」保证
// 同一 node-id 同时只有一个进程在运行。
//
// 说明：锁文件按 node-id 命名（而非全局），同一机器可跑多个不同节点
// （如 mac-1 / mac-2），互不干扰；同 node-id 重复启动会被拒绝。

const instanceLockDir = "temp" // 相对 slice-worker 根目录

// acquireInstanceLock 尝试获取单实例锁。
// 返回 release 函数（进程退出时释放锁）；已存在存活实例时返回错误。
func acquireInstanceLock(nodeID string) (release func(), err error) {
	dir := instanceLockDir
	if abs, aerr := filepath.Abs(dir); aerr == nil {
		dir = abs
	}
	if err = os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("创建锁目录失败: %w", err)
	}

	lockPath := filepath.Join(dir, fmt.Sprintf("%s.lock", nodeID))

	// 锁文件存在且 PID 存活 → 已有实例在运行
	if data, rerr := os.ReadFile(lockPath); rerr == nil {
		var pid int
		if _, perr := fmt.Sscanf(string(data), "%d", &pid); perr == nil && pid > 0 {
			if processAlive(pid) {
				return nil, fmt.Errorf("节点 %s 已有实例在运行 (PID %d)，请勿重复启动", nodeID, pid)
			}
		}
	}

	// 写入当前 PID 获取锁
	if werr := os.WriteFile(lockPath, []byte(fmt.Sprintf("%d\n", os.Getpid())), 0644); werr != nil {
		return nil, fmt.Errorf("写入锁文件失败: %w", werr)
	}

	release = func() {
		// 仅当锁仍属于本进程时才删除，避免误删后来实例的锁
		if data, rerr := os.ReadFile(lockPath); rerr == nil {
			var pid int
			if _, perr := fmt.Sscanf(string(data), "%d", &pid); perr == nil && pid == os.Getpid() {
				os.Remove(lockPath)
			}
		}
	}
	return release, nil
}

// processAlive 检查 PID 对应的进程是否存活（Unix：signal 0 探测）。
func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	// signal 0 只探测存在性，不发送信号
	return proc.Signal(syscall.Signal(0)) == nil
}
