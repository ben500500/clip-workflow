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
#   6. 根 docker-compose.yml 必须单独同步 —— SYNC_DIRS 只同步「目录」，根文件不在其中，
#      于是服务器上长出了仓库里没有的 worker-wechat-dl（2026-09-14 发现）。现由
#      SYNC_FILES 补同步，并在同步后用 md5 对账硬校验，不一致直接中止部署。
#   7. backend/ 变更的重建名单从 compose 自动推导，不再硬编码 —— 硬编码必然漏掉
#      新增 worker（worker-wechat-dl 就是这么漏的）。
#   8. 变量展开一律写 ${var}。脚本里中文/全角标点很多，而本机是 bash 3.2：在 C locale
#      （后台/非交互执行时 LANG 常常没继承）下它会把 >=0x80 的字节当作标识符字符，
#      于是「裸展开紧跟全角逗号」会被解析成变量名里带着 `）` 的标识符，
#      set -u 直接报未绑定并中止部署。（同类隐患：healthcheck.sh / init_admin.sh /
#      refresh_pingyue_roster.sh / server-setup.sh 各有 1~4 处，非本次范围。）
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

# 根级散落文件同步（不在任何 SYNC_DIRS 里，必须单列，否则会与仓库漂移）
SYNC_FILES=(docker-compose.yml)

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

# 单文件同步（根 compose 等散落文件）
sync_file() {
  local f="$1"
  if [ ! -f "$LOCAL_DIR/$f" ]; then
    log "跳过不存在的本地文件: $f"
    return
  fi
  log "同步 $f -> $REMOTE_HOST:$REMOTE_DIR/$f"
  tar czf - -C "$LOCAL_DIR" "$f" \
    | ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && tar xzf -" \
    || die "同步 $f 失败"
}

# 可移植 md5（macOS 自带的是 md5，无 md5sum）
file_md5() {
  if command -v md5sum >/dev/null 2>&1; then
    md5sum "$1" | awk '{print $1}'
  else
    md5 -q "$1"
  fi
}

# 从 compose 推导「运行 clip-backend:latest 镜像」的服务集合 —— 也就是 backend/ 代码
# 变更后必须重建的容器。以 compose 为唯一事实来源，避免硬编码名单随新增 worker 失效。
compose_backend_image_services() {
  awk '
    /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { svc=$1; sub(/:$/, "", svc); anc[svc]=0; img[svc]=""; order[++n]=svc }
    /<<: \*celery-worker-base/        { anc[svc]=1 }
    /^    image:[[:space:]]/          { img[svc]=$2 }
    END {
      for (i=1;i<=n;i++) { s=order[i]
        if (img[s]=="clip-backend:latest")                 print s
        else if (anc[s]==1 && img[s]=="")                   print s
      }
    }
  ' "$LOCAL_DIR/docker-compose.yml"
}

# 兜底名单：compose 解析异常时使用（正常路径永不依赖它）
BACKEND_CORE_SERVICES="backend worker-video worker-variant worker-publish worker-selection worker-fast worker-wechat-dl beat"

# backend/ 变更的重建名单。alembic-migrate 虽跑同一镜像，但它是一次性迁移容器，
# 只跟随 alembic/ 变更重建，故排除。
backend_rebuild_services() {
  local list
  list="$(compose_backend_image_services | grep -vx 'alembic-migrate' | tr '\n' ' ')"
  case " $list " in
    *" backend "*)
      echo "$list"
      ;;
    *)
      log "WARN: 无法从 compose 解析 backend 镜像服务，回退到内置名单"
      echo "$BACKEND_CORE_SERVICES"
      ;;
  esac
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
  # backend/ 变更 —— 名单从 compose 推导（所有跑 clip-backend:latest 的容器）
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^backend/'; then
    svc="$svc $(backend_rebuild_services)"
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

# 3. 同步受影响目录（整目录，避免半同步）+ 根级散落文件
if [ "$DRY_RUN" = "1" ]; then
  log "[dry-run] 将同步目录: ${SYNC_DIRS[*]}"
  log "[dry-run] 将同步文件: ${SYNC_FILES[*]}"
