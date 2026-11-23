#!/usr/bin/env bash
# 163 部署铁律配套：compose 用 local-overrides/<file> 挂载覆盖镜像内同名文件，
# scp+build 更新仓库文件后，必须同步覆盖层，否则运行时仍是旧代码
# （2026-11-23 两次踩坑：normalize 路由 404、storage_bytes 缺失）。
# 用法：在 163 仓库根执行 bash scripts/sync-overrides.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
OV=local-overrides
if [ ! -d "$OV" ]; then echo "无 $OV 目录，跳过"; exit 0; fi
for f in "$OV"/*.py; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  for src in backend/app/api/"$base" backend/app/models/"$base" backend/app/services/"$base" backend/app/utils/"$base"; do
    if [ -f "$src" ]; then
      cp "$src" "$f"
      echo "synced: $src -> $f"
      break
    fi
  done
done
echo "完成。若 backend 容器在跑，请 docker rm -f clip-backend && docker compose up -d --no-deps backend 重载"
