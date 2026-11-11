#!/usr/bin/env bash
#
# backup_server.sh — 生产服务器一键备份（批 M·评审一 P1-5；2026-11-11 运维排期扩到 MinIO 桶／媒体卷）
#
# 背景：此前全仓 grep 不到任何备份/回滚沉淀，历史 .env 事故恢复靠人肉。
# 本脚本在【服务器本机】跑（与 deploy_server.sh 的远端机同台）：
#   ① pg_dump 整库（docker compose exec postgres，不依赖宿主机装 psql）；
#   ② .env 快照（部署变量丢了等于全站失联，必须和库一起备份）；
#   ③ pg_restore --list 完整性自检；
#   ④ MinIO 各桶 mc mirror（增量、当前态）；
#   ⑤ media_data 卷＋浏览器 profile／去重上传卷增量拷贝；
#   ⑥ 抽样 md5 对账 —— 拿**备份目录里的那份**与现网对象逐字节比；
#   ⑦ 恢复演练 —— 从备份目录取回真文件、ffprobe 读得出时长；
#   ⑧ 保留期清理（默认 14 天）；⑨ 汇总与红/绿判定。
#
# 备份算成功的判据是三条同时成立，不是「文件躺在那儿了」：
#   · 桶清单逐个 mc mirror 成功（桶清单为空直接判失败，绝不静默「什么都没备还报绿」）；
#   · 抽样 md5 与现网对象逐字节一致（对不上计硬伤、整轮报红）；
#   · 恢复演练从备份目录里读出音视频时长（读不出报 WARN 并说明）。
#
# 用法（服务器上）：
#   bash scripts/backup_server.sh                 # 备到默认目录 /home/<user>/clip-backups
#   BACKUP_DIR=/data/backup KEEP_DAYS=30 bash scripts/backup_server.sh
#   MIRROR_REMOVE_EXTRANEOUS=1 bash scripts/backup_server.sh   # 让镜像精确等于现网（会删本地多余对象）
#     ⚠️ 默认 0（只增不删）。开着 --remove 挂 cron 等于「现网误删 → 备份跟着误删」，别在 cron 里开。
#   ONLY_BUCKETS="login-qr sliced" bash scripts/backup_server.sh   # 调试口：只镜像这几个桶，演练用
#     ⚠️ 带着它就是「部分备份」，日志里会报一行 !! 并计入告警；cron 里绝不能出现。
#
# 挂 cron：**已于 2026-11-11 装在 163 的 cc12703 crontab 里，别再重复装**。
#   25 3 * * * cd /home/cc12703/clip-workflow && PATH=/snap/bin:/usr/local/bin:/usr/bin:/bin /usr/bin/bash scripts/backup_server.sh >> logs/backup.log 2>&1
#   两个当时踩过的点，改回去备份就会静默失效：
#     · 不写 03:40：那一分钟已被 revenue_keepalive 占用（同机同一个 crontab）；
#     · PATH 必须显式带上 /snap/bin：163 的 docker 是 snap 装的（/snap/bin/docker），
#       而 cron 继承的 PATH 里没有它 —— 不加这行就是「每天定点跑、每天 command not found」，
#       而失败只落在 logs/backup.log 里，没人看就等于没有。
#   核对：crontab -l | grep backup_server ；日志：tail -40 /home/cc12703/clip-workflow/logs/backup.log
#   卸载：crontab -l | grep -v backup_server | crontab -
#   扩容后的耗时量级：首次全量（MinIO 约 19G＋媒体卷 14G）约 20~40 分钟，后续增量分钟级。
#   cron 只有 03:25 一条、不会与自身重叠；手动补跑前先看 logs/backup.log 有没有正在跑的那轮。
#
# 首次实跑（2026-11-11 本机验过）：dump 4.1M / 1 秒，pg_restore --list 自检通过。
# 11-11 晚扩容段的现网实测口径（都是真跑出来的，不是设想）：
#   · 凭据一律不进命令行：`docker exec clip-minio printenv MINIO_ROOT_USER` 取值 → shell 变量 →
#     `MC_HOST_local` 用 `-e 变量名`（只传名字）交给 mc 容器；全程不 echo，ps 里看不到值。
#   · minio/mc 镜像的 ENTRYPOINT 就是 mc，别名配置靠 MC_HOST_<别名> 环境变量传；
#     默认以 root 跑会把产物写成 root 属主，后续清理／覆盖全 Permission denied ⇒ 必须 `--user $(id -u):$(id -g)`。
#   · 媒体卷里有 root 属主 700 的子目录（`/src/pingyue` 实测 uid1000 读不进去）⇒ 拷贝段以 root 跑，
#     拷完在容器里 `chown -R "$HOST_UID:$HOST_GID" /dst`，产物回到当前用户手里。
#   · clip-minio 容器里**没有 sed**（`mc ls` 的桶名要在宿主机解析），且 `mc du` 不认 `--nobatch`。
#   · 163 的 docker 是 snap 装的：它的 `/tmp` 与 ssh 会话的 `/tmp` 不在同一命名空间，
#     `-v /tmp/x:/backup` 挂进去是空目录（本轮实测 mirror 报「传了 227KiB」、宿主侧 0 个文件）。
#     ⇒ 备份目录必须在 /home 下（默认值已满足），脚本对这一点显式告警。
#
# ⚠️ 不覆盖的卷：postgres_data（① 的 pg_dump 已覆盖）／redis_data（缓存可重建）／
#    ollama_data（模型可重下）／slice_worker_temp（临时）。要备就自己加进 AUX_VOLS。

