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
#   3. engines/ 与两个消费方的生效方式不同，别搞混：
#        · slice-worker：镜像内 COPY → 必须重建（且重建前先在服务器跑
#          sync-engines-to-worker.sh 刷新被 .gitignore 的构建副本）；
#        · clip-backend：只读 bind mount → 同步即生效，但 uvicorn 无 --reload，
#          必须 restart 容器才会重新 import。两条现都由脚本自动处理（见第 4 步）。
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
#   9. rpa/ 已纳入同步（2026-09-15）：此前 163 上的 rpa/app/** 在仓库里不存在但
#      clip-rpa-worker 一直在跑 —— 服务器是唯一事实来源。已回仓 + 加映射 rpa/→rpa_worker。
#  10. 根级单文件如果是 bind mount 进容器的（nginx.conf → clip-nginx 的
#      /etc/nginx/conf.d/default.conf），文件同步完 **进程不会重读配置**，而它又不在任何
#      服务的构建上下文里 → 重建名单永远不含它 → 「日志全绿、现网没变」。现由第 4.6 步
#      按 mtime／内容变更两条判据自动 docker restart（Issue #244）。
#
set -uo pipefail

# ============ 配置（可用环境变量覆盖） ============
REMOTE_USER="${DEPLOY_REMOTE_USER:-cc12703}"
REMOTE_HOST="${DEPLOY_REMOTE_HOST:-192.168.1.163}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/cc12703/clip-workflow}"
LOCAL_DIR="${DEPLOY_LOCAL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SSH_OPTS="${DEPLOY_SSH_OPTS:--o StrictHostKeyChecking=no -o BatchMode=yes}"

# 整目录同步（消除半同步）
# ⚠️ rpa 于 2026-09-15 加入：此前 163 上的 rpa/app/**（8 个文件，含 celery_app/tasks/
#    publishers）在仓库里根本不存在，而 clip-rpa-worker 一直在跑 —— 典型的「服务器是
#    唯一事实来源」漂移。已于当日从 163 回仓（逐文件 md5 一致），并纳入同步防复发。
SYNC_DIRS=(backend slice-worker frontend engines alembic deploy scripts autoclip rpa docker remotion)
# ⚠️ docker / remotion 于 2026-11-11 加入（运维席 P1）：worker-remotion 的构建上下文是仓库根、
#    dockerfile 指向 docker/remotion-worker/Dockerfile，渲染源在 remotion/src。这两目录此前
#    **从不同步**，服务器那份是当初手工放的 —— 仓库改了 Dockerfile／渲染逻辑，现网永远不知道
#    （和上面 rpa、下面 nginx.conf 同一个病根：服务器变成唯一事实来源）。
#    只同步文件、**不纳入重建名单**：worker-remotion 被 compose profile 门控
#    （profiles: ["remotion"]），默认没启，`up -d --build worker-remotion` 会被 compose
#    判成 "service not enabled" 直接中断部署。真要启用时手工跑：
#      docker compose --profile remotion up -d --build worker-remotion

# 根级散落文件同步（不在任何 SYNC_DIRS 里，必须单列，否则会与仓库漂移）
# nginx.conf 是根级散落文件（不在 SYNC_DIRS 里）——2026-11-09 加 HTTPS 时发现
# 它一直没被同步：服务器上是手工放的旧文件，仓库改了端口/证书配置也不会生效。
SYNC_FILES=(docker-compose.yml nginx.conf)

# 是否先拉取 cnb 更新（git fetch + ff-only merge + 推 GitHub）
PULL_CNB="${DEPLOY_PULL_CNB:-1}"

# 强制全量重建（忽略 git diff，默认关）
FORCE_ALL="${DEPLOY_FORCE_ALL:-0}"

# 干跑：只打印将要执行的操作，不实际同步/重建
DRY_RUN=0

# 部署后端到端冒烟（scripts/smoke_deploy.py，只读登录＋GET，零成本）。
# 默认开：冒烟不过 = 这次部署没落地成功，**不写 .deploy_last_commit**（下次重跑仍会
# 重建这批容器）并以非零退出。--no-smoke 用于「明知容器在慢慢起来、先放行标记」。
RUN_SMOKE="${DEPLOY_RUN_SMOKE:-1}"

