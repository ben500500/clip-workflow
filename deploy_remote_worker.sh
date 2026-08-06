#!/usr/bin/env bash
# =============================================================================
# Clip Workflow - 远程 Slice Worker 节点一键部署脚本 (v2)
# 支持两种模式:
#   docker (默认): 构建镜像并运行容器 (自动加载包内基础镜像, 无需 Docker Hub)
#   bare   (裸机): 本机已有 ffmpeg+python3 时, 编译二进制直接运行
#
# 用法:
#   ./deploy_remote_worker.sh                          # 自动生成节点ID
#   ./deploy_remote_worker.sh --node-id mac-1          # 指定节点 ID
#   ./deploy_remote_worker.sh --bare                   # 裸机模式(需要本机 Go)
#
# 参数:
#   --node-id NAME        节点 ID (默认自动生成 slice-worker-<本机名缩写>)
#   --server-ip IP        服务器 IP (默认 192.168.1.163)
#   --server-ssh-user U   服务器 SSH 用户 (默认 cc12703, 用于自动读取 Redis 密码)
#   --max-concurrent N    并发数 (默认 2)
#   --bare                裸机模式
#
# 环境变量:
#   REDIS_PASSWORD  Redis 密码 (可自动从服务器获取, 见下)
#   REDIS_PORT      Redis 端口 (默认 6379)
#   SERVER_IP       服务器 IP (同 --server-ip)
#
# 说明: 节点本地不需要安装 Redis, 只需网络可达服务器 6379 端口
# =============================================================================
set -euo pipefail

# ==================== 默认参数 ====================
SERVER_IP="${SERVER_IP:-192.168.1.163}"
SERVER_SSH_USER="${SERVER_SSH_USER:-cc12703}"
REDIS_PORT="${REDIS_PORT:-6379}"
MAX_CONCURRENT="${MAX_CONCURRENT:-2}"
MODE="docker"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ==================== 自动生成节点 ID ====================
HOST_SHORT="$(hostname 2>/dev/null | tr -cd 'A-Za-z0-9' | cut -c1-12 | tr 'A-Z' 'a-z')"
NODE_ID="slice-worker-${HOST_SHORT:-local}"

# ==================== 参数解析 ====================
while [[ $# -gt 0 ]]; do
    case $1 in
        --node-id) NODE_ID="$2"; shift 2 ;;
        --server-ip) SERVER_IP="$2"; shift 2 ;;
        --server-ssh-user) SERVER_SSH_USER="$2"; shift 2 ;;
        --max-concurrent) MAX_CONCURRENT="$2"; shift 2 ;;
        --bare) MODE="bare"; shift ;;
        -h|--help)
            echo "用法: $0 [--node-id NAME] [--server-ip IP] [--server-ssh-user U] [--max-concurrent N] [--bare]"
            echo "节点 ID 默认自动生成: slice-worker-<本机名缩写>"
            exit 0 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

log() { echo -e "\033[32m[INFO]\033[0m $1"; }
warn() { echo -e "\033[33m[WARN]\033[0m $1"; }
die()  { echo -e "\033[31m[ERROR]\033[0m $1" >&2; exit 1; }

# ==================== 前置检查 ====================
log "=== 前置检查 ==="

# 1. 工具检测
MISSING=""
if [[ "$MODE" == "docker" ]]; then
    command -v docker >/dev/null 2>&1 || MISSING="$MISSING docker"
    command -v nc >/dev/null 2>&1 || MISSING="$MISSING nc"
else
    for cmd in go ffmpeg python3 nc; do
        command -v "$cmd" >/dev/null 2>&1 || MISSING="$MISSING $cmd"
    done
fi
[[ -n "$MISSING" ]] && die "缺少必需工具:$MISSING (裸机模式需 go+ffmpeg+python3, docker 模式需 docker)"

# 2. 网络连通性 (节点本地不需要 Redis, 只需网络可达)
log "检测服务器连通性 ($SERVER_IP)..."
if ! nc -zv -w 5 "$SERVER_IP" "$REDIS_PORT" >/dev/null 2>&1; then
    die "无法连通 $SERVER_IP:$REDIS_PORT (Redis), 请检查网络/服务器防火墙"
fi
log "Redis 端口可达: $SERVER_IP:$REDIS_PORT"
if ! nc -zv -w 5 "$SERVER_IP" 80 >/dev/null 2>&1; then
    warn "无法连通 $SERVER_IP:80 (后端回调), 任务结果可能无法回传"
fi

# 3. Redis 密码获取 (环境变量 -> 自动从服务器读取 -> 交互输入)
if [[ -z "${REDIS_PASSWORD:-}" ]]; then
    log "尝试自动从服务器读取 Redis 密码 (ssh ${SERVER_SSH_USER}@${SERVER_IP})..."
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "${SERVER_SSH_USER}@${SERVER_IP}" \
        "grep '^REDIS_PASSWORD=' /home/${SERVER_SSH_USER}/clip-workflow/.env 2>/dev/null | cut -d= -f2" \
        >/tmp/redis-pass.tmp 2>/dev/null && [[ -s /tmp/redis-pass.tmp ]]; then
        REDIS_PASSWORD="$(cat /tmp/redis-pass.tmp)"
        log "已从服务器自动获取 Redis 密码"
        rm -f /tmp/redis-pass.tmp
    else
        warn "SSH 免密不可用, 请手动输入 Redis 密码:"
        read -rs -p "REDIS_PASSWORD: " REDIS_PASSWORD
        echo ""
        [[ -z "$REDIS_PASSWORD" ]] && die "未提供 Redis 密码"
    fi
