//go:build !windows

package main

import (
	"os"
	"os/exec"
	"syscall"
)

// pythonBinary 返回平台对应的 Python 可执行文件名。
// Linux/Alpine（容器）与 macOS 提供 python3。
// 支持 SLICE_PYTHON 环境变量覆盖（如系统默认 python3 版本 < 3.10 时，
// 可通过 SLICE_PYTHON=/path/to/python3.11+ 指定，引擎要求 Python 3.10+）。
func pythonBinary() string {
	if p := os.Getenv("SLICE_PYTHON"); p != "" {
		return p
	}
	return "python3"
}

// SetProcessGroup 为子进程设置独立进程组（Unix），便于整体强杀。
func SetProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

// KillProcessTree 强杀整个进程组（含 ffmpeg 子进程）。
func KillProcessTree(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	pgid, err := syscall.Getpgid(cmd.Process.Pid)
	if err == nil {
		// 负 PID = 向整个进程组发送信号
		return syscall.Kill(-pgid, syscall.SIGKILL)
	}
	return cmd.Process.Kill()
}

var _ = os.Getpid // 保留 os 引用（跨平台一致性占位）