# 回滚镜像标签清理：每个镜像仓库保留最新 N 个 rollback/lastgood 标签，
# 且创建时间距今不足 KEEP_DAYS 天的一律不删。--no-prune-rollback 关掉清理。
PRUNE_ROLLBACK="${DEPLOY_PRUNE_ROLLBACK:-1}"
ROLLBACK_KEEP="${DEPLOY_ROLLBACK_KEEP:-2}"
ROLLBACK_KEEP_DAYS="${DEPLOY_ROLLBACK_KEEP_DAYS:-3}"

for a in "$@"; do
  case "$a" in
    --dry-run|-n)         DRY_RUN=1 ;;
    --no-pull)            PULL_CNB=0 ;;
    --all)                FORCE_ALL=1 ;;
    --no-smoke)           RUN_SMOKE=0 ;;
    --no-prune-rollback)  PRUNE_ROLLBACK=0 ;;
    -h|--help)            sed -n '2,20p' "$0"; exit 0 ;;
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
    --exclude='._*' --exclude='*/._*' \
    --exclude='.DS_Store' --exclude='*/.DS_Store' \
    --exclude='*.tsbuildinfo' \
    --exclude='slice-worker/engines' \
    --exclude='slice-worker/ubuntu' --exclude='slice-worker/macos' --exclude='slice-worker/windows' \
    --exclude='slice-worker/slice-worker' --exclude='slice-worker/slice-worker.exe' \
    -C "$LOCAL_DIR" "$dir" \
    | ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && tar xzf -" \
    || die "同步 $dir 失败"
}
# ⚠️ 上面对 slice-worker/engines 做了 exclude：它是 .gitignore 忽略的**构建产物副本**
# （Dockerfile 需要 `COPY --from=builder /build/engines`），唯一事实来源是仓库根 engines/。
# 本地那份可能长期陈旧（2026-09-14 实测本地是 33d20ff8、生产是 ae14d230）。若把它同步过去，
# 就等于用陈旧副本覆盖服务器的构建输入。正确做法是同步后在服务器上跑
# scripts/sync-engines-to-worker.sh（见主流程第 3.5 步）从 engines/ 全量刷新。

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

# ============================================================
# 单文件 bind mount 变更后自动 restart（Issue #244）
# ============================================================
# 症状：改了仓库根 nginx.conf → 同步成功、compose md5 对账通过、容器 Up healthy ——
#   但现网行为一点没变。原因：clip-nginx 把 nginx.conf **以单文件 bind mount**
#   挂成 /etc/nginx/conf.d/default.conf，宿主机换文件 ≠ 进程重读配置；而 nginx.conf
#   不在任何服务的构建上下文里，compute_services 的重建名单永远不会包含它。
#   于是这类改动在日志全绿的情况下静默留在「文件已更新、进程还是旧配置」。
# 判据：bind mount 下「容器内 md5」永远等于宿主机那份，拿它判「是否生效」毫无信息量。
#   真正能区分的只有时间：宿主机文件 mtime 比容器进程启动时间新 → 进程用的可能是旧配置。
#   再并上「本次内容真的变了」（diff 动过 / 远端与本地 md5 不一致）—— tar 保留 mtime，
#   单靠时间会漏掉「上一轮同步过但从没重启」的历史欠账，两条合起来才闭环。
# 作用域：只处理挂在 $REMOTE_DIR 下、且落在本脚本同步集（SYNC_DIRS ∪ SYNC_FILES）里的
#   单文件挂载。163 上还有 clip-postgres 挂 init.sql 这类单文件挂载 —— init.sql 不由本
#   脚本同步、且只在 postgres 首次启动时生效，去重启它属于越界，一律不动。
# 冻结名单：clip-rpa-worker（现网冻结）即使命中也只告警不重启，交人工判。
BIND_RESTART_SKIP="${DEPLOY_SKIP_RESTART:-clip-rpa-worker}"
STALE_SYNC_FILES=""       # 本次内容真的变了的根级同步文件（空格分隔相对路径）
BIND_CANDIDATES=""        # 每行 container|容器内路径|仓库相对路径|判据

