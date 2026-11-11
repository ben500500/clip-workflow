#!/usr/bin/env bash
#
# backup_server.sh — 生产服务器一键备份（批 M·评审一 P1-5）
#
# 背景：此前全仓 grep 不到任何备份/回滚沉淀，历史 .env 事故恢复靠人肉。
# 本脚本在【服务器本机】跑（与 deploy_server.sh 的远端机同台）：
#   1. pg_dump 整库（docker compose exec postgres，不依赖宿主机装 psql）；
#   2. .env 快照（部署变量丢了等于全站失联，必须和库一起备份）；
#   3. gzip 完整性自检 + 保留期清理（默认 14 天）。
#
# 用法（服务器上）：
#   bash scripts/backup_server.sh                 # 备到默认目录 /home/<user>/clip-backups
#   BACKUP_DIR=/data/backup bash scripts/backup_server.sh
#   KEEP_DAYS=30 bash scripts/backup_server.sh
#
# 挂 cron：**已于 2026-11-11 装在 163 的 cc12703 crontab 里，别再重复装**。
#   25 3 * * * cd /home/cc12703/clip-workflow && PATH=/snap/bin:/usr/local/bin:/usr/bin:/bin /usr/bin/bash scripts/backup_server.sh >> logs/backup.log 2>&1
#   两个当时踩过的点，改回去备份就会静默失效：
#     · 不写 03:40：那一分钟已被 revenue_keepalive 占用（同机同一个 crontab）；
#     · PATH 必须显式带上 /snap/bin：163 的 docker 是 snap 装的（/snap/bin/docker），
#       而 cron 继承的 PATH 里没有它 —— 不加这行就是「每天定点跑、每天 command not found」，
#       而失败只落在 logs/backup.log 里，没人看就等于没有。
#   核对：crontab -l | grep backup_server ；日志：tail -20 /home/cc12703/clip-workflow/logs/backup.log
#   卸载：crontab -l | grep -v backup_server | crontab -
#
# 首次实跑（2026-11-11 本机验过）：dump 4.1M / 1 秒，pg_restore --list 自检通过。
#
# ⚠️ 不覆盖 MinIO 数据卷（媒体文件量大，另行按卷快照策略处理，见 docs/DEPLOYMENT.md 回滚一节）。

set -uo pipefail

# ============ 配置（可用环境变量覆盖） ============
# 与 docker-compose.yml 同一口径：POSTGRES_USER/POSTGRES_DB 从根 .env 读，读不到用默认值
COMPOSE_DIR="${BACKUP_COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/home/$(whoami)/clip-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

log() { echo "[$(date '+%F %T')] $*"; }
die() { log "!! $*"; exit 1; }

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
log "pg_dump 开始：库 ${PG_DB}（用户 ${PG_USER}）→ ${DB_OUT}"
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

# ---- ④ 保留期清理（只删自己生成的两类文件，按文件名前缀锚定）----
DELETED=0
for f in "${BACKUP_DIR}"/clip-db-*.dump "${BACKUP_DIR}"/env-*.snapshot; do
  [ -e "$f" ] || continue
  if [ "$(find "$f" -mtime +"${KEEP_DAYS}" 2>/dev/null)" ]; then
    rm -f "$f" && DELETED=$((DELETED + 1))
  fi
done

log "备份完成：${DB_OUT}（$(du -h "${DB_OUT}" | cut -f1)）＋ ${ENV_OUT}"
log "保留期 ${KEEP_DAYS} 天，本轮清理 ${DELETED} 份过期备份；当前共 $(ls "${BACKUP_DIR}" | wc -l | tr -d ' ') 份"
log "回滚步骤见 docs/DEPLOYMENT.md「备份与回滚」一节"
