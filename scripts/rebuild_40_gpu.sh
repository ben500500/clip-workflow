#!/usr/bin/env bash
#
# rebuild_40_gpu.sh — 40 生产「GPU 服务」一键重建 / 校验
#
# 背景（2026-09-02 固化）：40 上以下服务依赖 GPU，且重建时**必须**带
# docker-compose.gpu.yml overlay，否则会被静默打回纯 CPU：
#   - autoclip   ：FunASR ASR 走 CUDA（需 .env 配 TORCH_INDEX_URL=.../cu121）
#   - slice-worker / slice-worker-2：切片 NVENC（h264_nvenc）
#   - ollama     ：画面理解本地视觉（当前用在线 mimo-v2.5，ollama 为兜底，可选重建）
# 本脚本强制固定 -f docker-compose.yml -f docker-compose.gpu.yml，
# 统一处理「先 stop 旧容器（避免 stop_grace_period=15m 卡住 compose 重建）→ build → up → 校验」。
#
# 用法（在 40 服务器 clip-workflow 目录内执行）：
#   ./scripts/rebuild_40_gpu.sh            # 重建默认 GPU 服务(autoclip+slice-worker×2)
#   ./scripts/rebuild_40_gpu.sh verify     # 只校验当前容器 GPU 状态，不重建
#   ./scripts/rebuild_40_gpu.sh autoclip   # 只重建 autoclip
#   ./scripts/rebuild_40_gpu.sh slice-worker slice-worker-2
#
set -uo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.gpu.yml)
DEFAULT_SVCS=(autoclip slice-worker slice-worker-2)
STOP_WAIT=20

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "[$(date +%H:%M:%S)] ERROR: $*" >&2; exit 1; }

check_gpu_env() {
  # autoclip 走 GPU 需 .env 指定 CUDA 轮子源；仅提示不阻断（CPU 也能跑）
  if ! grep -qE "^TORCH_INDEX_URL=.*cu1(18|21|22|24|26)" .env 2>/dev/null; then
    log "WARN: .env 未配 TORCH_INDEX_URL=...cu1xx，autoclip 将构建为 CPU torch（FunASR 走 CPU）"
  fi
}

verify_gpu() {
  local svc="$1"
  local cid
  cid=$(docker ps -q --filter "name=clip-${svc}" | head -1)
  [ -n "$cid" ] || { echo "  ✗ ${svc}: 容器未运行"; return 1; }
  local dev
  dev=$(docker inspect "$cid" -f '{{json .HostConfig.DeviceRequests}}' 2>/dev/null)
  if echo "$dev" | grep -q 'nvidia'; then
    echo "  ✓ ${svc}: GPU 已透传"
  else
    echo "  ✗ ${svc}: 未透传 GPU（DeviceRequests 无 nvidia）——重建务必带 docker-compose.gpu.yml"
    return 1
  fi
}

verify() {
  log "=== 校验 GPU 状态 ==="
  local ok=0
  for s in autoclip slice-worker slice-worker-2; do verify_gpu "$s" || ok=1; done

  echo "--- autoclip: torch/cuda + ASR 设备 ---"
  docker exec clip-autoclip python -c "import torch;print('  torch',torch.__version__,'cuda:',torch.cuda.is_available())" 2>&1 | tail -1
  docker logs clip-autoclip --since 24h 2>&1 | grep -iE "FunASR 推理设备" | tail -1 | sed 's/^/  /' || echo "  (近期无 ASR 运行记录)"

  echo "--- slice-worker: 实际编码器（有 GPU 应 h264_nvenc）---"
  docker exec clip-slice-worker python3 -c "
import sys; sys.path.insert(0,'/app/engines')
from slice import detect_best_encoder
print('  encoder =>', detect_best_encoder())" 2>&1 | tail -2 | sed 's/^\[slice.py\].*/  (探测跳过记录)/'

  [ "$ok" = "0" ] && log "GPU 校验通过 ✅" || { log "GPU 校验存在失败，请检查 ⚠️"; exit 1; }
}

rebuild() {
  local svcs=("$@")
  [ ${#svcs[@]} -gt 0 ] || svcs=("${DEFAULT_SVCS[@]}")
  check_gpu_env
  log "目标服务: ${svcs[*]}（固定 gpu overlay）"

  # 先停旧容器（容错：不存在则跳过），避免 compose 优雅停机 stop_grace_period=15m 卡死重建
  local names=()
  for s in "${svcs[@]}"; do names+=("clip-$s"); done
  docker stop -t "$STOP_WAIT" "${names[@]}" 2>/dev/null || true

  log "构建镜像..."
  "${COMPOSE[@]}" build "${svcs[@]}" || die "镜像构建失败"
  log "拉起容器..."
  "${COMPOSE[@]}" up -d "${svcs[@]}" || die "容器拉起失败"
  sleep 20
  verify
}

case "${1:-}" in
  verify) shift; verify ;;
  *)      rebuild "$@" ;;
esac
