#!/usr/bin/env bash
# =============================================================================
# deploy_phase2.sh — 后程部署：构建指定服务 → 镜像内预检 → 单服务逐个 recreate
#
# 定位：跑在**服务器上**（~/clip-workflow 内，直接 bash scripts/deploy_phase2.sh），
#       补 deploy_server.sh 之外的场景——只重建部分服务（如 backend/slice-worker/
#       frontend），不动整树同步。
#
# 四个闸门（2026-11-27 后程部署事故换来的，见 relay log/023）：
#   G1  TS 在锁与解析闸门之后取值——构建日志名与实际一致（曾 -1926 vs 实际 -1839）
#   G2  构建同步执行 + 完成判据兼容 buildkit（#NN DONE / naming to），
#       并断言每个目标服务的镜像确实存在——不再轮询日志空转 40×20s
#   G3  recreate 前逐镜像预检（backend 家族在镜像内 `import app.main`），
#       任何失败立即退出，**任何容器都不会被动过**（1127 崩溃循环教训）
#   G4  单服务逐个 `up -d --no-deps --no-build`——多服务一把梭在 snap docker
#       上会挂起 9 分钟以上并把 beat+worker 停在半路（F107：逐个 2.3s）
#
# 用法：
#   bash scripts/deploy_phase2.sh                     # 默认 backend+frontend+双 slice-worker+celery 全家
#   bash scripts/deploy_phase2.sh --services "backend frontend"
#   bash scripts/deploy_phase2.sh --dry-run           # 只打印计划，不碰 docker
# =============================================================================
set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

DRY_RUN=0
SERVICES="backend frontend slice-worker slice-worker-2 beat worker-fast worker-video worker-selection worker-variant worker-publish worker-wechat-dl"
BUILD_LOCK_FILE="${DEPLOY_BUILD_LOCK_FILE:-/var/tmp/clip-build.lock}"
BUILD_LOCK_WAIT="${DEPLOY_BUILD_LOCK_WAIT:-3600}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --services) SERVICES="$2"; shift ;;
    *) echo "未知参数: $1（支持 --dry-run / --services \"...\"）" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "[phase2] ✗ $*" >&2; exit 1; }
log() { echo "[phase2] $*"; }

# ---------- 闸门 0：服务/镜像解析（失败在此退出，TS 尚未取值） ----------
SVC_LIST=()
for s in $SERVICES; do
  docker compose config --services 2>/dev/null | grep -qx "$s" || die "服务 '$s' 不在 compose 项目里（检查拼写/override）"
  SVC_LIST+=("$s")
done

declare -A SVC_IMAGE
for s in "${SVC_LIST[@]}"; do
  img="$(docker compose images "$s" --format json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin)[0];print(d["Repository"]+":"+d["Tag"])' 2>/dev/null || true)"
  [ -n "$img" ] || img="$(docker compose images "$s" 2>/dev/null | awk 'NR==2{print $2}')"
  [ -n "$img" ] || die "无法解析服务 '$s' 的镜像名"
  SVC_IMAGE["$s"]="$img"
done

# ---------- 闸门 1（G1）：锁 + TS（日志名从这一刻起才算数） ----------
TS="$(date +%m%d-%H%M)"
LOG_FILE="logs/deploy-phase2-$TS.log"
mkdir -p logs
log "目标服务: ${SVC_LIST[*]}"
for s in "${SVC_LIST[@]}"; do log "  $s -> ${SVC_IMAGE[$s]}"; done
log "构建日志: $LOG_FILE"

if [ "$DRY_RUN" = "1" ]; then
  log "[dry-run] 构建后将执行预检："
  for s in "${SVC_LIST[@]}"; do
    case "${SVC_IMAGE[$s]}" in
      clip-backend*)    echo "    $s: docker run --rm --entrypoint python3 ${SVC_IMAGE[$s]} -c 'import app.main'" ;;
      clip-slice-worker*) echo "    $s: docker run --rm --entrypoint /bin/sh ${SVC_IMAGE[$s]} -c 'test -f /app/engines/slice.py && test -x /app/slice-worker'" ;;
      clip-frontend*)   echo "    $s: docker run --rm --entrypoint /bin/sh ${SVC_IMAGE[$s]} -c 'nginx -t'" ;;
      *)                echo "    $s: （无专属预检，仅镜像存在性检查）" ;;
    esac
  done
  log "[dry-run] 预检全过后逐服务 recreate: $(printf '%s ' "${SVC_LIST[@]}")"
  exit 0
fi

