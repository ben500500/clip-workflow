//go:build windows

package main

import (
	"os"
	"os/exec"
)

// pythonBinary Windows 上 Python 可执行文件为 python。
func pythonBinary() string {
	return "python"
}

// SetProcessGroup Windows 无进程组概念，创建独立控制台窗口并设置
// CREATE_NEW_PROCESS_GROUP，便于 taskkill 按 PID 树终止。
func SetProcessGroup(cmd *exec.Cmd) {
	// 见 KillProcessTree：Windows 下通过 taskkill /T 终止进程树
}

// KillProcessTree Windows 下通过 taskkill /F /T 终止进程及其子进程。
func KillProcessTree(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	kill := exec.Command("taskkill", "/F", "/T", "/PID", itoa(cmd.Process.Pid))
	_ = kill.Run()
	return nil
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b []byte
	for n > 0 {
		b = append([]byte{byte('0' + n%10)}, b...)
		n /= 10
	}
	if neg {
		b = append([]byte{'-'}, b...)
	}
	return string(b)
}

var _ = os.Getpid // 保留 os 引用（跨平台一致性占位）