# 远端根级同步文件的指纹表：md5|相对路径（缺失打 missing）
remote_sync_file_md5s() {
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "bash -s" <<MD5_EOF
R='${REMOTE_DIR}'
for f in ${SYNC_FILES[*]}; do
  m=\$(md5sum "\$R/\$f" 2>/dev/null | awk '{print \$1}')
  echo "\${m:-missing}|\$f"
done
MD5_EOF
}

# 哪些根级单文件「内容真的变了」：git diff 动过 ／ 远端 md5 与本地不一致（漂移也算变）。
# 必须在同步**之前**调 —— 同步完两侧必然相等，这个信号会自己把自己抹掉。
stale_sync_files() {
  local rel out="" table l r diff_all=0
  table="$(remote_sync_file_md5s 2>/dev/null)" || table=""
  if [ "$FORCE_ALL" = "1" ] || [ -z "$PREV" ] || \
     ! git -C "$LOCAL_DIR" cat-file -e "$PREV^{commit}" 2>/dev/null; then
    diff_all=1
  fi
  for rel in "${SYNC_FILES[@]}"; do
    if [ -f "$LOCAL_DIR/$rel" ]; then
      l="$(file_md5 "$LOCAL_DIR/$rel")"
      r="$(printf '%s\n' "$table" | awk -F'|' -v k="$rel" '$2==k{print $1}')"
      if [ -n "$r" ] && [ "$r" != "missing" ] && [ "$r" != "$l" ]; then
        out="$out $rel"
        continue
      fi
    fi
    if [ "$diff_all" = "1" ] || \
       git -C "$LOCAL_DIR" diff --name-only "$PREV" HEAD -- "$rel" 2>/dev/null | grep -qx "$rel"; then
      out="$out $rel"
    fi
  done
  echo "$out"
}

