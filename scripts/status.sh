#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 状态检查脚本
# 查看所有服务的运行状态、资源使用和健康检查信息
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
echo -e "${BLUE}  Clip Workflow 服务状态${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# 检查 .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[WARN]${NC} .env 文件不存在，某些信息可能不准确"
    echo ""
fi

# 1. 服务运行状态
echo -e "${CYAN}[1/3] 服务运行状态${NC}"
echo ""

if $COMPOSE_CMD ps 2>/dev/null | grep -q "CONTAINER"; then
    $COMPOSE_CMD ps
else
    echo -e "  ${YELLOW}暂无服务运行${NC}"
fi

echo ""

# 2. 资源使用情况
echo -e "${CYAN}[2/3] 资源使用情况${NC}"
echo ""

# 获取 clip 相关容器的资源使用
if docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}" 2>/dev/null | grep -q "clip"; then
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}" 2>/dev/null | grep -E "clip|NAME" || true
else
    echo -e "  ${YELLOW}没有运行中的 Clip Workflow 容器${NC}"
fi

echo ""

# 3. 健康检查
echo -e "${CYAN}[3/3] 健康检查${NC}"
echo ""

# 获取 Nginx 端口
nginx_port=$(grep -E "^NGINX_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "80")

# 健康检查端点
health_endpoints=(
    "http://localhost:${nginx_port}/health"
)

for endpoint in "${health_endpoints[@]}"; do
    if curl -sf "$endpoint" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $endpoint - 正常"
    else
        echo -e "  ${RED}✗${NC} $endpoint - 不可达"
    fi
done

echo ""

# 显示访问地址
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  访问地址${NC}"
echo -e "${BLUE}============================================${NC}"
echo -e "  前端应用:       http://localhost:${nginx_port}"
echo -e "  API 接口:        http://localhost:${nginx_port}/api/"
echo -e "  MinIO 控制台:    http://localhost:$(grep -E "^MINIO_CONSOLE_PORT=" .env 2>/dev/null | cut -d= -f2 || echo '9001')"
echo -e "  管理命令:        bash scripts/logs.sh"
echo -e "${BLUE}============================================${NC}"
echo ""