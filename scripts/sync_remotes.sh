#!/bin/bash
# clip-workflow 双仓同步脚本
# 用法: bash scripts/sync_remotes.sh
# 逻辑: 先推 CNB(主) -> 成功后再推 GitHub(备)；任一失败即中止，保证备份不超前于主仓。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

BRANCH="$(git branch --show-current)"
echo "[sync] 仓库: $REPO_DIR  分支: $BRANCH"

echo "[sync] 1/2 推送 CNB(主仓)..."
# 用 HTTP/1.1 规避 macOS git + Secure Transport 的 HTTP/2 framing layer 偶发错误
git -c http.version=HTTP/1.1 push cnb "$BRANCH"

echo "[sync] 2/2 推送 GitHub(备份仓)..."
git -c http.version=HTTP/1.1 push origin "$BRANCH"

echo "[sync] 完成 ✅"