# 远端单文件 bind mount 全表：container|宿主机路径|容器内路径|stale|ok
bind_mount_stale_table() {
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "bash -s '${REMOTE_DIR}'" <<'STALE_EOF'
R="$1"
for c in $(docker ps -q); do
  n=$(docker inspect -f '{{.Name}}' "$c" | sed 's|^/||')
  se=$(date -d "$(docker inspect -f '{{.State.StartedAt}}' "$c")" +%s 2>/dev/null) || continue
  docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}=>{{.Destination}}{{println}}{{end}}{{end}}' "$c" \
    | while IFS= read -r m; do
        src="${m%%=>*}"; dst="${m#*=>}"
        [ -f "$src" ] || continue
        case "$src" in "$R"/*) ;; *) continue ;; esac
        mt=$(stat -c %Y "$src" 2>/dev/null) || continue
        if [ "$mt" -gt "$se" ]; then st=stale; else st=ok; fi
        echo "$n|$src|$dst|$st"
      done
done
STALE_EOF
}

# 相对路径是否落在本脚本的同步集内（SYNC_FILES 精确 ／ SYNC_DIRS 前缀）
in_synced_set() {
  local rel="$1" d f
  for f in "${SYNC_FILES[@]}"; do
    [ "$rel" = "$f" ] && return 0
  done
  for d in "${SYNC_DIRS[@]}"; do
    case "$rel" in "$d"/*) return 0 ;; esac
  done
  return 1
}

collect_bind_candidates() {
  local raw n src dst st rel
  BIND_CANDIDATES=""
  raw="$(bind_mount_stale_table 2>/dev/null)"
  if [ -z "$raw" ]; then
    log "WARN: 单文件 bind mount 探测失败／为空（本次不做自动重启，改过 nginx.conf 请人工 docker restart clip-nginx）"
    return 0
  fi
  while IFS='|' read -r n src dst st; do
    [ -n "$n" ] || continue
    rel="${src#"$REMOTE_DIR"/}"
    in_synced_set "$rel" || continue
    case " $STALE_SYNC_FILES " in
      *" $rel "*) st="content_changed" ;;
    esac
    [ "$st" = "stale" ] || [ "$st" = "content_changed" ] || continue
    BIND_CANDIDATES="${BIND_CANDIDATES}${n}|${dst}|${rel}|${st}
"
  done <<CAND_EOF
$raw
CAND_EOF
}

restart_stale_bind_mounts() {
  local done_list="" n dst rel why cur want
  collect_bind_candidates
  if [ -z "$BIND_CANDIDATES" ]; then
    if [ -n "$STALE_SYNC_FILES" ]; then
      log "单文件 bind mount：${STALE_SYNC_FILES} 有变更，但没有容器以单文件方式挂载它们（无需重启）"
    fi
    return 0
  fi
  while IFS='|' read -r n dst rel why; do
    [ -n "$n" ] || continue
    case " $done_list " in
      *" $n "*) continue ;;
    esac
    done_list="$done_list $n"
    case " $BIND_RESTART_SKIP " in
      *" $n "*)
        log "WARN: ${n} 挂载的 ${rel} 已更新（判据 ${why}），但它在冻结名单里 → **没有**自动重启，需人工判：docker restart ${n}"
        continue
        ;;
    esac
    if [ "$DRY_RUN" = "1" ]; then
      log "[dry-run] 将 restart ${n}（单文件 bind mount: ${rel} -> ${dst}，判据 ${why}）"
      continue
    fi
    log "restart ${n}（单文件 bind mount: ${rel}，判据 ${why}）..."
    if ! ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker restart $n" >/dev/null 2>&1; then
      log "WARN: ${n} 重启失败（${rel} 的改动可能未生效，请手工 docker restart ${n}）"
      continue
    fi
    want="$(file_md5 "$LOCAL_DIR/$rel")"
    cur="$(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker exec $n md5sum '$dst' 2>/dev/null | awk '{print \$1}'")"
    if [ "$cur" = "$want" ]; then
      log "  验收：容器内 ${dst} md5=${cur} 与仓库一致"
    else
      log "  WARN: 容器内 ${dst} md5=${cur:-取不到} 与仓库 ${want} 不一致（不是 bind mount？路径变了？请人工 docker inspect ${n}）"
    fi
  done <<APPLY_EOF
$BIND_CANDIDATES
APPLY_EOF
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

# engines/ 是否在本次变更内 —— 决定是否需要 `docker restart clip-backend`
# （engines 对 slice-worker 是镜像内 COPY，对 clip-backend 是只读 bind mount：
#  文件同步即生效，但 uvicorn 无 --reload，必须重启才重新 import 新引擎模块）
engines_changed() {
  local prev="$1"
  [ "$FORCE_ALL" = "1" ] && return 0
  if [ -z "$prev" ] || ! git -C "$LOCAL_DIR" cat-file -e "$prev^{commit}" 2>/dev/null; then
    return 0
  fi
  git -C "$LOCAL_DIR" diff --name-only "$prev" HEAD 2>/dev/null | grep -q '^engines/'
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
  # slice-worker/ 或 engines/ 变更 —— 都会改变 slice-worker 镜像内容
  # （engines/ 由 Dockerfile COPY 进镜像，见 sync-engines-to-worker.sh）
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^slice-worker/'; then
    svc="$svc slice-worker slice-worker-2"
  fi
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^engines/'; then
    svc="$svc slice-worker slice-worker-2"
  fi
  # rpa/ 变更 —— 镜像 clip-rpa:latest，build context ./rpa（独立于 backend）
  if [ "$changed" = "ALL" ] || printf '%s\n' "$changed" | grep -q '^rpa/'; then
    svc="$svc rpa_worker"
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

# 1.5 部署门禁（P1·评审定稿⑬）：部署物必须已被 CI 验证——HEAD 须已推到远端。
# 设置 DEPLOY_ALLOW_UNPUSHED=1 显式放行（应急），默认拦截。
HEAD_SHA="$(git -C "$LOCAL_DIR" rev-parse HEAD)"
if [ "${DEPLOY_ALLOW_UNPUSHED:-0}" != "1" ]; then
  if ! git -C "$LOCAL_DIR" branch -r --contains "$HEAD_SHA" 2>/dev/null | grep -qE '.'; then
    die "HEAD ($HEAD_SHA) 尚未推送到任何远端——部署物必须先过 CI（push 后再部署；应急设 DEPLOY_ALLOW_UNPUSHED=1）"
  fi
  log "门禁通过：HEAD 已在远端"
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
  # 3.0 同 real 分支：干跑也要算「哪些根级单文件内容变了」（远端 md5 取当前值，
  #     同步还没发生）。restart 本身由第 4.6 步统一调，干跑在那里打「将 restart ...」。
  STALE_SYNC_FILES="$(stale_sync_files)"
  [ -n "$STALE_SYNC_FILES" ] && log "[dry-run] 根级单文件内容有变更:${STALE_SYNC_FILES}"
  log "[dry-run] 重建前将打回滚标签 rollback-pre-<MMDD-HHMM>-<commit>；部署后跑 smoke_deploy.py（未过则不写 .deploy_last_commit 并非零退出，--no-smoke 可关）；末尾清理 ${ROLLBACK_KEEP_DAYS} 天前的旧回滚标签（每仓库留最新 ${ROLLBACK_KEEP} 个，--no-prune-rollback 可关）"
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

  # 3.0 同步**前**先算哪些根级单文件内容真的变了（漂移／新改动都算）。顺序是硬要求：
  #     同步之后两侧 md5 必然相等，这个信号就没了，nginx 这类 bind mount 也就永远不会
  #     被重启（Issue #244 的根因正是「同步了、没人重启、日志全绿」）。
  STALE_SYNC_FILES="$(stale_sync_files)"
  [ -n "$STALE_SYNC_FILES" ] && log "根级单文件内容有变更:${STALE_SYNC_FILES}"

  for d in "${SYNC_DIRS[@]}"; do
    sync_dir "$d"
  done
  for f in "${SYNC_FILES[@]}"; do
    sync_file "$f"
  done
  log "全部目录 + 根文件同步完成"

  # 3.1.5 服务器侧清 macOS 垃圾（._* AppleDouble / .DS_Store）。来源存疑（本地 tar 已
  # 双模式排除、本地仓库恒为 0，但 163 树上会再生——疑似 SMB 侧 macOS 写入），根治办法
  # 就是每次部署同步后兜底清一遍：alembic 会把 ._0063 当迁移模块加载（null bytes 报错、
  # stamp 失败），这 200 字节的保险比排查来源便宜。
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" \
    "find '$REMOTE_DIR' -name '._*' -type f -delete; find '$REMOTE_DIR' -name '.DS_Store' -type f -delete" \
    || log "WARN: 服务器侧垃圾清理失败（不影响本次已构建的镜像，下次部署重试）"

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

# 3.6 回滚镜像标签（P1·评审定稿⑬ ＋ 2026-11-11 运维席 P1 重做）
# 原实现有两处硬伤，合起来等于「回滚预案从来没存在过」：
#   · 从没被调用：函数定义在这儿，主流程里一句 `tag_last_good` 都没有 —— 打 tag 这步
#     实际一次都没跑过（163 上那批 rollback-pre-* 全是历次手工部署留下的，不是脚本的功劳）。
#   · tag 名算错：`${img%-*}-lastgood` 想剥掉 `:latest`，但 `clip-backend:latest` 里唯一的
#     `-` 在仓库名中间 → 剥出 `clip`，所有服务全打成同一个 `clip-lastgood`，互相覆盖。
# 现在：① 重建前真调用；② 镜像引用交给 compose 自己解析
# （`docker compose images <svc> --format json`，实测 backend / alembic-migrate / frontend /
# autoclip / slice-worker / rpa_worker 都取得到；没建过镜像的 worker-remotion 取到空 → 跳过）；
# ③ tag 名带「部署时刻」而不是只带 commit —— 同一 HEAD 一天部署两次不会把第一次的备份顶掉；
# ④ 打完把可直接复制的回滚指令打出来（自动回滚仍不做：DB 可能已经迁移过，回代码不回库
#    会把现网打成半新半旧，这一步必须人来判）。
LAST_GOOD_TAGGED=0
ROLLBACK_TAG_LIST=""      # 每行 svc|当前镜像|新打的回滚 tag
tag_last_good() {
  [ "$LAST_GOOD_TAGGED" = "1" ] && return 0
  LAST_GOOD_TAGGED=1
  [ -n "$SERVICES" ] || return 0
  local suffix raw
  suffix="$(date +%m%d-%H%M)-$(git -C "$LOCAL_DIR" rev-parse --short HEAD)"
  raw="$(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "
    cd '$REMOTE_DIR' || exit 1
    for svc in $SERVICES; do
      ref=\$(docker compose images \"\$svc\" --format json 2>/dev/null \\
            | sed -n 's/.*\"Repository\":\"\([^\"]*\)\",\"Tag\":\"\([^\"]*\)\".*/\1:\2/p' | head -1)
      if [ -z \"\$ref\" ]; then echo \"SKIP|\$svc||\"; continue; fi
      new=\"\${ref%:*}:rollback-pre-${suffix}\"
      if docker tag \"\$ref\" \"\$new\" 2>/dev/null; then echo \"TAG|\$svc|\$ref|\$new\"; else echo \"FAIL|\$svc|\$ref|\$new\"; fi
    done
  " 2>&1)"
  ROLLBACK_TAG_LIST="$(printf '%s\n' "$raw" | awk -F'|' '$1=="TAG"{print $2"|"$3"|"$4}')"
  _n_tag="$(printf '%s\n' "$ROLLBACK_TAG_LIST" | grep -c . || true)"
  _n_skip="$(printf '%s\n' "$raw" | grep -c '^SKIP' || true)"
  _n_fail="$(printf '%s\n' "$raw" | grep -c '^FAIL' || true)"
  # ⚠️ 「服务数」≠「标签数」：backend/beat/6 个 worker/alembic-migrate 全共用
  # `clip-backend:latest`，10 次 docker tag 只会落下 **2 个**唯一标签（backend 系 1 个＋
  # frontend 1 个），后面几次是同 repo 同 tag 的幂等重打。原来这句只报 ${_n_tag}，
  # 读日志的人会以为有 10 个可回退的镜像备份（2026-11-11 现网部署后 `docker images` 实拍只有 2 个）。
  _n_uniq="$(printf '%s\n' "$ROLLBACK_TAG_LIST" | cut -d'|' -f2 | sort -u | grep -c . || true)"
  log "回滚标签：${_n_tag} 次 docker tag → **${_n_uniq} 个唯一镜像标签**（rollback-pre-${suffix}）· 跳过 ${_n_skip} · 失败 ${_n_fail}"
  if [ "${_n_fail}" != "0" ]; then
    printf '%s\n' "$raw" | grep '^FAIL' | sed 's/^/      docker tag 失败: /'
  fi
  if [ "${_n_tag}" = "0" ]; then
    log "WARN: 一个回滚标签都没打上（受影响服务全没有可解析的镜像？），本次部署出问题只能靠重跑旧 commit 回退"
  fi
}

