#!/usr/bin/env bash
#
# deploy_server.sh — 把本地 clip-workflow 代码一键同步到生产服务器并重建受影响容器
#
# 设计要点（踩坑固化）:
#   1. 同步必须用「本地 tar | ssh tar xzf -」管道，绝不在 ssh 单引号内自打包自解压
#      （否则等于没传文件，重建后还是旧代码 —— 已踩过）。
#   2. 对受影响目录做「整目录完整同步」，避免只同步 diff 文件导致「半同步」——
#      slice-worker 的 task_executor.go 引用了 redis_client.go 的结构体字段，
#      只同步前者会让 Go 编译失败 (undefined: task.SubtitleMask) —— 已踩过。
#   3. engines/slice.py 是只读 bind mount，同步即生效，无需重建。
#   4. 用 git diff 智能判定本次改了哪些目录，只重建对应容器，省去无谓的全量重建。
#   5. 重建后做容器健康 + 错误日志冒烟校验。
#
set -uo pipefail

# ============ 配置（可用环境变量覆盖） ============
REMOTE_USER="${DEPLOY_REMOTE_USER:-cc12703}"
REMOTE_HOST="${DEPLOY_REMOTE_HOST:-192.168.1.163}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/cc12703/clip-workflow}"
LOCAL_DIR="${DEPLOY_LOCAL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SSH_OPTS="${DEPLOY_SSH_OPTS:--o StrictHostKeyChecking=no -o BatchMode=yes}"

# 整目录同步（消除半同步）
SYNC_DIRS=(backend slice-worker frontend engines alembic deploy scripts autoclip)

# 是否先拉取 cnb 更新（git fetch + ff-only merge + 推 GitHub）
PULL_CNB="${DEPLOY_PULL_CNB:-1}"

# 强制全量重建（忽略 git diff，默认关）
FORCE_ALL="${DEPLOY_FORCE_ALL:-0}"

# 干跑：只打印将要执行的操作，不实际同步/重建
DRY_RUN=0
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY_RUN=1 ;;
    --no-pull)    PULL_CNB=0 ;;
    --all)        FORCE_ALL=1 ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
  esac
done

# ============ 函数 ============
log()  { echo "[$(date +%H:%M:%S)] $*"; }
die()  { echo "[$(date +%H:%M:%S)] ERROR: $*" >&2; exit 1; }

# 整目录打包并管道传到服务器解压（正确写法）
sync_dir() {
  local dir="$1"
  if [ ! -d "$LOCAL_DIR/$dir" ]; then
    log "跳过不存在的本地目录: $dir"
    return
  fi
  log "同步 $dir -> $REMOTE_HOST:$REMOTE_DIR/$dir"
  tar czf - \
    --exclude='node_modules' --exclude='dist' --exclude='build' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
    --exclude='.git' \
    --exclude='slice-worker/ubuntu' --exclude='slice-worker/macos' --exclude='slice-worker/windows' \
    --exclude='slice-worker/slice-worker' --exclude='slice-worker/slice-worker.exe' \
    -C "$LOCAL_DIR" "$dir" \
    | ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && tar xzf -" \
    || die "同步 $dir 失败"
}

# 根据 git diff 判定需要重建的服务（去重）
compute_services() {
  local prev="$1"
  local changed
  if [ "$FORCE_ALL" = "1" ]; then
    changed="ALL"
  elif [ -n "$prev" ] && git -C "$LOCAL_DIR" cat-file -e "$prev^{commit}" 2>/dev/null; then
    changed=$(git -C "$LOCAL_DIR" diff --name-only "$prev" HEAD 2>/dev/null) || changed="ALL"
    [ -z "$changed" ] && changed="_none_"
  else
    changed="ALL"
  fi

  local svc=""
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^backend/'; then
    svc="$svc backend worker-video worker-publish worker-fast beat rpa_worker"
  fi
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^frontend/'; then
    svc="$svc frontend"
  fi
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^slice-worker/'; then
    svc="$svc slice-worker slice-worker-2"
  fi
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^autoclip/'; then
    svc="$svc autoclip"
  fi
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^alembic/'; then
    svc="$svc alembic-migrate"
  fi

  # 去重并输出
  if [ "$changed" = "_none_" ]; then
    echo ""
  else
    echo "$svc" | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' '
  fi
}

# ============ 主流程 ============
log "本地仓库: $LOCAL_DIR"
log "目标服务器: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"

# 0. 基础连通性
ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "test -d '$REMOTE_DIR'" \
  || die "服务器部署目录不存在: $REMOTE_DIR"

LAST_FILE="$LOCAL_DIR/.deploy_last_commit"
PREV=""
[ -f "$LAST_FILE" ] && PREV="$(cat "$LAST_FILE")"

# 1. 可选：拉取 cnb 更新
if [ "${PULL_CNB}" = "1" ]; then
  log "拉取 cnb/main 更新..."
  git -C "$LOCAL_DIR" fetch cnb 2>&1 | tail -2 || die "git fetch cnb 失败"
  if git -C "$LOCAL_DIR" merge cnb/main --ff-only 2>&1 | tail -3; then
    log "已快进合并 cnb/main"
  else
    log "WARN: ff-only 合并未执行（可能本地有未提交改动，将按当前 HEAD 部署）"
  fi
  git -C "$LOCAL_DIR" push origin main 2>&1 | tail -2 || log "WARN: 推送 GitHub 失败（不影响部署）"
fi

# 2. 判定受影响服务
SERVICES=$(compute_services "$PREV")
if [ -z "$SERVICES" ]; then
  log "git diff 无代码变更，无需重建容器（仍会同步文件）。"
  SERVICES=""
else
  log "需重建容器: $SERVICES"
fi

# 3. 同步受影响目录（整目录，避免半同步）
if [ "$DRY_RUN" = "1" ]; then
  log "[dry-run] 将同步目录: ${SYNC_DIRS[*]}"
else
  for d in "${SYNC_DIRS[@]}"; do
    sync_dir "$d"
  done
  log "全部目录同步完成"
fi

# 4. 重建受影响容器
if [ -n "$SERVICES" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] 将重建容器: $SERVICES"
  else
    log "重建容器: $SERVICES"
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose up -d --build $SERVICES" \
      || die "docker compose 重建失败"
  fi
else
  log "跳过容器重建"
fi

# 5. 验证
if [ "$DRY_RUN" = "1" ]; then
  log "[dry-run] 跳过验证步骤"
else
  log "等待容器就绪..."
  sleep 5
  if [ -n "$SERVICES" ]; then
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose ps $SERVICES" 2>&1 | tail -20
    log "校验最近错误日志..."
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose logs --since 2m $SERVICES 2>&1 | grep -iE 'error|traceback|panic|undefined|exception' | tail -10 || true"
  fi

  # 6. 记录本次部署 commit
  git -C "$LOCAL_DIR" rev-parse HEAD > "$LAST_FILE"
  log "部署完成 ✅  (commit $(cat "$LAST_FILE"))"
fi
