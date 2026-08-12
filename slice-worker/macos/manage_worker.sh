#!/bin/bash
# =============================================================================
# Slice Worker (macOS) 管理脚本 — 手动启停 / 状态查询 / 开机自启切换
#
# 用法:
#   ./manage_worker.sh start          # 手动启动（托盘模式）
#   ./manage_worker.sh stop           # 停止 worker（含 launchd 自启实例）
#   ./manage_worker.sh status         # 查看运行状态
#   ./manage_worker.sh autostart-on   # 注册开机自启（launchd）
#   ./manage_worker.sh autostart-off  # 取消开机自启
#   ./manage_worker.sh restart        # 重启
#
# 说明:
#   - 部署目录 = 本脚本所在目录（worker.json / slice-worker-mac 同目录）
#   - launchd plist 使用 ~/Library/LaunchAgents/com.clip.workflow.worker.plist
#   - 新版 macOS 用 launchctl bootstrap/bootout（load/unload 已废弃）
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$DIR/slice-worker-mac"
CFG="$DIR/worker.json"
PLIST="$HOME/Library/LaunchAgents/com.clip.workflow.worker.plist"
LABEL="com.clip.workflow.worker"
NODE_ID="$(python3 -c "import json;print(json.load(open('$CFG'))['node_id'])" 2>/dev/null || echo unknown)"

log() { echo -e "\033[32m[INFO]\033[0m $1"; }
die()  { echo -e "\033[31m[ERROR]\033[0m $1" >&2; exit 1; }

[[ -x "$BIN" ]] || die "找不到 $BIN，请先确认部署目录完整"
[[ -f "$CFG" ]] || die "找不到 $CFG"

cmd="${1:-status}"

case "$cmd" in
  start)
    # 先停 launchd 实例（避免单实例锁冲突）
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    pkill -f "slice-worker-mac.*--tray" 2>/dev/null || true
    pkill -f "slice-worker-mac.*--no-tui" 2>/dev/null || true
    sleep 1
    rm -f "$DIR/temp/${NODE_ID}.lock" 2>/dev/null || true
    nohup "$BIN" --config "$CFG" --tray >> "$DIR/worker.log" 2>&1 &
    echo $! > "$DIR/worker.pid"
    sleep 2
    if kill -0 "$(cat "$DIR/worker.pid")" 2>/dev/null; then
      log "worker 已启动 (PID $(cat "$DIR/worker.pid"), 托盘模式, 节点 $NODE_ID)"
      log "菜单栏出现 Slice Worker 图标；日志: $DIR/worker.log"
    else
      die "worker 启动失败，请查看日志 $DIR/worker.log"
    fi
    ;;
  stop)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    pkill -f "slice-worker-mac.*--tray" 2>/dev/null || true
    pkill -f "slice-worker-mac.*--no-tui" 2>/dev/null || true
    rm -f "$DIR/worker.pid" "$DIR/temp/${NODE_ID}.lock" 2>/dev/null || true
    log "worker 已停止"
    ;;
  status)
    if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
      echo "开机自启: 已注册 (launchd)"
    else
      echo "开机自启: 未注册"
    fi
    if pgrep -f "slice-worker-mac.*(${NODE_ID}|--tray|--no-tui)" >/dev/null 2>&1; then
      echo "运行状态: 运行中"
      pgrep -fl "slice-worker-mac" | head -3
    else
      echo "运行状态: 未运行"
    fi
    ;;
  autostart-on)
    [[ -f "$DIR/com.clip.workflow.worker.plist" ]] || \
      die "缺少 plist 模板（$DIR/com.clip.workflow.worker.plist），请从部署包获取或手动创建"
    sed "s|__WORKER_DIR__|$DIR|g" "$DIR/com.clip.workflow.worker.plist" > "$PLIST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    log "开机自启已注册（下次登录自动启动）"
    sleep 2
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && log "launchd 任务已加载"
    ;;
  autostart-off)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    log "开机自启已取消"
    ;;
  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;
  *)
    echo "用法: $0 {start|stop|status|autostart-on|autostart-off|restart}"
    exit 1
    ;;
esac