print_rollback_howto() {
  [ -n "$ROLLBACK_TAG_LIST" ] || return 0
  local svcs
  svcs="$(printf '%s\n' "$ROLLBACK_TAG_LIST" | cut -d'|' -f1 | sort -u | tr '\n' ' ')"
  log "回滚预案（在 ${REMOTE_USER}@${REMOTE_HOST} 上执行；只回代码，不回数据库 —— 本次若有迁移要人工判）:"
  printf '%s\n' "$ROLLBACK_TAG_LIST" | awk -F'|' '{print $2" "$3}' | sort -u | while read -r ref new; do
    echo "      docker tag ${new} ${ref}"
  done
  echo "      cd ${REMOTE_DIR} && docker compose up -d --no-build ${svcs}"
}

# 3.7 回滚标签清理（2026-11-11 运维席 P1）：163 上 rollback/lastgood 标签已堆到 57 个，
# 全是历次手工部署留的一次性备份 —— 占着旧镜像不让 prune 回收，且越堆越没人敢删。
# 判据两条同时成立才删：① 同仓库内**不是**最新 ${ROLLBACK_KEEP} 个；② 镜像构建时间早于
# ${ROLLBACK_KEEP_DAYS} 天前。按构建时间而不是打 tag 的时间排序有已知偏差（长期不重建的
# 服务，其备份镜像会比 tag 老），所以第一条兜底：每个仓库最新两个永远留着。
# 只 untag／删无引用的镜像，且**不带 -f**：仍被容器占用的会失败并打 KEEP，绝不动在跑的容器。
prune_rollback_tags() {
  if [ "$PRUNE_ROLLBACK" != "1" ]; then
    log "跳过回滚标签清理（--no-prune-rollback）"
    return 0
  fi
  log "清理 ${ROLLBACK_KEEP_DAYS} 天前的回滚标签（每个镜像仓库至少留最新 ${ROLLBACK_KEEP} 个）..."
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "
    cutoff=\$(date -d '-${ROLLBACK_KEEP_DAYS} days' +%Y-%m-%d 2>/dev/null) || { echo 'WARN: 远端 date -d 不支持，跳过清理'; exit 0; }
    docker images --format '{{.Repository}}:{{.Tag}}|{{.CreatedAt}}' \\
      | grep -E '^clip-[A-Za-z0-9_-]+:(rollback|.*lastgood)' \\
      | awk -F'|' '{repo=\$1; sub(/:.*/,\"\",repo); print repo\"|\"\$2\"|\"\$1}' \\
      | sort -t'|' -k1,1 -k2,2r \\
      | awk -F'|' -v cutoff=\"\$cutoff\" -v keep=${ROLLBACK_KEEP} '
          { rank[\$1]++; if (rank[\$1] > keep && substr(\$2,1,10) < cutoff) print \$3 }' \\
      | while read -r t; do
          if docker rmi \"\$t\" >/dev/null 2>&1; then echo \"  已删 \$t\"; else echo \"  保留 \$t（仍被容器占用）\"; fi
        done
  " 2>&1 | tail -40 || log "WARN: 回滚标签清理失败（不影响部署）"
}

