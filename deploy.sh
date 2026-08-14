#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 一键部署脚本
# 支持全新部署和增量更新
# =============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# ==================== 工具函数 ====================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

# ==================== 前置检查 ====================

check_prerequisites() {
    log_step "检查系统依赖..."

    # 检查 Docker
    if command -v docker &> /dev/null; then
        log_info "Docker 已安装: $(docker --version)"
    else
        log_error "Docker 未安装。请先安装 Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi

    # 检查 Docker Compose
    if docker compose version &> /dev/null; then
        log_info "Docker Compose 已安装: $(docker compose version)"
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        log_info "docker-compose 已安装: $(docker-compose --version)"
        COMPOSE_CMD="docker-compose"
    else
        log_error "Docker Compose 未安装。请先安装 Docker Compose: https://docs.docker.com/compose/install/"
        exit 1
    fi

    # GPU 加速 overlay：设置 GPU_ACCELERATION=1 时加载 docker-compose.gpu.yml
    # （为 ollama/autoclip/slice-worker 透传 NVIDIA GPU，需部署机已装 nvidia-container-toolkit）
    if [ "${GPU_ACCELERATION:-0}" = "1" ]; then
        if [ -f "docker-compose.gpu.yml" ]; then
            COMPOSE_CMD="$COMPOSE_CMD -f docker-compose.yml -f docker-compose.gpu.yml"
            log_info "已启用 GPU 加速 overlay（docker-compose.gpu.yml）"
        else
            log_warn "GPU_ACCELERATION=1 但未找到 docker-compose.gpu.yml，忽略 GPU overlay"
        fi
    fi

    # 检查 Docker 运行状态
    if ! docker info &> /dev/null; then
        log_error "Docker 守护进程未运行。请先启动 Docker。"
        exit 1
    fi

    log_info "系统依赖检查通过。"
}

# ==================== 环境变量检查 ====================

check_env_file() {
    log_step "检查环境变量配置..."

    if [ ! -f ".env" ]; then
        log_warn ".env 文件不存在，正在从 .env.example 复制..."

        if [ -f ".env.example" ]; then
            cp .env.example .env
            log_info ".env 文件已创建，请根据实际环境修改配置。"
            log_warn "请务必修改以下配置项："
            echo "  - SECRET_KEY (设置为随机字符串)"
            echo "  - POSTGRES_PASSWORD (修改数据库密码)"
            echo "  - REDIS_PASSWORD (修改 Redis 密码)"
            echo "  - MINIO_ROOT_PASSWORD (修改 MinIO 密码)"
            echo "  - DASHSCOPE_API_KEY (如果使用 AutoClip 功能)"
            echo ""
            read -rp "是否继续部署？(y/N): " confirm
            if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
                log_info "部署已取消。请编辑 .env 文件后重新运行脚本。"
                exit 0
            fi
        else
            log_error ".env.example 文件不存在，无法创建 .env 文件。"
            exit 1
        fi
    else
        log_info ".env 文件已存在。"

        # 检查关键变量是否已修改
        if grep -q "SECRET_KEY=change-this-to-a-random-secret-key" .env 2>/dev/null; then
            log_warn "SECRET_KEY 仍为默认值，建议修改为随机字符串。"
        fi
    fi
}

# ==================== 目录检查 ====================

check_directories() {
    log_step "检查必要目录..."

    mkdir -p logs
    log_info "目录结构已就绪。"
}

# ==================== 镜像构建 ====================

build_images() {
    log_step "构建 Docker 镜像..."

    # 检查 autoclip 目录
    if [ -d "autoclip" ] && [ -f "autoclip/Dockerfile" ]; then
        log_info "AutoClip 目录存在，将构建 autoclip 镜像。"
    else
        log_warn "autoclip 目录或 Dockerfile 不存在，将跳过 autoclip 镜像构建。"
    fi

    # 检查 backend 目录
    if [ -d "backend" ] && [ -f "backend/Dockerfile" ]; then
        log_info "Backend 目录存在，将构建 backend 镜像。"
    else
        log_warn "backend 目录或 Dockerfile 不存在，将跳过 backend 镜像构建。"
    fi

    # 检查 frontend 目录
    if [ -d "frontend" ] && [ -f "frontend/Dockerfile" ]; then
        log_info "Frontend 目录存在，将构建 frontend 镜像。"
    else
        log_warn "frontend 目录或 Dockerfile 不存在，将跳过 frontend 镜像构建。"
    fi

    # 检查 slice-worker 目录
    if [ -d "slice-worker" ] && [ -f "slice-worker/Dockerfile" ]; then
        log_info "Slice Worker 目录存在，将构建 slice-worker 镜像。"
    else
        log_warn "slice-worker 目录或 Dockerfile 不存在，将跳过 slice-worker 镜像构建。"
    fi

    # 执行构建
    $COMPOSE_CMD build --parallel

    log_info "Docker 镜像构建完成。"
}

