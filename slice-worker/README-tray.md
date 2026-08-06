# Clip Workflow — Slice Worker 系统托盘（任务栏/菜单栏）使用说明

Slice Worker 分布式切片节点现在支持在 **Windows** 与 **macOS** 上以「系统托盘 / 菜单栏图标」方式运行：

- **Windows**：图标显示在任务栏右下角系统托盘区
- **macOS**：图标显示在屏幕顶部菜单栏（适配明暗外观）

托盘图标点开后可以：

| 功能 | 说明 |
|------|------|
| 查看节点状态 | 显示「在线 / 离线」状态，与后端 /workers 页面一致 |
| 调整 CPU 分配 | 菜单中可直接 +/- 调整本节点 CPU 资源分配比例（默认 50%），写入 Redis 后下次任务生效 |
| 启用 / 停用节点 | 直接写入 Redis 控制 key，与后端页面共用同一开关；停用后不再领取新任务（正在执行的不受影响） |
| 退出 Worker | 注销节点并退出程序 |

> 后台（Linux / 服务器 / 容器）仍使用原有 `--no-tui` 纯日志模式，不受影响。

---

## 一、Windows 端一键部署

### 1. 准备

在 Windows 机器上安装：

- **Python 3.10+**：<https://www.python.org/downloads/>（安装时勾选 Add to PATH）
- **FFmpeg**：<https://www.gyan.dev/ffmpeg/builds/>（解压后把 `bin` 目录加入 PATH）
- （可选，仅当目录中没有 `slice-worker.exe` 时需要）**Go 1.21+**：<https://go.dev/dl/>

### 2. 一键部署

把 `slice-worker/` 整个目录拷贝到 Windows 机器，双击运行：

```
slice-worker\windows\deploy_windows.bat
```

按提示输入：
- 服务器 IP / 域名
- Redis 密码（与服务器 `.env` 的 `REDIS_PASSWORD` 一致）

脚本自动完成：

1. 检测 python / ffmpeg / 网络连通性
2. 若没有 `slice-worker.exe`，自动用 Go 编译（首次会下载依赖，需几分钟）
3. 生成 `worker.json`（Redis 地址 / 节点 ID / 后端回调地址）
4. 以 **`--tray` 托盘模式**启动 Worker
5. 注册**开机自启**（当前用户注册表 HKCU\...\Run）

也可以带参数免交互部署：

```bat
deploy_windows.bat --server-ip 192.168.1.163 --redis-password 你的密码 --node-id win-1 --cpu-percent 50
```

### 3. 卸载

```
slice-worker\windows\uninstall_windows.bat          # 停止 + 取消开机自启
slice-worker\windows\uninstall_windows.bat --purge  # 同时删除程序/配置/临时文件
```

---

## 二、macOS 端（菜单栏状态）

macOS 菜单栏图标依赖 Cocoa，必须用 **cgo** 原生编译（不能 CGO_ENABLED=0 交叉编译）。

### 1. 准备

```bash
brew install go ffmpeg
```

### 2. 编译 + 启动

```bash
chmod +x slice-worker/macos/build_mac.sh
./slice-worker/macos/build_mac.sh --run --server-ip 192.168.1.163 --redis-password 你的密码 --cpu-percent 50
```

脚本会在本机编译出 `slice-worker/macos/slice-worker-mac`，生成 `worker.json`，并以 `--tray` 模式启动。菜单栏会出现 Slice Worker 图标。

### 3. 开机自启（登录项）

```bash
./slice-worker/macos/build_mac.sh --install --server-ip ... --redis-password ...
./slice-worker/macos/build_mac.sh --uninstall
```

---

## 三、实现说明

- 托盘实现使用 [`github.com/getlantern/systray`](https://github.com/getlantern/systray)（Windows 原生 Shell_NotifyIcon；macOS Cocoa）。
- 平台适配通过 build tag 隔离：
  - `tray_windows.go`（`//go:build windows`）
  - `tray_darwin.go`（`//go:build darwin && cgo`）+ `tray_darwin_nocgo.go`（无 cgo 时退化日志模式）
  - `tray_other.go`（Linux/服务器，无操作兜底）
- 进程管理平台化：`exec_unix.go`（进程组 SIGKILL）/ `exec_windows.go`（taskkill /T 杀进程树）。
- 启停节点与后端 `/workers/{id}/enable|disable` 共用同一个 Redis key `slice:node-enabled:{node_id}`，两端状态实时一致。
- CPU 分配比例与后端 `/workers/{id}/cpu-percent` 共用 `slice:node-cpu-percent:{node_id}`，托盘调整与 Web 页面调整实时一致；切片引擎按比例限制 ffmpeg 编码线程数（`threads = round(核数 × 比例 / 100)`），避免占满整机 CPU。

## 四、目录结构

```
slice-worker/
├── windows/
│   ├── deploy_windows.bat        # Windows 一键部署（托盘模式 + 开机自启）
│   └── uninstall_windows.bat     # Windows 卸载
├── macos/
│   └── build_mac.sh              # macOS 编译/启动/登录项脚本
├── icons/
│   ├── icon.ico                  # Windows 托盘图标（多尺寸）
│   ├── icon.png                  # 彩色图标
│   └── icon_template.png         # macOS Template 图标
├── tray.go / tray_common.go      # 托盘通用逻辑（状态/启停/轮询/退出）
├── tray_windows.go / tray_darwin.go / tray_other.go
├── exec_unix.go / exec_windows.go
└── ...
```
