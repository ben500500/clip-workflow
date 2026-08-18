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

# ---------------------------------------------------------------------------
# 启动 Chromium 实例。
# 单实例模式：一期（9223，/data/chrome-profiles），多运营者未启用时兜底。
# 多实例模式：按 chrom_profiles（[{profile_id,port,profile_dir}]）为每个启用的
#   profile 起一个独立 Chromium（--user-data-dir 隔离登录态 R5/R15；
#   --remote-debugging-port=<port> 来自路由表端口池，基址 9223+N）。
# 两者都 fork 后台进程并把 PID 记入全局数组 PIDS，供上层 wait 与探活。
# ---------------------------------------------------------------------------
PIDS=()
ACTIVE_MODE=single

_parse_profiles() {
  # 优先读 /app/profiles.json（bootstrap.py 从 Redis pub:profiles 落盘），
  # 其次读环境变量 CHROMIUM_PROFILES。输出 "profile_id|port|profile_dir" 每行一条。
  if [ -f /app/profiles.json ]; then
    python3 -c 'import json
try:
    d=json.load(open("/app/profiles.json"))
    items=d.get("chrom_profiles",[]) or []
except Exception:
    items=[]
for it in items:
    if not isinstance(it,dict):
        continue
    pid=it.get("profile_id") or ""
    port=it.get("port") or 9223
    pdir=it.get("profile_dir") or ("/data/chrome-profiles/"+pid)
    print(f"{pid}|{port}|{pdir}")' 2>/dev/null
  elif [ -n "${CHROMIUM_PROFILES:-}" ]; then
    python3 - <<'PYEOF'
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
  fi
}

_launch_multi() {
  local n=0
  while IFS='|' read -r profile_id port profile_dir; do
    [ -z "$profile_id" ] && continue
    [ -z "$port" ] && port=9223
    dir="${profile_dir:-/data/chrome-profiles/$profile_id}"
    mkdir -p "$dir"
    echo "[start_chromium] 启动 profile=$profile_id  port=$port  dir=$dir" >&2
    "$CHROME_BIN" \
      --remote-debugging-port="$port" \
      --user-data-dir="$dir" \
      "${BASE_ARGS[@]}" \
      >"/var/log/chromium-$port.log" 2>&1 &
    PIDS+=("$!")
    n=$((n+1))
  done < <(_parse_profiles)
  if [ "$n" -eq 0 ]; then
    echo "[start_chromium] 多运营者配置为空/无效，本次不启动实例，等待 profile 出现" >&2
    return 1
  fi
  echo "[start_chromium] 多运营者模式：已启动 $n 个 Chromium" >&2
  return 0
}

_launch_single() {
  echo "[start_chromium] 单实例模式：9223 /data/chrome-profiles" >&2
  "$CHROME_BIN" \
    --remote-debugging-port=9223 \
    --user-data-dir=/data/chrome-profiles \
    "${BASE_ARGS[@]}" \
    >"/var/log/chromium-9223.log" 2>&1 &
  PIDS+=("$!")
}

# 根据当前 profiles 决定并启动实例；返回 0 表示至少起了一个。
_launch() {
  local profile_count
  profile_count="$(_parse_profiles | grep -c '|' || true)"
  if [ "${profile_count:-0}" -gt 0 ]; then
    if _launch_multi; then
      ACTIVE_MODE=multi
      return 0
    fi
  fi
  _launch_single
  ACTIVE_MODE=single
  return 0
}

# ---- 主循环：启动实例并持续探活 / 刷新 profile 列表 ----------------
# 无论是单实例还是多实例，都会每 10s 刷新一次 profiles.json（backend beat 每
# 60s 更新 pub:profiles），当启用集合或模式变化时整体重启，从而保证：
#   * 灰度开启后，sync_multi_operator_profiles 写入的端口池端口有对应 Chromium 监听；
#   * 新增/移除 profile 时自动拉起/回收实例（无需手动重启容器）。
# 任一实例退出时整体退出，由 supervisord autorestart 兜底拉起。
_launch || exit 1

while :; do
  for i in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
      echo "[start_chromium] Chromium(pid=${PIDS[$i]}) 退出，整体重启" >&2
      wait
      exit 0
    fi
  done
  sleep 10
  # 刷新 profile 列表并比较签名，变化则整体重启（拉起新增/回收实例）
  OLD_SIG="$(cat /app/profiles.json 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1)"
  python3 /app/bootstrap.py >/dev/null 2>&1 || true
  NEW_SIG="$(cat /app/profiles.json 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1)"
  if [ -n "$OLD_SIG" ] && [ "$OLD_SIG" != "$NEW_SIG" ]; then
    echo "[start_chromium] profile 集合变化，整体重启 Chromium" >&2
    wait
    exit 0
  fi
done
