#!/usr/bin/env bash
# =============================================================================
# Clip Workflow - Ubuntu 端 Slice Worker 一键部署脚本 (v1)
#
# 特点：
#   - 适配 Ubuntu 20.04 / 22.04 / 24.04（x86_64 / arm64）
#   - 无需本机 Go 工具链：优先使用随部署包附带的预编译二进制（slice-worker-linux-*），
#     缺失时才尝试用 Go 编译（需本机安装 go）。
#   - 自动安装/检测依赖：ffmpeg、python3、python3-opencv、python3-fonttools、curl
#   - 使用 systemd 管理：开机自启、崩溃自动重启、journalctl 查看日志
#   - 支持「引擎推送更新」：服务器端修改引擎脚本后可在线推送，无需重新部署
#
# 用法：
#   ./deploy_ubuntu.sh                              # 交互式部署
#   ./deploy_ubuntu.sh --server-ip 1.2.3.4 --redis-password xxx --node-id ubuntu-1
#   ./deploy_ubuntu.sh --uninstall                 # 卸载（停止并移除 systemd 服务）
#   ./deploy_ubuntu.sh --status                    # 查看节点运行状态
#
# 参数：
#   --server-ip IP       服务器 IP/域名（必填，部署后如需改动可编辑 worker.json 后重启服务）
#   --redis-password P   Redis 密码（与服务器 .env 的 REDIS_PASSWORD 一致）
#   --redis-port PORT    Redis 端口（默认 6379）
#   --node-id NAME       节点 ID（默认 slice-worker-<主机名前12位>）
#   --max-concurrent N   并发数（默认 2）
#   --cpu-percent N      CPU 分配比例 1~100（默认 50）
#   --install-dir DIR    安装目录（默认 /opt/clip-worker）
#   --no-deps            跳过依赖安装（仅检测）
#   --uninstall          卸载
#   --status             查看状态
#   --restart            重启 worker
#
# 依赖（自动检测，缺则用 apt 安装）：
#   ffmpeg python3 python3-opencv python3-fonttools curl
# =============================================================================
set -euo pipefail

INSTALL_DIR="/opt/clip-worker"
SERVER_IP=""
REDIS_PASSWORD=""
REDIS_PORT=6379
NODE_ID=""
MAX_CONCURRENT=2
CPU_PERCENT=50
DO_INSTALL_DEPS=1
ACTION="deploy"

# ==================== 参数解析 ====================
while [[ $# -gt 0 ]]; do
    case $1 in
        --server-ip) SERVER_IP="$2"; shift 2 ;;
        --redis-password) REDIS_PASSWORD="$2"; shift 2 ;;
        --redis-port) REDIS_PORT="$2"; shift 2 ;;
        --node-id) NODE_ID="$2"; shift 2 ;;
        --max-concurrent) MAX_CONCURRENT="$2"; shift 2 ;;
        --cpu-percent) CPU_PERCENT="$2"; shift 2 ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --no-deps) DO_INSTALL_DEPS=0; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        --status) ACTION="status"; shift ;;
        --restart) ACTION="restart"; shift ;;
        -h|--help)
            cat <<'EOF'
用法: $0 [--server-ip IP] [--redis-password P] [--node-id NAME]
         [--redis-port PORT] [--max-concurrent N] [--cpu-percent N]
         [--install-dir DIR] [--no-deps] [--uninstall] [--status] [--restart]

交互模式直接运行: $0
EOF
            exit 0 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="clip-slice-worker"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

log() { echo -e "\033[32m[INFO]\033[0m $1"; }
warn() { echo -e "\033[33m[WARN]\033[0m $1"; }
die()  { echo -e "\033[31m[ERROR]\033[0m $1" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "请以 root 运行（部署到 $INSTALL_DIR 并安装 systemd 服务需要 root 权限），可用: sudo $0"

# ==================== 卸载 ====================
if [[ "$ACTION" == "uninstall" ]]; then
    log "=== 卸载 Slice Worker ==="
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload 2>/dev/null || true
    pkill -f "slice-worker.*--no-tui" 2>/dev/null || true
    warn "已停止并移除 systemd 服务。安装目录 $INSTALL_DIR 保留（如需彻底删除: rm -rf $INSTALL_DIR）"
    exit 0
fi

# ==================== 状态查看 ====================
if [[ "$ACTION" == "status" ]]; then
    echo "=== Slice Worker 运行状态 ==="
    systemctl status "$SERVICE_NAME" --no-pager 2>&1 || true
    echo ""
    echo "最近日志 (journalctl -u $SERVICE_NAME -n 50):"
    journalctl -u "$SERVICE_NAME" -n 50 --no-pager 2>&1 || true
    exit 0
fi

# ==================== 重启 ====================
if [[ "$ACTION" == "restart" ]]; then
    systemctl restart "$SERVICE_NAME"
    log "已重启 $SERVICE_NAME"
    exit 0
fi

# ==================== 交互输入 ====================
if [[ -z "$SERVER_IP" ]]; then
    read -rp "请输入服务器 IP/域名: " SERVER_IP
fi
[[ -z "$SERVER_IP" ]] && die "未提供服务器 IP"
if [[ -z "$REDIS_PASSWORD" ]]; then
    read -rsp "请输入 Redis 密码（与服务器 .env 的 REDIS_PASSWORD 一致）: " REDIS_PASSWORD
    echo ""
fi
[[ -z "$REDIS_PASSWORD" ]] && die "未提供 Redis 密码"
if [[ -z "$NODE_ID" ]]; then
    HOST_SHORT="$(hostname | tr -cd 'A-Za-z0-9' | cut -c1-12 | tr 'A-Z' 'a-z')"
    NODE_ID="slice-worker-${HOST_SHORT:-local}"
fi

# ==================== 依赖检测/安装 ====================
log "=== 依赖检测 ==="
NEED_PKGS=""
for cmd in ffmpeg python3 curl; do
    command -v "$cmd" >/dev/null 2>&1 || NEED_PKGS="$NEED_PKGS $cmd"
done
# python3 模块检测
if ! python3 -c "import cv2" >/dev/null 2>&1; then
    NEED_PKGS="$NEED_PKGS python3-opencv"
fi
if ! python3 -c "import fontTools" >/dev/null 2>&1; then
    NEED_PKGS="$NEED_PKGS python3-fonttools"
fi

if [[ -n "$NEED_PKGS" ]]; then
    if [[ "$DO_INSTALL_DEPS" == "1" ]]; then
        log "检测到缺少依赖，将用 apt 安装:$NEED_PKGS"
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        # 用空格分隔的包名安装（去重）
        apt-get install -y -qq $NEED_PKGS
    else
        die "缺少依赖:$NEED_PKGS（已指定 --no-deps，请自行安装后重试）"
    fi
else
    log "依赖齐全"
fi

# ==================== 准备二进制 ====================
log "=== 准备 slice-worker 二进制 ==="
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) GOARCH="amd64" ;;
    aarch64|arm64) GOARCH="arm64" ;;
    *) die "不支持的架构: $ARCH" ;;
