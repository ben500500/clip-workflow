# Clip Workflow — 远程 Slice Worker 节点部署包 (v2)

在任意机器上部署 clip-workflow 的分布式切片 Worker 节点。节点从服务器 Redis 队列领取切片任务，执行完回调后端。**节点本地不需要安装 Redis**，只需网络可达服务器。

## 目录结构

```
remote-worker/
├── deploy_remote_worker.sh    # 一键部署脚本 (v2)
├── slice-worker/              # Go Worker 源码 + Dockerfile (仓库根目录)
├── engines/                   # 切片引擎 (仓库根目录)
├── base-images-arm64.tar.gz   # arm64 基础镜像 (golang+alpine, 可选)
└── base-images-amd64.tar.gz   # amd64 基础镜像 (可选)
```

基础镜像包约 140MB，不进 git。需要时从已配置加速器的服务器导出：

```bash
# 服务器上执行 (服务器可访问 Docker Hub / 镜像加速器)
docker pull --platform linux/arm64 golang:1.22-alpine && docker pull --platform linux/arm64 alpine:3.19
docker save golang:1.22-alpine alpine:3.19 | gzip > base-images-arm64.tar.gz
docker pull --platform linux/amd64 golang:1.22-alpine && docker pull --platform linux/amd64 alpine:3.19
docker save golang:1.22-alpine alpine:3.19 | gzip > base-images-amd64.tar.gz
```

不提供基础镜像包时脚本会使用本机已有镜像构建（需 Docker Hub 或加速器可达）。

## 快速部署（Docker 模式，推荐）

```bash
cd remote-worker
./deploy_remote_worker.sh
```

脚本自动完成：生成节点 ID（`slice-worker-本机名缩写`）→ 检测服务器连通 → 自动获取 Redis 密码（SSH 免密可用时）→ 加载包内基础镜像 → 构建 → 启动节点。

```bash
docker logs -f slice-worker-<本机名>   # 看日志，出现"节点注册成功"即上线
```

## 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--node-id` | 节点 ID，全局唯一 | 自动生成 `slice-worker-<本机名缩写>` |
| `--server-ip` | 服务器 IP | 192.168.1.163 |
| `--server-ssh-user` | 服务器 SSH 用户（自动读密码用） | cc12703 |
| `--max-concurrent` | 节点并发切片数 | 2 |
| `--bare` | 裸机模式（需要本机 Go） | docker 模式 |

环境变量：`REDIS_PASSWORD`（设置了就用它，否则 SSH 自动获取或交互输入）、`REDIS_PORT`（默认 6379）、`SERVER_IP`。

## 特性说明（v2）

1. **基础镜像内置**：golang/alpine 基础镜像打包在部署包内，脚本按本机架构自动 `docker load`，构建不依赖 Docker Hub（解决国内网络拉镜像超时）
2. **节点 ID 自动生成**：`slice-worker-<hostname 前12位字母数字>`
3. **Redis 密码自动获取**：本机对服务器 SSH 免密时自动读取服务器 `.env`；否则交互输入
4. **前提检测**：Docker 模式检查 docker + 网络可达 6379/80；裸机模式检查 go + ffmpeg + python3
5. **原生架构**：包内基础镜像为 arm64/amd64 双架构，本机构建产物为原生架构（无模拟开销）

## 裸机模式（无需 Docker）

```bash
./deploy_remote_worker.sh --bare --node-id my-node-1
```

## 验证

1. 服务器：`docker exec clip-redis redis-cli -a <密码> --no-auth-warning smembers slice:nodes:online` 能看到新节点
2. 前端 /workers 页面能看到新节点（10s 轮询）
3. 跑一条切片任务看节点是否抢单

## 注意事项

- 需要能访问服务器端口：6379（Redis）、80（后端回调）、9000（MinIO 预签名 URL）
- 服务器需已配置：redis/minio 端口对外（0.0.0.0）+ `.env` 中 `MINIO_EXTERNAL_ENDPOINT` 指向服务器 IP
- Redis/MinIO 按内网使用开放，确认部署环境网络可信
