#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 停止服务脚本
# 停止所有 Docker 容器，可选择保留数据卷
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
echo -e "${BLUE}  Clip Workflow 服务停止${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# 检查是否有运行中的服务
if ! $COMPOSE_CMD ps 2>/dev/null | grep -q "Up"; then
    echo -e "${YELLOW}[INFO]${NC} 没有正在运行的服务。"
    exit 0
fi

# 显示当前运行的服务
echo -e "${CYAN}当前运行的服务:${NC}"
$COMPOSE_CMD ps
echo ""

# 确认停止
read -rp "确认停止所有服务？(y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}[INFO]${NC} 已取消。"
    exit 0
fi
echo ""

# 询问是否删除数据卷
read -rp "是否同时删除数据卷（将丢失所有数据）？(y/N): " delete_volumes

if [[ "$delete_volumes" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}[WARN]${NC} 正在停止服务并删除数据卷..."
    $COMPOSE_CMD down -v
    echo -e "${GREEN}✓${NC} 服务已停止，数据卷已删除。"
else
    echo -e "${CYAN}[INFO]${NC} 正在停止服务（保留数据卷）..."
    $COMPOSE_CMD down
    echo -e "${GREEN}✓${NC} 服务已停止，数据卷已保留。"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  服务已停止${NC}"
echo -e "${GREEN}============================================${NC}"
echo -e "  重新启动: bash scripts/start.sh"
echo -e "${GREEN}============================================${NC}"
echo ""