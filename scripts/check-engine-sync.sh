#!/usr/bin/env bash
# 引擎双份一致性检查（2026-11-20 评审 架构师 P0-2 快速胜利）
#
# 背景：engines/slice.py（源）与 slice-worker/engines/slice.py（烤进 worker 镜像）
# 是同一文件的两份拷贝，历史上靠 scripts/sync-engines-to-worker.sh 在构建前同步。
# 该脚本一旦被忘记执行，worker 镜像里的引擎就落后/超前于源码，且无任何报错
# ——树内实测曾分叉 4975 vs 4867 行。本脚本用 sha256 兜底拦截：
#   - CI/部署前调用：不一致即非零退出，阻断构建；
#   --fix：不一致时自动执行一次同步再复查。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/engines/slice.py"
DST="$ROOT/slice-worker/engines/slice.py"

if [[ ! -f "$SRC" || ! -f "$DST" ]]; then
    echo "check-engine-sync: 找不到引擎文件（$SRC 或 $DST）" >&2
    exit 2
fi

SRC_HASH=$(shasum -a 256 "$SRC" | awk '{print $1}')
DST_HASH=$(shasum -a 256 "$DST" | awk '{print $1}')

if [[ "$SRC_HASH" == "$DST_HASH" ]]; then
    echo "check-engine-sync: OK（engines/slice.py 与 slice-worker/engines/slice.py 一致）"
    exit 0
fi

echo "check-engine-sync: 引擎双份不一致！engines/slice.py 与 slice-worker/engines/slice.py sha256 不同" >&2
echo "  src: $SRC_HASH" >&2
echo "  dst: $DST_HASH" >&2

if [[ "${1:-}" == "--fix" ]]; then
    echo "check-engine-sync: --fix 执行一次 sync-engines-to-worker.sh 后复查…" >&2
    bash "$ROOT/scripts/sync-engines-to-worker.sh"
    DST_HASH=$(shasum -a 256 "$DST" | awk '{print $1}')
    if [[ "$SRC_HASH" == "$DST_HASH" ]]; then
        echo "check-engine-sync: 同步后一致，OK"
        exit 0
    fi
    echo "check-engine-sync: 同步后仍不一致，请人工检查" >&2
    exit 1
fi

echo "check-engine-sync: 请先执行 bash scripts/sync-engines-to-worker.sh（构建 worker 前的铁律）" >&2
exit 1