if [ -e "$BUILD_LOCK_FILE" ] && command -v flock >/dev/null 2>&1; then
  log "等待构建锁 $BUILD_LOCK_FILE（最长 ${BUILD_LOCK_WAIT}s）..."
fi
exec 9>"$BUILD_LOCK_FILE"
flock -w "$BUILD_LOCK_WAIT" 9 || die "等构建锁超时（${BUILD_LOCK_WAIT}s），可能有别的部署在跑"

# ---------- 构建（同步执行，G2 判据直接看输出与镜像存在性） ----------
log "开始构建（同步，输出同写 $LOG_FILE）..."
if ! docker compose build "${SVC_LIST[@]}" 2>&1 | tee "$LOG_FILE"; then
  die "docker compose build 失败，详见 $LOG_FILE"
fi
# G2 判据：buildkit 输出必含 DONE/CACHED，且不得有 ERROR；再断言镜像真的被刷新
if ! grep -qE '#[0-9]+ (DONE|CACHED)|naming to' "$LOG_FILE"; then
  die "构建输出未匹配 buildkit 完成特征（#NN DONE/CACHED/naming to）——构建方式可能变了，人工确认后再跑"
fi
if grep -qE '^#?[0-9]* ?ERROR|error:' "$LOG_FILE"; then
  die "构建输出含 ERROR/error:，详见 $LOG_FILE"
fi
for s in "${SVC_LIST[@]}"; do
  docker image inspect "${SVC_IMAGE[$s]}" >/dev/null 2>&1 || die "镜像 ${SVC_IMAGE[$s]} 不存在（服务 $s 构建异常）"
done
log "构建完成且 ${#SVC_LIST[@]} 个镜像全部就位"

# ---------- 闸门 3（G3）：镜像内预检——任何容器被动之前 ----------
PRE_FAIL=""
for s in "${SVC_LIST[@]}"; do
  img="${SVC_IMAGE[$s]}"
  case "$img" in
    clip-backend*)
      log "预检 $s：镜像内 import app.main..."
      ENVARG=""
      [ -f .env ] && ENVARG="--env-file .env"
      if ! docker run --rm $ENVARG --entrypoint python3 "$img" -c "import app.main" >/dev/null 2>"logs/precheck-$s-$TS.err"; then
        PRE_FAIL="$PRE_FAIL $s"
        log "  ✗ $s 预检失败（logs/precheck-$s-$TS.err）："
        tail -5 "logs/precheck-$s-$TS.err" >&2
      else
        log "  ✓ $s"
      fi
      ;;
    clip-slice-worker*)
      log "预检 $s：engines/slice.py + 主程序存在性..."
      if docker run --rm --entrypoint /bin/sh "$img" -c "test -f /app/engines/slice.py && test -x /app/slice-worker" >/dev/null 2>&1; then
        log "  ✓ $s"
      else
        PRE_FAIL="$PRE_FAIL $s"
        log "  ✗ $s 镜像内引擎/主程序缺失"
      fi
      ;;
    clip-frontend*)
      # nginx -t 需解析 upstream "backend"：裸 docker run 无 compose 网络必报
      # host not found（环境限制非配置错误）——从在跑容器动态取网络，取不到就降级跳过
      NET="$(docker inspect "$(docker compose ps -q backend 2>/dev/null)" \
        --format '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || true)"
      log "预检 $s：nginx -t（网络 ${NET:-<不可得，跳过>}）..."
      if [ -z "$NET" ]; then
        log "  - $s：backend 容器不在跑取不到网络，跳过 nginx -t"
      elif docker run --rm --network "$NET" --entrypoint /bin/sh "$img" -c "nginx -t" >/dev/null 2>&1; then
        log "  ✓ $s"
      else
        PRE_FAIL="$PRE_FAIL $s"
        log "  ✗ $s nginx 配置异常"
      fi
      ;;
    *)
      log "  - $s：无专属预检，跳过"
      ;;
  esac
done
[ -z "$PRE_FAIL" ] || die "预检失败：[$PRE_FAIL] —— 退出，未动任何容器"

# ---------- 闸门 4（G4）：单服务逐个 recreate ----------
for s in "${SVC_LIST[@]}"; do
  log "recreate $s..."
  if ! docker compose up -d --no-deps --no-build "$s"; then
    die "recreate $s 失败（此前服务已重建，可用 docker compose ps 核对现状）"
  fi
  docker inspect --format '{{.State.Status}}' "$(docker compose ps -q "$s")" >/dev/null 2>&1 || true
done
log "✓ 后程部署完成：${SVC_LIST[*]}（日志 $LOG_FILE）"
