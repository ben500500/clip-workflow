#!/bin/bash
# 启动 RPA Chromium（带 --remote-debugging-port，供豆包生成/发布链路通过 CDP 连接）
#
# 背景：不同 playwright 镜像中 chromium 的可执行路径可能随版本变化，
# 且 apt 安装的 chromium-browser 在 Ubuntu 上是 snap 占位符无法真正启动。
# 本脚本按优先级自动探测可用二进制，避免因路径写死导致豆包任务一直「未生成/排队中」。
#
# 多运营者（方案 A，R5/R15）：
# - 若环境变量 CHROMIUM_PROFILES 为 JSON 数组（[{profile_id, port}, ...]），
#   则为每个启用的 PublishProfile 起一个独立 Chromium：
#     * --user-data-dir=/data/chrome-profiles/<profile_id>  （登录态严格隔离，防串号）
#     * --remote-debugging-port=<port>（基址 9223+N，来自路由表端口池）
#     * Chromium 127+ 强制调试口只监听 127.0.0.1（无需额外参数，天然只本机可连，R5）
#   CDP 外露访问统一由 cdp_proxy 鉴权转发（R19）。
# - 未设置 CHROMIUM_PROFILES 时退化为一期单实例（9223，/data/chrome-profiles）。
#
# supervisord 以本脚本为单一 program：脚本 fork 出各实例后 wait，任一实例退出则整体
# 重启（autorestart），保证所有 profile 的 Chromium 生命周期与容器一致。

set -u

# ---- 探测 chromium 可执行文件 ----
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

# 确保用户数据根目录存在
mkdir -p /data/chrome-profiles

# ---- 通用 chromium 启动参数 ----
BASE_ARGS=(
  --no-sandbox
  --disable-dev-shm-usage
  --disable-gpu
  --disable-software-rasterizer
  --disable-web-security
  about:blank
)

# 确保 profiles.json 已由 bootstrap 生成（从 Redis 读 pub:profiles）
if [ ! -f /app/profiles.json ]; then
  python3 /app/bootstrap.py >/dev/null 2>&1 || true
fi

# 是否多运营者模式：优先读 /app/profiles.json（由 bootstrap.py 从 Redis 落盘），
# 其次读环境变量 CHROMIUM_PROFILES（JSON 数组）
PROFILES_JSON=""
if [ -f /app/profiles.json ]; then
  PROFILES_JSON="$(python3 -c 'import json;d=json.load(open("/app/profiles.json"));print(json.dumps(d.get("chrom_profiles",[])))' 2>/dev/null || true)"
fi
if [ -z "$PROFILES_JSON" ]; then
  PROFILES_JSON="${CHROMIUM_PROFILES:-}"
fi

if [ -n "$PROFILES_JSON" ] && [ "$PROFILES_JSON" != "[]" ]; then
  echo "[start_chromium] 多运营者模式：按 CHROMIUM_PROFILES 启动 N 个 Chromium" >&2
  # 用 python3 解析 JSON（镜像内一般有），生成 "profile_id|port|profile_dir" 每行一条
  PIDS=()
  while IFS='|' read -r profile_id port profile_dir; do
    [ -z "$profile_id" ] && continue
    [ -z "$port" ] && port=9223
    # 独立 user-data-dir（登录态严格隔离，R5/R15）
    dir="${profile_dir:-/data/chrome-profiles/$profile_id}"
    mkdir -p "$dir"
    echo "[start_chromium] 启动 profile=$profile_id  port=$port  dir=$dir" >&2
    "$CHROME_BIN" \
      --remote-debugging-port="$port" \
      --user-data-dir="$dir" \
      "${BASE_ARGS[@]}" \
      >"/var/log/chromium-$port.log" 2>&1 &
    PIDS+=("$!")
  done < <(python3 - <<PYEOF
import json, os
raw = os.environ.get("CHROMIUM_PROFILES", "[]")
try:
    items = json.loads(raw)
except Exception:
    items = []
for it in items:
    if not isinstance(it, dict):
        continue
    pid = it.get("profile_id") or ""
    port = it.get("port") or 9223
    pdir = it.get("profile_dir") or ("/data/chrome-profiles/" + pid)
    print(f"{pid}|{port}|{pdir}")
PYEOF
)

  if [ "${#PIDS[@]}" -eq 0 ]; then
    echo "[start_chromium] WARN: CHROMIUM_PROFILES 为空/无效，回退单实例" >&2
    exec "$CHROME_BIN" \
      --remote-debugging-port=9223 \
      --user-data-dir=/data/chrome-profiles \
      "${BASE_ARGS[@]}"
  fi

  # 等待任一实例退出（supervisord autorestart 会重启整个脚本）；
  # 同时周期刷新 profiles.json（backend beat 更新 pub:profiles），
  # 若启用的 profile 集合变化则整体重启以拉起新增/回收实例。
  while :; do
    for i in "${!PIDS[@]}"; do
      if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
        echo "[start_chromium] Chromium(pid=${PIDS[$i]}) 退出，整体重启" >&2
        wait
        exit 0
      fi
    done
    sleep 10
    # 刷新 profile 列表并比较签名，变化则重启
    OLD_SIG="$(cat /app/profiles.json 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1)"
    python3 /app/bootstrap.py >/dev/null 2>&1 || true
    NEW_SIG="$(cat /app/profiles.json 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1)"
    if [ -n "$OLD_SIG" ] && [ "$OLD_SIG" != "$NEW_SIG" ]; then
      echo "[start_chromium] profile 集合变化，整体重启 Chromium" >&2
      wait
      exit 0
    fi
  done
fi

# ---- 一期单实例（默认） ----
exec "$CHROME_BIN" \
  --remote-debugging-port=9223 \
  --user-data-dir=/data/chrome-profiles \
  "${BASE_ARGS[@]}"