set -uo pipefail

# ============ 配置（可用环境变量覆盖） ============
# 与 docker-compose.yml 同一口径：POSTGRES_USER/POSTGRES_DB 从根 .env 读，读不到用默认值
COMPOSE_DIR="${BACKUP_COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/home/$(whoami)/clip-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

MINIO_C="${MINIO_CONTAINER:-clip-minio}"
MEDIA_C="${MEDIA_CONTAINER:-clip-backend}"
MC_IMG="${MC_IMAGE:-minio/mc:latest}"
BACKEND_IMG="${BACKEND_IMAGE:-clip-backend:latest}"
ALPINE_IMG="${ALPINE_IMAGE:-alpine:latest}"
MINIO_SVC_HOST="${MINIO_SERVICE_HOST:-minio:9000}"   # 容器网络里的服务名，不是 localhost
# 辅助卷：名字现取现验，凑不上就跳过并说明（换 compose 项目名不至于静默漏卷）
AUX_VOLS="${AUX_VOLS:-clip-workflow_chrome_profiles clip-workflow_dedupe_upload_data}"

MIRROR_DIR="${BACKUP_DIR}/minio"
MEDIA_DIR="${BACKUP_DIR}/media"
VOL_DIR="${BACKUP_DIR}/volumes"
SUMMARY="${BACKUP_DIR}/minio-summary-${STAMP}.txt"

log() { echo "[$(date '+%F %T')] $*"; }
die() { log "!! $*"; exit 1; }

FAILS=0      # 硬伤计数：>0 则整轮报红、退出码 1（cron 日志里必须能看出今天没备成）
WARNINGS=0   # 软伤计数：不判红，但必须写进日志（备份这种宁可吵也别安静）

# C locale 下中文/全角标点会把裸展开解析出怪变量名（deploy_server.sh 设计要点 8 的同款坑）：
# 这里变量后一律不紧跟全角字符。
cd "${COMPOSE_DIR}" || die "进不去 compose 目录 ${COMPOSE_DIR}"
[ -f .env ] || die "根目录没有 .env：连部署变量都找不到，备份无从谈起"

# 从 .env 抠库连接三件套（不 source .env —— 那会把整份部署变量灌进本 shell）
PG_USER="$(grep -E '^POSTGRES_USER=' .env | tail -1 | cut -d= -f2- | tr -d '"' || true)"
PG_DB="$(grep -E '^POSTGRES_DB=' .env | tail -1 | cut -d= -f2- | tr -d '"' || true)"
PG_USER="${PG_USER:-clipworkflow}"
PG_DB="${PG_DB:-clipworkflow}"

mkdir -p "${BACKUP_DIR}" || die "建不了备份目录 ${BACKUP_DIR}"

# ---- ① 整库 pg_dump（custom -Fc 格式：可 pg_restore 单表并行恢复，比纯 SQL 灵活）----
DB_OUT="${BACKUP_DIR}/clip-db-${STAMP}.dump"
log "① pg_dump 开始：库 ${PG_DB}（用户 ${PG_USER}）→ ${DB_OUT}"
docker compose exec -T postgres pg_dump -U "${PG_USER}" -d "${PG_DB}" -Fc \
  > "${DB_OUT}.tmp" 2>/tmp/backup_pgdump.err \
  || { tail -5 /tmp/backup_pgdump.err >&2; die "pg_dump 失败（完整报错见 /tmp/backup_pgdump.err）"; }