# 4. 重建受影响容器
if [ -n "$SERVICES" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] 将重建容器: $SERVICES"
    case " $SERVICES " in
      *" slice-worker "*) log "[dry-run] 将先在服务器执行 sync-engines-to-worker.sh（刷新构建副本）" ;;
    esac
    if engines_changed "$PREV"; then
      log "[dry-run] engines 有变更 → 部署后将需要重启 clip-backend 重新加载引擎"
    fi
  else
    # 4.0 重建前先留回滚标签（必须在 --build 之前：build 会把 clip-xxx:latest 顶到
    #     新镜像上，之后再打就把刚部署的新版本当备份了）。
    tag_last_good
    # 4.1 slice-worker 镜像是 `COPY --from=builder /build/engines`，其构建输入
    #     slice-worker/engines 是 .gitignore 忽略的产物副本（本地那份可能长期陈旧，
    #     且已从同步排除）→ 重建前必须在服务器上从 engines/ 全量刷新，否则镜像里
    #     还是旧引擎（2026-08-15 / 2026-08-24 两次踩坑）。
    case " $SERVICES " in
      *" slice-worker "*)
        log "刷新构建副本 slice-worker/engines (sync-engines-to-worker.sh)..."
        ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && bash scripts/sync-engines-to-worker.sh" \
          || die "sync-engines-to-worker.sh 执行失败"
        ;;
    esac

    log "重建容器: $SERVICES"
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "cd '$REMOTE_DIR' && docker compose up -d --build $SERVICES" \
      || die "docker compose 重建失败"

    # 4.2 engines/ 变更且 backend 不在重建名单时：engines 对 clip-backend 是只读
    #     bind mount（/app/engines），文件已随同步生效，但 uvicorn 无 --reload，
    #     进程里仍是旧模块 → 必须重启。backend 被重建时新容器自然加载新代码，跳过。
    if engines_changed "$PREV" && ! printf '%s' " $SERVICES " | grep -q " backend "; then
      log "engines 变更 → 重启 clip-backend 以重新加载引擎模块..."
      ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker restart clip-backend" \
        || log "WARN: clip-backend 重启失败（引擎改动可能未生效，请手工 docker restart clip-backend）"
    fi
  fi
