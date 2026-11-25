#!/usr/bin/env bash
# =============================================================================
# Clip Workflow 分布式切片节点启动脚本（Linux / macOS 通用）
#
# 前置要求：
#   1. Python 3.10+（引擎为纯标准库，无需 pip 装包；3.14 可用）
#   2. ffmpeg（需含 libx264 + aac；要接字幕烧录任务还需 libass）
#
# 用法：
#   ./start-worker.sh --node-id my-node-1 --server-ip 192.168.1.163 --redis-password XXX
#   ./start-worker.sh --python /path/to/python3.12   # 指定解释器（默认取 PATH 里的 python3）
#
# 参数会写入本目录 worker.json；再次运行同命令即按该配置重启节点。
# =============================================================================
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE_ID="slice-worker-$(hostname 2>/dev/null | tr -cd 'A-Za-z0-9' | cut -c1-10 | tr 'A-Z' 'a-z')"
SERVER_IP="192.168.1.163"
REDIS_PASSWORD=""
MAX_CONCURRENT=1
PRODUCT_CONCURRENCY="${SLICE_PRODUCT_CONCURRENCY:-1}"
CPU_PERCENT=50
PYTHON_BIN="${SLICE_PYTHON:-$(command -v python3 || echo python3)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --node-id) NODE_ID="$2"; shift 2;;
    --server-ip) SERVER_IP="$2"; shift 2;;
    --redis-password) REDIS_PASSWORD="$2"; shift 2;;
    --max-concurrent) MAX_CONCURRENT="$2"; shift 2;;
    --product-concurrency) PRODUCT_CONCURRENCY="$2"; shift 2;;
    --cpu-percent) CPU_PERCENT="$2"; shift 2;;
    --python) PYTHON_BIN="$2"; shift 2;;
    *) echo "未知参数: $1"; exit 1;;
  esac
done

"$PYTHON_BIN" --version

cat > "$DIR/worker.json" <<EOF
{
  "node_id": "$NODE_ID",
  "redis_url": "redis://:${REDIS_PASSWORD}@${SERVER_IP}:6379/0",
  "tags": ["cpu"],
  "max_concurrent": $MAX_CONCURRENT,
  "engines_path": "$DIR/engines",
  "temp_dir": "$DIR/temp",
  "log_level": "info",
  "heartbeat_interval": 10,
  "task_timeout": 21600,
  "max_retries": 2,
  "retry_delay": 30,
  "backend_url": "http://$SERVER_IP",
  "cpu_percent": $CPU_PERCENT,
  "product_concurrency": $PRODUCT_CONCURRENCY,
  "stuck_task_minutes": 30,
  "enable_direct_queue": true,
  "direct_queue_timeout": 2
}
EOF
mkdir -p "$DIR/temp"

export SLICE_PYTHON="$PYTHON_BIN"
echo "启动节点 $NODE_ID（日志: $DIR/worker.log，Ctrl+C 退出并注销节点）"
cd "$DIR"
exec ./slice-worker --config "$DIR/worker.json" --no-tui
