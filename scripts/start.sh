#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 一键启动脚本
# 构建并启动所有 Docker 服务
# =============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 检查 Docker Compose 命令
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}[ERROR]${NC} Docker Compose 未安装"
    exit 1
fi

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Clip Workflow 服务启动${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# 检查 .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[WARN]${NC} .env 文件不存在，请先运行 scripts/init.sh"
    exit 1
fi

# 构建镜像
echo -e "${CYAN}[1/3] 构建 Docker 镜像...${NC}"
$COMPOSE_CMD build --parallel
echo -e "${GREEN}✓${NC} 镜像构建完成"
echo ""

# 启动服务
echo -e "${CYAN}[2/3] 启动所有服务...${NC}"
$COMPOSE_CMD up -d
echo -e "${GREEN}✓${NC} 所有服务已启动"
echo ""

# 健康检查
echo -e "${CYAN}[3/3] 执行健康检查...${NC}"
max_retries=30
retry_interval=5

for i in $(seq 1 "$max_retries"); do
    if $COMPOSE_CMD ps --status=running 2>/dev/null | grep -q "nginx"; then
        echo -e "${GREEN}✓${NC} 所有服务已就绪"
        break
    fi
    if [ "$i" -eq "$max_retries" ]; then
        echo -e "${YELLOW}[WARN]${NC} 服务未在预期时间内完全就绪，请检查日志"
    fi
    sleep "$retry_interval"
done

echo ""

# 显示服务状态
echo -e "${BLUE}==================== 服务状态 ====================${NC}"
$COMPOSE_CMD ps
echo -e "${BLUE}===================================================${NC}"
echo ""

# 打印访问地址
nginx_port=$(grep -E "^NGINX_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "80")
minio_console_port=$(grep -E "^MINIO_CONSOLE_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "9001")

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Clip Workflow 已启动！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  访问地址:"
echo -e "  ${CYAN}  前端应用:${NC}      http://localhost:${nginx_port}"
echo -e "  ${CYAN}  API 接口:${NC}       http://localhost:${nginx_port}/api/"
echo -e "  ${CYAN}  MinIO 控制台:${NC}   http://localhost:${minio_console_port}"
echo ""
echo -e "  查看日志: bash scripts/logs.sh"
echo -e "  停止服务: bash scripts/stop.sh"
echo ""