else
  # 3.1 覆盖前先探测服务器侧根 compose 是否被手改过 —— 只告警，仓库是唯一事实来源。
  #     如果不报出来，漂移会被静默抹平，下次就再也发现不了「服务器上到底跑的是什么」。
  _pre_lmd5="$(file_md5 "$LOCAL_DIR/docker-compose.yml")"
  _pre_rmd5="$(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "md5sum '$REMOTE_DIR/docker-compose.yml' 2>/dev/null | awk '{print \$1}'")"
  if [ -n "$_pre_rmd5" ] && [ "$_pre_lmd5" != "$_pre_rmd5" ]; then
    log "WARN: 服务器根 compose 与仓库不一致（local=${_pre_lmd5} remote=${_pre_rmd5}），即将用仓库版本覆盖"
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cat '$REMOTE_DIR/docker-compose.yml'" > /tmp/.deploy_remote_compose.yml 2>/dev/null \
      && diff -u "$LOCAL_DIR/docker-compose.yml" /tmp/.deploy_remote_compose.yml | head -40
  fi

  for d in "${SYNC_DIRS[@]}"; do
    sync_dir "$d"
  done
  for f in "${SYNC_FILES[@]}"; do
    sync_file "$f"
  done
  log "全部目录 + 根文件同步完成"

  # 3.2 同步后硬校验：必须逐字节一致 + compose 语法可解析。这两条是「配置漂移」的
  #     最后一道闸 —— 漂移的表现是「代码改了但容器行为没变」，极难排查。宁可中止部署。
  _lmd5="$(file_md5 "$LOCAL_DIR/docker-compose.yml")"
  _rmd5="$(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "md5sum '$REMOTE_DIR/docker-compose.yml' | awk '{print \$1}'")"
  if [ "$_lmd5" != "$_rmd5" ]; then
    die "根 compose 同步后仍与本地不一致（local=${_lmd5} remote=${_rmd5}），中止部署"
  fi
  log "根 compose 与本地一致（md5=${_lmd5}）"
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose config -q" \
    || die "docker compose config 语法校验失败"
  log "compose 服务清单: $(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose config --services | sort | tr '\n' ' '")"
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
  log "[dry-run] 将执行 db_sync_columns 补齐数据库列 + 跳过验证步骤"
else
  # 4.5 部署后补齐 ORM-DB 列差异（防 cnb 加列但 alembic 迁移链跳过导致接口 500）
  log "补齐数据库缺失列 (db_sync_columns)..."
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose cp scripts/db_sync_columns.py backend:/app/db_sync_columns.py && docker compose exec -T backend python /app/db_sync_columns.py" 2>&1 | grep -vE "warning|INFO:|level=" | tail -8

  log "等待容器就绪..."
  sleep 5
  if [ -n "$SERVICES" ]; then
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose ps $SERVICES" 2>&1 | tail -20
    log "校验最近错误日志..."
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose logs --since 2m $SERVICES 2>&1 | grep -iE 'error|traceback|panic|undefined|exception' | tail -10 || true"
  fi

  # 6. 记录本次部署 commit（本地 + 远端标记同步，避免两侧失配）
  git -C "$LOCAL_DIR" rev-parse HEAD > "$LAST_FILE"
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "echo -n \"$(cat "$LAST_FILE")\" > '$REMOTE_DIR/.deploy_last_commit'" \
    || log "WARN: 远端部署标记写入失败（不影响部署）"
  log "部署完成 ✅  (commit $(cat "$LAST_FILE"))"

  # 7. 自动清理 Docker 垃圾（悬空镜像 + 构建缓存）——每次部署 --build 会产生
  #    新镜像覆盖旧 tag，旧镜像层变 <none> 悬空；BuildKit 缓存默认不自动清，
  #    几天就累积数十 GB（2026-08-19 实测 39 悬空镜像 + 10.5GB 缓存）。
  #    在部署成功后顺带清理，避免手工运维。
  log "自动清理 Docker 垃圾（悬空镜像 + 构建缓存）..."
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker image prune -f 2>&1 | tail -2; docker builder prune -f 2>&1 | tail -2" \
    || log "WARN: Docker 垃圾清理失败（不影响部署）"
fi
