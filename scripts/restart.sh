#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 重启服务脚本
# 按顺序重启所有 Docker 服务
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
echo -e "${BLUE}  Clip Workflow 服务重启${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# 询问是否重新构建镜像
read -rp "是否重新构建镜像？(y/N): " rebuild
echo ""

# 停止服务
echo -e "${CYAN}[1/4] 停止现有服务...${NC}"
$COMPOSE_CMD down
echo -e "${GREEN}✓${NC} 服务已停止"
echo ""

# 重新构建（可选）
if [[ "$rebuild" =~ ^[Yy]$ ]]; then
    echo -e "${CYAN}[2/4] 重新构建镜像...${NC}"
    $COMPOSE_CMD build --parallel
    echo -e "${GREEN}✓${NC} 镜像构建完成"
    echo ""
else
    echo -e "${CYAN}[2/4] 跳过镜像构建${NC}"
    echo ""
fi

# 启动服务
echo -e "${CYAN}[3/4] 启动服务...${NC}"
$COMPOSE_CMD up -d
echo -e "${GREEN}✓${NC} 服务已启动"
echo ""

# 健康检查
echo -e "${CYAN}[4/4] 执行健康检查...${NC}"
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

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Clip Workflow 已重启完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo -e "  前端应用: http://localhost:${nginx_port}"
echo -e "  API 接口: http://localhost:${nginx_port}/api/"
echo ""