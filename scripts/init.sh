#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 项目初始化脚本
# 用于初始化项目目录结构、检查依赖并引导配置
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

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Clip Workflow 项目初始化${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# ==================== 1. 创建目录结构 ====================
echo -e "${CYAN}[1/5] 创建目录结构...${NC}"

mkdir -p \
    backend/app \
    backend/app/api \
    backend/app/core \
    backend/app/models \
    backend/app/schemas \
    backend/app/services \
    backend/app/tasks \
    backend/app/utils \
    backend/app/workers \
    frontend/src \
    frontend/public \
    autoclip/app \
    autoclip/app/api \
    autoclip/app/core \
    autoclip/app/services \
    autoclip/app/tasks \
    engines \
    scripts \
    docs \
    logs \
    media \
    data/postgres \
    data/redis \
    data/minio

echo -e "  ${GREEN}✓${NC} 目录结构已创建"
echo ""

# ==================== 2. 检查引擎脚本 ====================
echo -e "${CYAN}[2/5] 检查引擎脚本...${NC}"

if [ -d "engines" ]; then
    engine_count=$(ls -1 engines/*.sh 2>/dev/null | wc -l)
    if [ "$engine_count" -gt 0 ]; then
        echo -e "  ${GREEN}✓${NC} 发现 $engine_count 个引擎脚本"
        for f in engines/*.sh; do
            echo "    - $(basename "$f")"
        done
    else
        echo -e "  ${YELLOW}⚠${NC} engines 目录中没有发现 .sh 脚本"
        echo "    请将引擎脚本放置在 engines/ 目录下"
    fi
else
    echo -e "  ${YELLOW}⚠${NC} engines 目录不存在"
fi
echo ""

# ==================== 3. 配置环境变量 ====================
echo -e "${CYAN}[3/5] 配置环境变量...${NC}"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "  ${GREEN}✓${NC} 已从 .env.example 创建 .env 文件"
        echo ""
        echo -e "  ${YELLOW}请编辑 .env 文件，修改以下配置项：${NC}"
        echo "    - SECRET_KEY: 设置为随机字符串"
        echo "    - POSTGRES_PASSWORD: 修改数据库密码"
        echo "    - REDIS_PASSWORD: 修改 Redis 密码"
        echo "    - MINIO_ROOT_PASSWORD: 修改 MinIO 密码"
        echo "    - DASHSCOPE_API_KEY: 如果使用 AutoClip AI 功能"
        echo ""
        echo -e "  ${YELLOW}可以使用以下命令生成随机密钥：${NC}"
        echo "    openssl rand -hex 32"
        echo ""
    else
        echo -e "  ${RED}✗${NC} .env.example 文件不存在，请手动创建 .env 文件"
    fi
else
    echo -e "  ${GREEN}✓${NC} .env 文件已存在"
fi
echo ""

# ==================== 4. 检查 Docker 环境 ====================
echo -e "${CYAN}[4/5] 检查 Docker 环境...${NC}"

docker_ok=true

if command -v docker &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Docker 已安装: $(docker --version)"
else
    echo -e "  ${RED}✗${NC} Docker 未安装"
    echo "    请安装 Docker: https://docs.docker.com/get-docker/"
    docker_ok=false
fi

if docker compose version &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Docker Compose 已安装: $(docker compose version)"
elif command -v docker-compose &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} docker-compose 已安装: $(docker-compose --version)"
else
    echo -e "  ${RED}✗${NC} Docker Compose 未安装"
    echo "    请安装 Docker Compose: https://docs.docker.com/compose/install/"
    docker_ok=false
fi

if $docker_ok && docker info &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Docker 守护进程运行正常"
elif $docker_ok; then
    echo -e "  ${RED}✗${NC} Docker 守护进程未运行"
    echo "    请启动 Docker 后重试"
fi
echo ""

# ==================== 5. 提供启动命令 ====================
echo -e "${CYAN}[5/5] 下一步操作...${NC}"

echo -e "  完成初始化后，可以使用以下命令："
echo ""
echo -e "  ${YELLOW}  一键部署:${NC}"
echo -e "    bash deploy.sh"
echo ""
echo -e "  ${YELLOW}  或分步操作:${NC}"
echo -e "    bash scripts/start.sh    # 启动所有服务"
echo -e "    bash scripts/status.sh   # 查看服务状态"
echo -e "    bash scripts/logs.sh     # 查看日志"
echo -e "    bash scripts/stop.sh     # 停止所有服务"
echo -e "    bash scripts/restart.sh  # 重启所有服务"
echo ""
echo -e "  ${YELLOW}  手动 Docker Compose 命令:${NC}"
echo -e "    docker compose build     # 构建镜像"
echo -e "    docker compose up -d     # 启动服务"
echo -e "    docker compose logs -f   # 查看日志"
echo -e "    docker compose down      # 停止服务"
echo -e "    docker compose ps        # 查看状态"
echo ""

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  初始化完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""