# ==================== 服务启动 ====================

start_services() {
    log_step "启动服务..."

    $COMPOSE_CMD up -d

    log_info "所有服务已启动。"
}

# ==================== 健康检查 ====================

health_check() {
    log_step "执行健康检查..."
    local max_retries=30
    local retry_interval=5
    
    # 等待 Nginx 就绪
    for i in $(seq 1 "$max_retries"); do
        if $COMPOSE_CMD ps --status=running 2>/dev/null | grep -q "nginx"; then
            log_info "Nginx 服务已就绪。"
            break
        fi
        if [ "$i" -eq "$max_retries" ]; then
            log_warn "Nginx 服务未在预期时间内就绪。"
        fi
        sleep "$retry_interval"
    done
    
    # 检查各服务 API 可用性
    local nginx_port
    nginx_port=$(grep -E "^NGINX_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "80")
    
    # 检查 Backend API
    for i in $(seq 1 12); do
        if curl -sf http://localhost:${nginx_port}/api/health > /dev/null 2>&1; then
            log_info "Backend API 已就绪。"
            break
        fi
        [ "$i" -eq 12 ] && log_warn "Backend API 未在预期时间内就绪。"
        sleep 5
    done
    
    # 检查 PostgreSQL
    if $COMPOSE_CMD exec -T postgres pg_isready -U ${POSTGRES_USER:-clipworkflow} > /dev/null 2>&1; then
        log_info "PostgreSQL 已就绪。"
    else
        log_warn "PostgreSQL 未就绪，请检查日志。"
    fi
    
    # 检查 Redis
    if $COMPOSE_CMD exec -T redis redis-cli -a "${REDIS_PASSWORD:-}" ping > /dev/null 2>&1; then
        log_info "Redis 已就绪。"
    else
        log_warn "Redis 未就绪，请检查日志。"
    fi
    
    # 检查 MinIO
    if curl -sf http://localhost:${MINIO_PORT:-9000}/minio/health/live > /dev/null 2>&1; then
        log_info "MinIO 已就绪。"
    else
        log_warn "MinIO 未就绪，请检查日志。"
    fi
    
    # 显示服务状态
    echo ""
    echo -e "${BLUE}==================== 服务状态 ====================${NC}"
    $COMPOSE_CMD ps
    echo -e "${BLUE}===================================================${NC}"
    echo ""
}

# ==================== 打印访问地址 ====================

print_access_urls() {
    # 获取 Nginx 端口
    local nginx_port
    nginx_port=$(grep -E "^NGINX_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "80")

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Clip Workflow 部署完成！${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "  访问地址:"
    echo -e "  ${CYAN}  前端应用:${NC}      http://localhost:${nginx_port}"
    echo -e "  ${CYAN}  API 接口:${NC}       http://localhost:${nginx_port}/api/"
    echo -e "  ${CYAN}  API 文档:${NC}       http://localhost:${nginx_port}/docs"
    echo -e "  ${CYAN}  MinIO 控制台:${NC}   http://localhost:${MINIO_CONSOLE_PORT:-9001}"
    echo -e "  ${CYAN}  MinIO API:${NC}      http://localhost:${MINIO_PORT:-9000}"
    echo ""
    echo -e "  管理命令:"
    echo -e "  ${YELLOW}  查看日志:${NC}       bash scripts/logs.sh"
    echo -e "  ${YELLOW}  查看状态:${NC}       bash scripts/status.sh"
    echo -e "  ${YELLOW}  停止服务:${NC}       bash scripts/stop.sh"
    echo -e "  ${YELLOW}  重启服务:${NC}       bash scripts/restart.sh"
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo ""
}

# ==================== 主流程 ====================

main() {
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  Clip Workflow 一键部署脚本${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""

    check_prerequisites
    check_env_file
    check_directories
    build_images
    start_services
    health_check
    print_access_urls

    log_info "部署流程已完成。"
}

# 执行主流程
main "$@"