mv "${DB_OUT}.tmp" "${DB_OUT}"

# ---- ② .env 快照（chmod 600：里面有 DB 密码/凭据，别备份成世界可读）----
ENV_OUT="${BACKUP_DIR}/env-${STAMP}.snapshot"
install -m 600 .env "${ENV_OUT}" || die ".env 快照失败"

# ---- ③ 完整性自检：pg_restore --list 能把目录读出来才算备份成功 ----
[ -s "${DB_OUT}" ] || die "dump 是空文件，视为失败"
docker compose exec -T postgres pg_restore --list < "${DB_OUT}" > /dev/null 2>&1 \
  || die "pg_restore --list 读不出目录：这份 dump 不完整，别删旧备份，立刻排查"

HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
MINIO_OK=0
BUCKET_TOTAL=0
BUCKETS=""

# ---- ④ MinIO 桶镜像（mc mirror，增量当前态）----
# 凭据来源＝clip-minio 容器自己的 env；只经 shell 变量转手，命令行与日志都不出现值。
case "${BACKUP_DIR}" in
  /home/*) ;;
  *) log "WARN: 备份目录 ${BACKUP_DIR} 不在 /home 下 —— snap 版 docker 挂不出 /home 以外的路径（④⑤⑦ 靠挂载传递，会静默备出空目录）"
     WARNINGS=$((WARNINGS + 1)) ;;
esac

if ! docker inspect "${MINIO_C}" >/dev/null 2>&1; then
  log "WARN: 找不到容器 ${MINIO_C} —— 本轮只备 库＋.env，MinIO 镜像／抽样对账整段跳过"
  WARNINGS=$((WARNINGS + 1))
else
  MINIO_NET="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "${MINIO_C}")"
  [ -n "${MINIO_NET}" ] || die "读不到 ${MINIO_C} 所在网络：mc mirror 无从直连"

  # 桶清单在宿主机解析（clip-minio 容器里没有 sed）：取每行最后一列、去掉结尾斜杠
  BUCKETS="$(docker exec "${MINIO_C}" sh -c '
      mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 || exit 1
      mc ls l 2>/dev/null
    ' | awk '{gsub(/\/$/, "", $NF); print $NF}' | sort -u)"
  [ -n "${BUCKETS}" ] || die "桶清单为空（MinIO 活着吗？）——备份不能静默什么都没备"
  # ONLY_BUCKETS＝调试口（演练、排障时只镜像某几个桶）。留空才是全量口径，cron 里绝不要带它。
  if [ -n "${ONLY_BUCKETS:-}" ]; then
    log "!! ONLY_BUCKETS 生效（调试口）：本轮只镜像 ${ONLY_BUCKETS}，其余桶这次没备份"
    WARNINGS=$((WARNINGS + 1))
    _kept=""
    for _req in ${ONLY_BUCKETS}; do
      printf '%s\n' "${BUCKETS}" | grep -qx -- "${_req}" \
        || die "ONLY_BUCKETS 里的 ${_req} 不在现网桶清单里（拼错／桶被删？）：$(printf '%s ' ${BUCKETS})"
      _kept="${_kept} ${_req}"
    done
    BUCKETS="$(printf '%s\n' ${_kept} | sort -u)"
  fi
  BUCKET_TOTAL="$(printf '%s\n' "${BUCKETS}" | grep -c . || true)"

  mkdir -p "${MIRROR_DIR}"
  : > "${SUMMARY}"
  MC_LOG="${BACKUP_DIR}/mc-mirror-${STAMP}.log"   # mc 的原始输出留在这儿，报红时才有据可查
  : > "${MC_LOG}"
  chmod 600 "${MC_LOG}" 2>/dev/null
  MINIO_ROOT_USER="$(docker exec "${MINIO_C}" printenv MINIO_ROOT_USER)"
  MINIO_ROOT_PASSWORD="$(docker exec "${MINIO_C}" printenv MINIO_ROOT_PASSWORD)"
  { [ -n "${MINIO_ROOT_USER}" ] && [ -n "${MINIO_ROOT_PASSWORD}" ]; } \
    || die "${MINIO_C} 容器 env 里读不到 MINIO_ROOT_USER/PASSWORD：无法镜像 MinIO"

  # mc 认 MC_HOST_<别名>＝「scheme://user:pass@endpoint」这种形状；凭据里若有 @ : / 会解析歪，
  # 所以先做一次只读 ls 探活，探不过当场判失败——别等 mirror 静默搬了 0 个对象才发现。
  MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@${MINIO_SVC_HOST}"
  export MC_HOST_local
  docker run --rm --user "${HOST_UID}:${HOST_GID}" -e HOME=/tmp -e MC_HOST_local \
      --network "${MINIO_NET}" --entrypoint /usr/bin/mc "${MC_IMG}" ls local >/dev/null 2>&1 \
    || die "MC_HOST 连不上 MinIO（${MINIO_SVC_HOST}）：多半是凭据里有 @ : / 这类字符、URL 形状装不下"

  REMOVE_FLAG=""
  [ "${MIRROR_REMOVE_EXTRANEOUS:-0}" = "1" ] && REMOVE_FLAG="--remove"
  log "④ MinIO 镜像开始：网络 ${MINIO_NET}，共 ${BUCKET_TOTAL} 个桶（$(printf '%s ' ${BUCKETS})）"
  for b in ${BUCKETS}; do
    [ -n "${b}" ] || continue
    # 直接给 mc 传参数（不再包一层 sh）：镜像的 ENTRYPOINT 就是 mc，`--entrypoint /usr/bin/mc ... sh -c`
    # 会变成 `mc sh -c ...` → 「`sh` is not a recognized command」（11-11 晚实测踩过）。
    # ${REMOVE_FLAG} 必须不加引号：空时要展开成 0 个参数，加了引号就传一个空参数给 mc。
    if docker run --rm --user "${HOST_UID}:${HOST_GID}" -e HOME=/tmp -e MC_HOST_local \
        --network "${MINIO_NET}" -v "${MIRROR_DIR}:/backup" \
        --entrypoint /usr/bin/mc "${MC_IMG}" mirror --overwrite ${REMOVE_FLAG} \
        "local/${b}" "/backup/${b}" >> "${MC_LOG}" 2>&1; then
      LIVE_DU="$(docker exec -e B="${b}" "${MINIO_C}" sh -c '
          mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
          mc du "l/$B" 2>/dev/null | head -1
        ' | tr '\n' ' ')"
      LOCAL_KB="$(du -sk "${MIRROR_DIR}/${b}" 2>/dev/null | cut -f1)"
      LOCAL_FILES="$(find "${MIRROR_DIR}/${b}" -type f 2>/dev/null | wc -l | tr -d ' ')"
      printf '%s\tsize=[%s]\tlocal_kb=%s\tlocal_files=%s\tmirror=OK\n' \
        "${b}" "${LIVE_DU:-?}" "${LOCAL_KB:-0}" "${LOCAL_FILES}" >> "${SUMMARY}"
      log "  桶 ${b}：现网 ${LIVE_DU:-?} ／ 本地 ${LOCAL_FILES} 个对象、${LOCAL_KB:-0} KB"
      MINIO_OK=$((MINIO_OK + 1))
    else
      printf '%s\tmirror=FAIL\n' "${b}" >> "${SUMMARY}"
      log "  !! 桶 ${b} 镜像失败（这个桶本轮没备份）：$(tail -3 "${MC_LOG}" 2>/dev/null | tr '\n' ' ')"
      FAILS=$((FAILS + 1))
    fi
  done
  unset MC_HOST_local MINIO_ROOT_USER MINIO_ROOT_PASSWORD
fi

# ---- ⑤ 媒体／辅助卷增量拷贝（cp -u：只补新增与更新，不删旧的）----
# media_data 是 /app/media 的宿主卷（下载原片、切片产物），此前和 MinIO 桶一样「零备份」。
# 卷名从 clip-backend 的挂载里现取，不硬编码 compose 项目名（换机器／改名不至于静默跳卷）。
MEDIA_COPIED=0
MEDIA_VOL="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/media"}}{{.Name}}{{end}}{{end}}' "${MEDIA_C}" 2>/dev/null)"
if [ -n "${MEDIA_VOL}" ] && docker volume inspect "${MEDIA_VOL}" >/dev/null 2>&1; then
  mkdir -p "${MEDIA_DIR}"
  log "⑤ 媒体卷增量拷贝：${MEDIA_VOL} -> ${MEDIA_DIR}（首次全量 14G 级，后续只补差）"
  # 卷里有 root 属主 700 的子目录，非 root 读不进去 ⇒ 这段以 root 跑，拷完 chown 回当前用户
  if docker run --rm -e HOST_UID="${HOST_UID}" -e HOST_GID="${HOST_GID}" \
      -v "${MEDIA_VOL}:/src:ro" -v "${MEDIA_DIR}:/dst" "${ALPINE_IMG}" sh -c \
      'mkdir -p /dst && cp -Rau /src/. /dst/ 2>/dev/null; chown -R "$HOST_UID:$HOST_GID" /dst 2>/dev/null; exit 0'; then
    SRC_N="$(docker run --rm -v "${MEDIA_VOL}:/src:ro" "${ALPINE_IMG}" sh -c 'find /src -type f 2>/dev/null | wc -l' 2>/dev/null | tr -d ' ')"
    DST_N="$(find "${MEDIA_DIR}" -type f 2>/dev/null | wc -l | tr -d ' ')"
    log "  媒体卷：卷内 ${SRC_N:-?} 个文件 ／ 备份侧 ${DST_N:-0} 个，共 $(du -sh "${MEDIA_DIR}" 2>/dev/null | cut -f1)"
    if [ -n "${SRC_N}" ] && [ "${DST_N:-0}" -lt "${SRC_N}" ]; then
      log "  WARN: 备份侧文件数少于卷内（差 $((SRC_N - DST_N)) 个）——正被写入或权限所致，下轮 cp -u 会补上"
      WARNINGS=$((WARNINGS + 1))
    fi
    MEDIA_COPIED=1
  else
    log "  !! 媒体卷拷贝异常退出（本轮媒体没备份）"
    FAILS=$((FAILS + 1))
  fi
else
  log "WARN: 容器 ${MEDIA_C} 上没找到 /app/media 卷，媒体备份跳过"
  WARNINGS=$((WARNINGS + 1))
fi

AUX_LOG=""
for v in ${AUX_VOLS}; do
  if docker volume inspect "${v}" >/dev/null 2>&1; then
    d="${VOL_DIR}/$(basename "${v}")"
    mkdir -p "${d}"
    if docker run --rm -e HOST_UID="${HOST_UID}" -e HOST_GID="${HOST_GID}" \
        -v "${v}:/src:ro" -v "${d}:/dst" "${ALPINE_IMG}" sh -c \
        'mkdir -p /dst && cp -Rau /src/. /dst/ 2>/dev/null; chown -R "$HOST_UID:$HOST_GID" /dst 2>/dev/null; exit 0'; then
      AUX_LOG="${AUX_LOG} ${v}=$(du -sh "${d}" 2>/dev/null | cut -f1)"
    else
      log "  !! 辅助卷 ${v} 拷贝失败"
      FAILS=$((FAILS + 1))
    fi
  else
    log "  辅助卷 ${v} 不存在（跳过）"
  fi
done
[ -n "${AUX_LOG}" ] && log "⑤ 辅助卷备份：${AUX_LOG}"
log "⑤ 不进备份的卷：postgres_data（pg_dump 已覆盖）／redis_data（缓存可重建）／ollama_data（模型可重下）／slice_worker_temp（临时）"

# ---- ⑥ 抽样 md5 对账：拿备份目录里的那份和现网对象逐字节比 ----
# 只抽 0<size<50M 的对象（大文件 md5 会把备份拖成小时级），每桶最多 3 个。
# 一个样本都抽不到 → 报 WARN：宁可吵，也不要「备份看起来成功、其实没验过」。
SAMPLE_TOTAL=0
SAMPLE_MATCH=0
if [ -d "${MIRROR_DIR}" ] && [ "${MINIO_OK}" -gt 0 ]; then
  log "⑥ 抽样 md5 对账开始"
  for b in ${BUCKETS}; do
    [ -d "${MIRROR_DIR}/${b}" ] || continue
    for kf in $(find "${MIRROR_DIR}/${b}" -type f -size +0 -size -50M 2>/dev/null | head -3); do
      SAMPLE_TOTAL=$((SAMPLE_TOTAL + 1))
      rel="${kf#${MIRROR_DIR}/${b}/}"
      lm="$(md5sum "${kf}" | cut -d' ' -f1)"
      rm5="$(docker exec -e B="${b}" -e K="${rel}" "${MINIO_C}" sh -c '
              mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
              mc cat "l/$B/$K" 2>/dev/null
            ' | md5sum | cut -d' ' -f1)"
      if [ -n "${rm5}" ] && [ "${lm}" = "${rm5}" ]; then
        SAMPLE_MATCH=$((SAMPLE_MATCH + 1))
      else
        log "  !! 抽样 md5 不一致/取不到：桶 ${b} 对象 ${rel}（local=${lm} remote=${rm5:-空}）"
        FAILS=$((FAILS + 1))
      fi
    done
  done
  log "  抽样对账：${SAMPLE_MATCH}/${SAMPLE_TOTAL} 个对象与现网逐字节一致"
  printf 'sample=%s/%s\n' "${SAMPLE_MATCH}" "${SAMPLE_TOTAL}" >> "${SUMMARY}"
  [ "${SAMPLE_TOTAL}" -gt 0 ] || { log "  WARN: 本轮一个样本都没抽到（桶全空？）——备份没做过逐字节校验"; WARNINGS=$((WARNINGS + 1)); }
fi

# ---- ⑦ 恢复演练：只用备份目录里的那份，读出时长才算「这份备份能当真还原用」----
ffprobe_dur() {  # $1=宿主目录 $2=目录内相对路径
  docker run --rm --user "${HOST_UID}:${HOST_GID}" -v "$1:/b:ro" \
      --entrypoint ffprobe "${BACKEND_IMG}" \
      -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "/b/$2" 2>/dev/null | head -1
}
DRILL_DONE=0
if [ "${MEDIA_COPIED}" = "1" ] || [ "${MINIO_OK}" -gt 0 ]; then
  log "⑦ 恢复演练开始（只从备份目录取，不碰现网对象）"
  for dir in "${MIRROR_DIR}" "${MEDIA_DIR}"; do
    [ -d "${dir}" ] || continue
    pick="$(find "${dir}" -type f -size +1M -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -1 | cut -f2-)"
    [ -n "${pick}" ] || continue
    DUR="$(ffprobe_dur "${dir}" "${pick#${dir}/}")"
    if [ -n "${DUR}" ]; then
      log "  PASS: $(basename "${dir}")/$(basename "${pick}") —— ffprobe 读出 ${DUR}s（备份里的文件打得开）"
      printf 'drill=%s\tfile=%s\tffprobe_duration=%s\n' "$(basename "${dir}")" "$(basename "${pick}")" "${DUR}" >> "${SUMMARY}"
      DRILL_DONE=$((DRILL_DONE + 1))
    else
      log "  WARN: $(basename "${dir}")/$(basename "${pick}") 读不出时长（非音视频对象属正常）"
      WARNINGS=$((WARNINGS + 1))
    fi
  done
  [ "${DRILL_DONE}" -gt 0 ] || log "  WARN: 本轮没有一次恢复演练成功——备份能不能用仍未被证实"
fi
[ -f "${SUMMARY}" ] && chmod 600 "${SUMMARY}" 2>/dev/null

# ---- ⑧ 保留期清理（只删自己生成的按天文件，前缀锚定；镜像／媒体目录是当前态，不按天删）----
DELETED=0
for f in "${BACKUP_DIR}"/clip-db-*.dump "${BACKUP_DIR}"/env-*.snapshot "${BACKUP_DIR}"/minio-summary-*.txt "${BACKUP_DIR}"/mc-mirror-*.log; do
  [ -e "$f" ] || continue
  if [ "$(find "$f" -mtime +"${KEEP_DAYS}" 2>/dev/null)" ]; then
    rm -f "$f" && DELETED=$((DELETED + 1))
  fi
done

# ---- ⑨ 汇总 ----
log "备份完成：${DB_OUT}（$(du -h "${DB_OUT}" | cut -f1)）＋ ${ENV_OUT}＋ MinIO ${MINIO_OK}/${BUCKET_TOTAL} 桶 ＋ 媒体卷（${MEDIA_DIR}）"
log "校验：抽样 md5 ${SAMPLE_MATCH}/${SAMPLE_TOTAL} 一致；恢复演练 ${DRILL_DONE} 次读出时长；明细见 ${SUMMARY}"
log "备份总占用 $(du -sh "${BACKUP_DIR}" 2>/dev/null | cut -f1)，磁盘余量 $(df -h "${BACKUP_DIR}" | awk 'NR==2{print $4}')"
log "保留期 ${KEEP_DAYS} 天，本轮清理 ${DELETED} 份过期备份；当前顶层共 $(ls "${BACKUP_DIR}" | wc -l | tr -d ' ') 项"
log "回滚步骤见 docs/DEPLOYMENT.md「备份与回滚」一节"

if [ "${WARNINGS}" -gt 0 ]; then
  log "提示：本轮有 ${WARNINGS} 处告警（不判红，但值得回头看上面几行）"
fi
if [ "${FAILS}" -gt 0 ]; then
  log "!! 本轮备份不达标：${FAILS} 处硬伤（镜像失败或抽样对不上）——别把它当成已备份"
  exit 1
fi
exit 0
