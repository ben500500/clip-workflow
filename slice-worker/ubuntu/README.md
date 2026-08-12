# Clip Workflow — Ubuntu 节点部署包

为 **Ubuntu 20.04 / 22.04 / 24.04**（x86_64 / arm64）准备的 Slice Worker 分布式切片节点部署包。

本部署包将你的 Ubuntu 机器注册为 Clip Workflow 的分布式切片 Worker 节点，可被服务器调度执行视频切片任务。

## 特性

- **免 Go 工具链**：随包附带预编译二进制（`slice-worker-linux-<arch>`），无需在 Ubuntu 上安装 Go。
- **systemd 托管**：开机自启、崩溃自动重启、`journalctl` 查看日志。
- **自动装依赖**：缺 ffmpeg / python3-opencv / fonttools 时自动 `apt` 安装。
- **支持引擎推送更新**：服务器端修改引擎脚本后，可在 Worker 节点管理页点「推送更新」在线下发，无需重新部署节点。

## 目录结构

```
clip-slice-worker-ubuntu-<arch>-<version>/
├── slice-worker-linux-<arch>     # 预编译 Worker 二进制
├── engines/                      # 引擎脚本（slice.py / vert2horiz_crop.py 等）
├── deploy_ubuntu.sh              # 一键部署脚本
├── clip-slice-worker.service.in  # systemd 服务模板
└── README.md                     # 本说明
```

## 快速部署

```bash
# 1. 解压
tar xzf clip-slice-worker-ubuntu-amd64-v3.0.0.tar.gz
cd clip-slice-worker-ubuntu-amd64-v3.0.0

# 2. 一键部署（交互式输入服务器 IP / Redis 密码）
sudo ./deploy_ubuntu.sh

# 或非交互式
sudo ./deploy_ubuntu.sh \
  --server-ip 192.168.1.163 \
  --redis-password '你的Redis密码' \
  --node-id ubuntu-1 \
  --max-concurrent 2 \
  --cpu-percent 50
```

部署完成后：
- 节点 ID：`slice-worker-<主机名前12位>`（可用 `--node-id` 指定）
- 安装目录：`/opt/clip-worker`
- systemd 服务名：`clip-slice-worker`

## 常用操作

```bash
sudo ./deploy_ubuntu.sh --status       # 查看运行状态 + 最近日志
sudo ./deploy_ubuntu.sh --restart      # 重启 worker
sudo ./deploy_ubuntu.sh --uninstall    # 卸载（停止并移除 systemd 服务）
journalctl -u clip-slice-worker -f     # 实时查看日志
```

## 修改配置

编辑 `/opt/clip-worker/worker.json` 后重启生效：

```bash
sudo systemctl restart clip-slice-worker
```

常用配置项：
- `node_id`：节点 ID
- `redis_url`：服务器 Redis 连接串（`redis://:密码@服务器IP:6379/0`）
- `backend_url`：后端地址（`http://服务器IP`，用于心跳/回调/推送更新）
- `max_concurrent`：最大并发任务数
- `cpu_percent`：切片时 CPU 资源分配比例（1~100）
- `engines_path`：引擎脚本目录（默认 `/opt/clip-worker/engines`）

## 引擎推送更新

服务器端修改引擎脚本后：
1. 在 **Worker 节点管理** 页找到该节点，点 **推送更新**。
2. 节点 Worker 会自动从服务器拉取最新引擎包并替换本地 `engines/`，无需重新部署/重启。

## 前置要求

- Ubuntu 20.04+（Debian 系亦可，systemd 需可用）
- 能访问服务器 6379（Redis）与 80（后端）端口
- 节点本地**无需**安装 Redis，只需网络可达服务器

## 从源码重新打包（可选）

若需为其他架构/版本重新生成部署包，在有 Go 1.22+ 的环境执行：

```bash
cd slice-worker/ubuntu
./build_package.sh --arch amd64 --version v3.0.0   # 或 --all 同时构建双架构
```