else
  log "跳过容器重建"
fi

# 4.6 单文件 bind mount 生效收口（Issue #244）—— 必须放在重建之后、冒烟之前：
#     · 放重建之后：compose 刚 recreate 的容器 StartedAt 是现在，mtime 判据自动不命中，
#       不会重复重启；nginx.conf 这类不在重建名单里的才轮到我们补 restart。
#     · 放冒烟之前：冒烟走 nginx :80 打接口，nginx 没换配置就等于「验的是旧网关」，
#       超时链／location 改动这类回归会被冒烟漏掉。
restart_stale_bind_mounts

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

  # 5.5 部署后端到端冒烟（2026-11-11 运维席 P1）。此前的「验证」只看 compose ps ＋
  #     grep 错误日志，属于「容器起来了」而不是「服务能用」：登录竞态（Issue #350）
  #     那种一进门就 401 的回归全靠人记得手工跑 smoke_deploy.py，跑漏了就静默留在现网。
  #     零成本：只登录 admin ＋ 5 个 GET，不建数据、不调模型、不投板。
  #     未过则 **不写 .deploy_last_commit** 并非零退出 —— 写了标记，下次增量判定就会
  #     认为这批容器已经部署过，一次坏部署会被永久藏起来。
  if [ "$RUN_SMOKE" = "1" ]; then
    if [ "$(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker inspect -f '{{.State.Running}}' clip-backend 2>/dev/null || echo missing")" != "true" ]; then
      log "WARN: clip-backend 不在运行，跳过冒烟（这本身就是部署事故，请立刻人工看 docker compose ps）"
    else
      log "部署后冒烟 scripts/smoke_deploy.py（容器内 127.0.0.1:8080）..."
      # 刚 recreate 完 uvicorn 可能还在起，健康探测最多等 60s；超时不判死，交给冒烟本身说话。
      _hs=""
      for _i in 1 2 3 4 5 6 7 8 9 10 11 12; do
        _hs="$(ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' clip-backend 2>/dev/null")"
        case "$_hs" in healthy|no-healthcheck) break ;; esac
        sleep 5
      done
      log "clip-backend 状态: ${_hs:-unknown}"
      _smoke_rc=0
      ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker exec -i clip-backend python -" \
        < "$LOCAL_DIR/scripts/smoke_deploy.py" 2>&1 | tail -25 || _smoke_rc=$?
      if [ "$_smoke_rc" != "0" ]; then
        print_rollback_howto
        die "部署后冒烟未通过（退出码 ${_smoke_rc}）—— 本次**没有**记录部署标记：现网跑的已是新代码，要么修完重跑本脚本，要么照上面的预案回滚（有迁移时别只回镜像）"
      fi
      log "冒烟通过 ✅"
    fi
  else
    log "跳过部署后冒烟（--no-smoke）"
  fi

  # 6. 记录本次部署 commit（本地 + 远端标记同步，避免两侧失配）
  git -C "$LOCAL_DIR" rev-parse HEAD > "$LAST_FILE"
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "echo -n \"$(cat "$LAST_FILE")\" > '$REMOTE_DIR/.deploy_last_commit'" \
    || log "WARN: 远端部署标记写入失败（不影响部署）"
  log "部署完成 ✅  (commit $(cat "$LAST_FILE"))"
  # 回滚预案留档：即使这次一切正常，也把「刚才那一版是哪个 tag」打出来，
  # 免得事后想回退时只能去 docker images 里猜时间。
  print_rollback_howto

  # 6.5 回滚标签清理放在悬空清理之前：先把没人要的 rollback tag 摘掉，
  #     下面 image prune 才收得回那些只剩回滚标签占着的旧镜像。
  prune_rollback_tags

  # 7. 自动清理 Docker 垃圾（悬空镜像 + 构建缓存）——每次部署 --build 会产生
  #    新镜像覆盖旧 tag，旧镜像层变 <none> 悬空；BuildKit 缓存默认不自动清，
  #    几天就累积数十 GB（2026-08-19 实测 39 悬空镜像 + 10.5GB 缓存）。
  #    在部署成功后顺带清理，避免手工运维。
  log "自动清理 Docker 垃圾（悬空镜像 + 构建缓存）..."
  ssh $SSH_OPTS "${REMOTE_USER}@${REMOTE_HOST}" "docker image prune -f 2>&1 | tail -2; docker builder prune -f 2>&1 | tail -2" \
    || log "WARN: Docker 垃圾清理失败（不影响部署）"
fi
