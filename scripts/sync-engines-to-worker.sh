#!/usr/bin/env bash
#
# sync-engines-to-worker.sh — 把仓库根 engines/ 同步进 slice-worker/engines/
#
# slice-worker 的 Docker build context 是 ./slice-worker，无法 COPY 仓库根的
# engines/（在 context 之外）。打包/构建前先跑本脚本把 engines/ 拷进去，
# Dockerfile 的 `COPY . .` 才能把引擎打入镜像。
#
# 副本是构建产物，已在 .gitignore 忽略，勿提交（与 backend/alembic/ 同一套路）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/engines"
DST="$ROOT/slice-worker/engines"

[ -d "$SRC" ] || { echo "❌ engines/ 不存在: $SRC" >&2; exit 1; }

# 整目录覆盖：先清旧副本（可能有已删除的残留文件），再全量拷入
rm -rf "$DST"
cp -r "$SRC" "$DST"

# 清掉不进镜像/不参与版本判定的杂物（与 engineExclude 对齐）
find "$DST" \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \
  -o -name '.DS_Store' -o -name 'README.md' \) -delete 2>/dev/null || true

echo "✓ engines/ → slice-worker/engines/ ($(find "$DST" -type f | wc -l | tr -d ' ') files)"
