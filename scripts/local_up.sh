#!/usr/bin/env bash
# 本地一键部署脚本（2026-11-21 评审 S 级建议落地）
# 用法：bash scripts/local_up.sh
# 前置：Docker Desktop（arm64）已启动；仓库内 .env 已配置（DEBUG=true + SEED_USERS_JSON 种子账号）
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

MIRRORS=("docker.m.daocloud.io" "docker.1ms.run")
LOCAL_HOST_PORT_BACKEND="${BACKEND_PORT:-8001}"
LOCAL_HOST_PORT_AUTOCLIP="${AUTOCLIP_PORT:-18000}"

step() { echo "[local_up] $*"; }

# ── 1. 运行时与架构预检 ──
step "1/5 预检 Docker 运行时"
docker info >/dev/null 2>&1 || { echo "Docker 未就绪：请先启动 Docker Desktop"; exit 1; }
ARCH=$(docker version --format '{{.Server.Arch}}')
step "运行时就绪（arch=$ARCH）"

# ── 2. 宿主端口占用预检 ──
step "2/5 端口占用预检（80/8001/9000/9001/$LOCAL_HOST_PORT_AUTOCLIP）"
CONFLICT=()
for p in 80 "$LOCAL_HOST_PORT_BACKEND" 9000 9001 "$LOCAL_HOST_PORT_AUTOCLIP"; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then CONFLICT+=("$p"); fi
done
if (( ${#CONFLICT[@]} )); then
  echo "端口被占用：${CONFLICT[*]}——请修改 .env 对应端口（如 AUTOCLIP_PORT/BACKEND_PORT/NGINX_PORT）后重试"
  exit 1
fi
step "端口全部可用"

# ── 3. 基础镜像就绪检查（缺失时经镜像源拉取，minio 系提示 163 导入兜底） ──
step "3/5 基础镜像检查"
BASES=("library/debian:bookworm-slim" "library/golang:1.22-alpine" "library/nginx:alpine"
       "library/nginx:1.28-alpine" "library/node:18-alpine" "library/python:3.11-slim"
       "library/postgres:15-alpine" "library/redis:7-alpine" "minio/minio:latest" "minio/mc:latest")
MISSING=()
for img in "${BASES[@]}"; do
  docker image inspect "$img" >/dev/null 2>&1 || MISSING+=("$img")
done
if (( ${#MISSING[@]} )); then
  for img in "${MISSING[@]}"; do
    pulled=0
    for m in "${MIRRORS[@]}"; do
      if docker pull "$m/$img" >/dev/null 2>&1; then docker tag "$m/$img" "$img"; pulled=1; break; fi
    done
    if (( pulled )); then step "已拉取 $img"; else step "警告：$img 各镜像源均不可得（minio 系可用 163 docker save|ssh|load 导入兜底）"; fi
  done
else
  step "基础镜像全部就绪"
fi

# ── 4. 构建并启动（本地 override 剥离 163 专属挂载/跳过重服务） ──
step "4/5 构建 + 启动（backend/frontend/slice-worker 源码构建，约 12-15 分钟）"
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build || exit 1

# ── 5. 冒烟 ──
step "5/5 冒烟（等待 backend healthy）"
for i in $(seq 1 30); do
  if curl -sf http://localhost:"$LOCAL_HOST_PORT_BACKEND"/api/health >/dev/null 2>&1; then break; fi
  sleep 5
done
curl -sf http://localhost:"$LOCAL_HOST_PORT_BACKEND"/api/health >/dev/null \
  && step "后端 health OK；前端 http://localhost/ ；账号见 .env SEED_USERS_JSON" \
  || { echo "后端 health 未就绪，请查 docker logs clip-backend"; exit 1; }
step "完成。注意：全新库以 create_all 建表为准（迁移链勿直接 upgrade head，见 DEPLOYMENT.md）"
