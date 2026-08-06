#!/usr/bin/env bash
# =============================================================================
# Clip Workflow - macOS 端 Slice Worker 构建 + 启动脚本
#
# macOS 菜单栏状态图标依赖 Cocoa（cgo），因此必须用 cgo 构建（本机原生编译）。
# 本脚本在本机 macOS 上编译并启动，编译产物在 slice-worker/macos/slice-worker-mac。
#
# 用法:
#   ./build_mac.sh                     # 编译（需要 Go + ffmpeg + python3）
#   ./build_mac.sh --run               # 编译并启动（菜单栏托盘模式）
#   ./build_mac.sh --run --node-id mac-1 --server-ip 1.2.3.4 --redis-password xxx
#   ./build_mac.sh --install           # 编译并注册为登录项（开机自启，需要 AppleScript/登录项权限）
#   ./build_mac.sh --uninstall         # 取消登录项
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NODE_ID=""
SERVER_IP=""
REDIS_PASSWORD=""
REDIS_PORT=6379
MAX_CONCURRENT=2
CPU_PERCENT=50
ACTION="build"

while [[ $# -gt 0 ]]; do
    case $1 in
        --run) ACTION="run"; shift ;;
        --install) ACTION="install"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        --node-id) NODE_ID="$2"; shift 2 ;;
        --server-ip) SERVER_IP="$2"; shift 2 ;;
        --redis-password) REDIS_PASSWORD="$2"; shift 2 ;;
        --redis-port) REDIS_PORT="$2"; shift 2 ;;
        --max-concurrent) MAX_CONCURRENT="$2"; shift 2 ;;
        --cpu-percent) CPU_PERCENT="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $0 [--run|--install|--uninstall] [--node-id N] [--server-ip IP] [--redis-password P] [--redis-port PORT] [--max-concurrent N] [--cpu-percent N]"
            exit 0 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

log() { echo -e "\033[32m[INFO]\033[0m $1"; }
warn() { echo -e "\033[33m[WARN]\033[0m $1"; }
die()  { echo -e "\033[31m[ERROR]\033[0m $1" >&2; exit 1; }

# ==================== 卸载登录项 ====================
if [[ "$ACTION" == "uninstall" ]]; then
    if [[ -f "$SCRIPT_DIR/com.clip.workflow.worker.plist" ]]; then
        launchctl unload "$SCRIPT_DIR/com.clip.workflow.worker.plist" 2>/dev/null || true
        rm -f "$SCRIPT_DIR/com.clip.workflow.worker.plist"
    fi
    pkill -f "slice-worker.*--tray" 2>/dev/null || true
    log "已停止 Worker 并移除登录项"
    exit 0
fi

# ==================== 前置检查 ====================
log "=== 前置检查 ==="
command -v go >/dev/null 2>&1 || die "缺少 go，请先安装: brew install go"
command -v ffmpeg >/dev/null 2>&1 || warn "缺少 ffmpeg，请先安装: brew install ffmpeg"
command -v python3 >/dev/null 2>&1 || die "缺少 python3"

# macOS 必须 cgo 才能显示菜单栏图标
if [[ "$(go env CGO_ENABLED 2>/dev/null || echo 1)" == "0" ]]; then
    warn "CGO_ENABLED=0，菜单栏图标将不可用（退化为日志模式）。请用默认 cgo 构建。"
fi

# ==================== 编译 ====================
log "=== 编译 macOS Worker (cgo, 本机架构) ==="
mkdir -p "$SCRIPT_DIR"
OUT="$SCRIPT_DIR/slice-worker-mac"
CGO_ENABLED=1 go build -ldflags="-s -w" -o "$OUT" "$ROOT_DIR/slice-worker"
log "编译完成: $OUT"

if [[ "$ACTION" == "build" ]]; then
    echo ""
    log "编译完成！运行方式:"
    echo "  $0 --run --server-ip <服务器IP> --redis-password <密码>"
    exit 0
fi

# ==================== 交互输入（run/install） ====================
if [[ -z "$SERVER_IP" ]]; then
    read -rp "请输入服务器 IP/域名: " SERVER_IP
fi
[[ -z "$SERVER_IP" ]] && die "未提供服务器 IP"
if [[ -z "$REDIS_PASSWORD" ]]; then
    read -rsp "请输入 Redis 密码: " REDIS_PASSWORD
    echo ""
fi
[[ -z "$REDIS_PASSWORD" ]] && die "未提供 Redis 密码"
if [[ -z "$NODE_ID" ]]; then
    NODE_ID="slice-worker-$(hostname | tr -cd 'A-Za-z0-9' | cut -c1-12 | tr 'A-Z' 'a-z')"
fi

# ==================== 生成配置 ====================
mkdir -p "$SCRIPT_DIR/../temp"
cat > "$SCRIPT_DIR/worker.json" <<EOF
{
  "node_id": "$NODE_ID",
  "redis_url": "redis://:${REDIS_PASSWORD}@${SERVER_IP}:${REDIS_PORT}/0",
  "tags": ["cpu"],
  "max_concurrent": $MAX_CONCURRENT,
  "engines_path": "$ROOT_DIR/engines",
  "temp_dir": "$SCRIPT_DIR/../temp",
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
log "配置已生成: $SCRIPT_DIR/worker.json"

# ==================== 启动（菜单栏托盘） ====================
if [[ "$ACTION" == "run" ]]; then
    log "启动 Worker（菜单栏托盘模式）..."
    nohup "$OUT" --config "$SCRIPT_DIR/worker.json" --tray >> "$SCRIPT_DIR/slice-worker.log" 2>&1 &
    echo $! > "$SCRIPT_DIR/slice-worker.pid"
    sleep 2
    log "已启动 (PID $(cat "$SCRIPT_DIR/slice-worker.pid"))"
    log "菜单栏将出现 Slice Worker 图标，可查看状态/启停节点/退出"
    log "日志: $SCRIPT_DIR/slice-worker.log | 停止: $0 --uninstall 或 kill \$(cat slice-worker.pid)"
    exit 0
fi

# ==================== 注册登录项（开机自启） ====================
if [[ "$ACTION" == "install" ]]; then
    PLIST="$SCRIPT_DIR/com.clip.workflow.worker.plist"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.clip.workflow.worker</string>
    <key>ProgramArguments</key>
    <array>
        <string>$OUT</string>
        <string>--config</string>
        <string>$SCRIPT_DIR/worker.json</string>
        <string>--tray</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/slice-worker.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/slice-worker.log</string>
</dict>
</plist>
EOF
    launchctl load "$PLIST"
    log "已注册登录项（开机自启）: $PLIST"
    log "取消: $0 --uninstall"
    exit 0
fi
