#!/bin/bash
# 启动 RPA Chromium（带 --remote-debugging-port，供豆包生成/发布链路通过 CDP 连接）
#
# 背景：不同 playwright 镜像中 chromium 的可执行路径可能随版本变化，
# 且 apt 安装的 chromium-browser 在 Ubuntu 上是 snap 占位符无法真正启动。
# 本脚本按优先级自动探测可用二进制，避免因路径写死导致豆包任务一直「未生成/排队中」。

set -u

# 候选可执行路径（按优先级）
CANDIDATES=(
  "/ms-playwright/chromium-1124/chrome-linux/chrome"
  "/ms-playwright/chromium-1117/chrome-linux/chrome"
  "/ms-playwright/chromium-1148/chrome-linux/chrome"
  "/ms-playwright/chromium-1169/chrome-linux/chrome"
  "/ms-playwright/chromium-1194/chrome-linux/chrome"
  "/ms-playwright/chromium_headless_shell-1124/chrome-linux/headless_shell"
  "$(command -v chromium 2>/dev/null || true)"
  "$(command -v chromium-browser 2>/dev/null || true)"
  "$(command -v google-chrome 2>/dev/null || true)"
)

CHROME_BIN=""
for c in "${CANDIDATES[@]}"; do
  if [ -n "$c" ] && [ -x "$c" ]; then
    CHROME_BIN="$c"
    break
  fi
done

if [ -z "$CHROME_BIN" ]; then
  echo "[start_chromium] ERROR: 未找到可用的 chromium 可执行文件" >&2
  # 尝试用 playwright CLI 安装（兜底，镜像内一般已预装）
  if command -v playwright >/dev/null 2>&1; then
    echo "[start_chromium] 尝试 playwright install chromium ..." >&2
    playwright install chromium 2>&1 >&2
    for c in /ms-playwright/chromium-*/chrome-linux/chrome; do
      if [ -x "$c" ]; then
        CHROME_BIN="$c"
        break
      fi
    done
  fi
fi

if [ -z "$CHROME_BIN" ]; then
  echo "[start_chromium] FATAL: 仍无法定位 chromium，退出" >&2
  exit 1
fi

echo "[start_chromium] 使用浏览器: $CHROME_BIN" >&2

# 确保用户数据目录存在
mkdir -p /data/chrome-profiles

exec "$CHROME_BIN" \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-software-rasterizer \
  --user-data-dir=/data/chrome-profiles \
  about:blank