fi

# ==================== Docker 模式 ====================
if [[ "$MODE" == "docker" ]]; then
    docker info >/dev/null 2>&1 || die "Docker 不可用, 请启动 Docker 或改用 --bare"

    # 加载包内基础镜像 (按本机架构选择), 避免 Docker Hub 超时
    ARCH="$(uname -m)"
    case "$ARCH" in
        arm64|aarch64) BASE_IMG="base-images-arm64.tar.gz" ;;
        x86_64|amd64)  BASE_IMG="base-images-amd64.tar.gz" ;;
        *) warn "未知架构 $ARCH, 尝试直接构建 (可能需 Docker Hub 可达)" ; BASE_IMG="" ;;
    esac
    if [[ -n "$BASE_IMG" && -f "$SCRIPT_DIR/$BASE_IMG" ]]; then
        if docker image inspect golang:1.22-alpine >/dev/null 2>&1; then
            log "基础镜像已存在, 跳过加载"
        else
            log "加载包内基础镜像 ($BASE_IMG)..."
            docker load < "$SCRIPT_DIR/$BASE_IMG" | tail -2
        fi
    else
        warn "包内无基础镜像或已加载, 构建将使用本机已有镜像"
    fi

    log "构建 slice-worker 镜像 (本机架构 $ARCH)..."
    docker build -q -t clip-slice-worker "$SCRIPT_DIR/slice-worker" || \
        die "镜像构建失败, 请检查 Docker 网络(需可访问 goproxy.cn)或基础镜像"

    docker rm -f "$NODE_ID" >/dev/null 2>&1 || true
    log "启动节点 $NODE_ID (服务器 $SERVER_IP, 并发 $MAX_CONCURRENT)..."
    docker run -d --name "$NODE_ID" --restart unless-stopped \
        -e NODE_ID="$NODE_ID" \
        -e REDIS_URL="redis://:${REDIS_PASSWORD}@${SERVER_IP}:${REDIS_PORT}/0" \
        -e BACKEND_URL="http://${SERVER_IP}" \
        -e MAX_CONCURRENT="$MAX_CONCURRENT" \
        -e HEARTBEAT_INTERVAL="10" \
        -e LOG_LEVEL="info" \
        -e TASK_TIMEOUT="7200" \
        -e MAX_RETRIES="2" \
        -e RETRY_DELAY="30" \
        -e NODE_TTL="0" \
        -v "$SCRIPT_DIR/engines:/app/engines:ro" \
        clip-slice-worker >/dev/null

    log "节点已启动, 查看日志: docker logs -f $NODE_ID"
    sleep 6
    docker logs "$NODE_ID" --tail 8 || true
    echo ""
    log "部署完成! 节点: $NODE_ID | 架构: $(uname -m)"
    exit 0
fi

# ==================== 裸机模式 ====================
log "裸机模式: 编译 slice-worker 二进制..."
GOOS_ARCH="$(go env GOOS)/$(go env GOARCH)"
case "$GOOS_ARCH" in
    darwin/arm64) CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o "$SCRIPT_DIR/slice-worker-bin" "$SCRIPT_DIR/slice-worker" ;;
    darwin/amd64) CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -ldflags="-s -w" -o "$SCRIPT_DIR/slice-worker-bin" "$SCRIPT_DIR/slice-worker" ;;
    linux/amd64)  CGO_ENABLED=0 GOOS=linux  GOARCH=amd64 go build -ldflags="-s -w" -o "$SCRIPT_DIR/slice-worker-bin" "$SCRIPT_DIR/slice-worker" ;;
    linux/arm64)  CGO_ENABLED=0 GOOS=linux  GOARCH=arm64 go build -ldflags="-s -w" -o "$SCRIPT_DIR/slice-worker-bin" "$SCRIPT_DIR/slice-worker" ;;
    *) die "不支持的平台: $GOOS_ARCH" ;;
esac

log "生成 worker.json 配置..."
cat > "$SCRIPT_DIR/worker.json" <<EOF
{
  "node_id": "$NODE_ID",
  "redis_url": "redis://:${REDIS_PASSWORD}@${SERVER_IP}:${REDIS_PORT}/0",
  "tags": ["cpu"],
  "max_concurrent": $MAX_CONCURRENT,
  "engines_path": "$SCRIPT_DIR/engines",
  "temp_dir": "/tmp/slice-worker",
  "log_level": "info",
  "heartbeat_interval": 10,
  "task_timeout": 7200,
  "max_retries": 2,
  "retry_delay": 30,
  "node_ttl": 0,
  "backend_url": "http://${SERVER_IP}"
}
EOF

log "启动节点 $NODE_ID (后台运行)..."
nohup "$SCRIPT_DIR/slice-worker-bin" --config "$SCRIPT_DIR/worker.json" --no-tui \
    >> "$SCRIPT_DIR/slice-worker.log" 2>&1 &
echo $! > "$SCRIPT_DIR/slice-worker.pid"
sleep 3
tail -8 "$SCRIPT_DIR/slice-worker.log"
log "已启动 (PID $(cat "$SCRIPT_DIR/slice-worker.pid")), 停止: kill \$(cat slice-worker.pid)"
