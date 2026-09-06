#!/usr/bin/env bash
# 平阅剧单快照刷新：用本地 lark-cli 拉取飞书 wiki 6 个 Sheet 的全量数据，
# 推送到服务器 clip-backend 容器的 /app/media/pingyue/（命名卷，重建不丢）。
#
# 后端逻辑：无 FEISHU_APP_ID/SECRET 时自动回退读取该快照目录
#   （优先 {sheet_id}.json，其次合并后的 平阅剧单.csv）。
#
# 用法：
#   bash scripts/refresh_pingyue_roster.sh             # 拉取并推送
#   bash scripts/refresh_pingyue_roster.sh --no-push   # 仅本地拉取，不推送
#
# 可用环境变量：
#   DEPLOY_REMOTE            默认 cc12703@192.168.1.163
#   PINGYUE_BACKEND_CONTAINER 默认 clip-backend
#   PINGYUE_CONTAINER_DIR    默认 /app/media/pingyue
#   PINGYUE_MAX_CHARS        默认 8000000（配合 --output-path 全量落盘）
#   PINGYUE_OUT_DIR          默认 mktemp 临时目录
#
# 注意：
#   - 首次运行 lark-cli 需在 TRAE 环境内完成扫码授权（本环境已配置）；
#   - 不带 --range，lark-cli 自动读取全区（综合剧单实际延伸到 693 行，
#     文档给的 A1:AJ650 会漏数据），校验 has_more 确认未截断。

set -euo pipefail

PINGYUE_WIKI_URL="https://my.feishu.cn/wiki/PTW7wRpY9iFJ8TkGILfciu1rnrh"
DEPLOY_REMOTE="${DEPLOY_REMOTE:-cc12703@192.168.1.163}"
PINGYUE_BACKEND_CONTAINER="${PINGYUE_BACKEND_CONTAINER:-clip-backend}"
PINGYUE_CONTAINER_DIR="${PINGYUE_CONTAINER_DIR:-/app/media/pingyue}"
PINGYUE_MAX_CHARS="${PINGYUE_MAX_CHARS:-8000000}"

NO_PUSH=0
for arg in "$@"; do
  case "$arg" in
    --no-push) NO_PUSH=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $arg（支持 --no-push）" >&2; exit 1 ;;
  esac
done

# ── lark-cli 定位（优先 PATH，其次 TRAE lark 插件目录取最新版） ──────────────
if command -v lark-cli >/dev/null 2>&1; then
  LARK_CLI="lark-cli"
elif compgen -G "$HOME/.trae-cn/plugins/trae-remote-official/lark/*/bin/lark-cli" >/dev/null; then
  LARK_CLI="$(ls -t "$HOME"/.trae-cn/plugins/trae-remote-official/lark/*/bin/lark-cli | head -1)"
else
  echo "错误: 找不到 lark-cli（PATH 与 ~/.trae-cn/plugins 均未找到）" >&2
  exit 1
fi
echo "lark-cli: $LARK_CLI"

OUT_DIR="${PINGYUE_OUT_DIR:-$(mktemp -d /tmp/pingyue_roster.XXXXXX)}"
mkdir -p "$OUT_DIR"
echo "输出目录: $OUT_DIR"

# 6 个 Sheet：ID 与文档一致；名称仅用于日志
SHEET_IDS=(9dbac7 HbqYes rEysGs qaCvR8 8MyIUq bTRn76)
SHEET_NAMES=(综合剧单 老剧 新剧1 新剧2 新剧3 新剧4)

# ── 并行拉取（不带 --range = 全区，避免行数超文档预估被截断） ────────────────
pull_one() {
  local sid="$1"
  (
    cd "$OUT_DIR"   # lark-cli 要求 --output-path 为当前目录内的相对路径
    "$LARK_CLI" sheets +csv-get \
      --url "$PINGYUE_WIKI_URL" \
      --sheet-id "$sid" \
      --format json \
      --max-chars "$PINGYUE_MAX_CHARS" \
      --output-path "./$sid.json"
  ) >/dev/null
}
PIDS=()
for i in "${!SHEET_IDS[@]}"; do
  sid="${SHEET_IDS[$i]}"
  name="${SHEET_NAMES[$i]}"
  echo "拉取 $name ($sid) ..."
  pull_one "$sid" & PIDS+=($!)
done
FAIL=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || FAIL=1
done
if [ "$FAIL" -ne 0 ]; then
  echo "错误: 部分 lark-cli 拉取命令失败（可能是授权过期，请重新扫码）" >&2
  exit 1
fi

# ── 校验：ok 标志 / annotated_csv 非空 / has_more 截断检查 / 写 _meta.json ──
python3 - "$OUT_DIR" "$(IFS=,; echo "${SHEET_IDS[*]}")" <<'PYEOF'
import json, sys, pathlib

out_dir = pathlib.Path(sys.argv[1])
sheets = sys.argv[2].split(",")
failed = []
for sid in sheets:
    p = out_dir / f"{sid}.json"
    if not p.exists() or p.stat().st_size == 0:
        failed.append(f"{sid}: 文件缺失或为空")
        continue
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        failed.append(f"{sid}: JSON 解析失败: {e}")
        continue
    if payload.get("ok") is False:  # 错误信封（lark-cli 失败时写入）
        failed.append(f"{sid}: {payload.get('error')}")
        continue
    # --output-path 落盘的是纯 data 载荷；兼容带 data 键的信封结构
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    csv_text = (data or {}).get("annotated_csv") or ""
    if not csv_text.strip():
        failed.append(f"{sid}: annotated_csv 为空")
        continue
    rows = csv_text.count("[row=")
    if data.get("has_more"):
        print(f"WARN {sid}: has_more=true，可能未拉全（当前 rows~{rows}），可调大 PINGYUE_MAX_CHARS")
    print(f"OK   {sid}: rows~{rows}, range={data.get('actual_range')}")

meta = {"pulled_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")}
(out_dir / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
print(f"meta: _meta.json pulled_at={meta['pulled_at']}")

if failed:
    print("校验失败:", *failed, sep="\n  ")
    sys.exit(1)
PYEOF

echo "校验通过: 6 个 Sheet 快照就绪"

# ── 推送：清空容器快照目录（防残留旧 Sheet）→ tar 管道进容器 ────────────────
if [ "$NO_PUSH" -eq 1 ]; then
  echo "--no-push 模式：跳过推送，快照保留在 $OUT_DIR"
  exit 0
fi

echo "推送到 $DEPLOY_REMOTE → 容器 $PINGYUE_BACKEND_CONTAINER:$PINGYUE_CONTAINER_DIR ..."
ssh "$DEPLOY_REMOTE" "docker exec $PINGYUE_BACKEND_CONTAINER sh -c 'mkdir -p $PINGYUE_CONTAINER_DIR && rm -rf $PINGYUE_CONTAINER_DIR/*'"
tar czf - -C "$OUT_DIR" . | ssh "$DEPLOY_REMOTE" "docker exec -i $PINGYUE_BACKEND_CONTAINER tar xzf - -C $PINGYUE_CONTAINER_DIR"

ssh "$DEPLOY_REMOTE" "docker exec $PINGYUE_BACKEND_CONTAINER ls -la $PINGYUE_CONTAINER_DIR"
echo "完成: 快照已推送，可在剧目库点击「飞书同步（平阅剧单）」拉取导入"