esac
BIN="$INSTALL_DIR/slice-worker"
mkdir -p "$INSTALL_DIR/engines" "$INSTALL_DIR/temp"

# 1) 优先用随包预编译二进制
PREBUILT=""
for cand in "$SCRIPT_DIR/slice-worker-linux-${GOARCH}" "$SCRIPT_DIR/slice-worker-linux"; do
    if [[ -x "$cand" ]]; then PREBUILT="$cand"; break; fi
done
if [[ -n "$PREBUILT" ]]; then
    log "使用随包预编译二进制: $PREBUILT"
    cp "$PREBUILT" "$BIN"
    chmod +x "$BIN"
# 2) 否则尝试用本机 Go 编译
elif command -v go >/dev/null 2>&1; then
    log "未找到预编译二进制，使用本机 Go 编译（需 go 1.22+）..."
    ( cd "$SCRIPT_DIR/.." && CGO_ENABLED=0 GOOS=linux GOARCH="$GOARCH" \
        go build -ldflags="-s -w" -o "$BIN" . )
    chmod +x "$BIN"
else
    die "未找到预编译二进制（slice-worker-linux-$GOARCH）且本机无 Go 工具链。请使用 build_package.sh 生成部署包，或在部署包目录放置编译好的 slice-worker-linux-$GOARCH"
fi

# ==================== 准备引擎 ====================
log "=== 准备引擎脚本 ==="
# 优先复制部署包内置的 engines/（若 build_package.sh 已打包），否则从源码目录复制
SRC_ENGINES="$SCRIPT_DIR/engines"
if [[ -d "$SRC_ENGINES" && -n "$(ls -A "$SRC_ENGINES" 2>/dev/null)" ]]; then
    cp -r "$SRC_ENGINES"/. "$INSTALL_DIR/engines/"
elif [[ -d "$SCRIPT_DIR/../../engines" ]]; then
    cp -r "$SCRIPT_DIR/../../engines"/. "$INSTALL_DIR/engines/"
else
    warn "未找到引擎脚本目录 engines/，请确认部署包完整或源码目录存在。切片任务将无法执行。"
fi

# ==================== 生成配置 ====================
log "=== 生成配置 worker.json ==="
cat > "$INSTALL_DIR/worker.json" <<EOF
{
  "node_id": "$NODE_ID",
  "redis_url": "redis://:${REDIS_PASSWORD}@${SERVER_IP}:${REDIS_PORT}/0",
  "tags": ["cpu"],
  "max_concurrent": $MAX_CONCURRENT,
  "engines_path": "$INSTALL_DIR/engines",
  "temp_dir": "$INSTALL_DIR/temp",
  "log_level": "info",
  "heartbeat_interval": 10,
  "task_timeout": 7200,
  "max_retries": 2,
  "retry_delay": 30,
  "node_ttl": 0,
  "backend_url": "http://${SERVER_IP}",
  "cpu_percent": $CPU_PERCENT
}
EOF
log "配置已生成: $INSTALL_DIR/worker.json"

# ==================== 安装 systemd 服务 ====================
log "=== 安装 systemd 服务 ==="
if [[ -f "$SCRIPT_DIR/clip-slice-worker.service.in" ]]; then
    sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$SCRIPT_DIR/clip-slice-worker.service.in" > "$SERVICE_FILE"
else
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Clip Workflow Slice Worker Node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/slice-worker --config $INSTALL_DIR/worker.json --no-tui
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 3

# ==================== 验证 ====================
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Slice Worker 已启动（节点 $NODE_ID, $INSTALL_DIR）"
    log "查看日志: journalctl -u $SERVICE_NAME -f | 状态: $0 --status | 重启: $0 --restart | 卸载: $0 --uninstall"
    log "节点 ID: $NODE_ID"
    # 输出最近日志供确认
    journalctl -u "$SERVICE_NAME" -n 10 --no-pager 2>&1 || true
else
    die "systemd 服务启动失败，请查看: journalctl -u $SERVICE_NAME -n 50"
fi
