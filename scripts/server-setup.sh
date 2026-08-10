#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 阿里云服务器一键部署脚本
# 用法: curl -fsSL <repo-raw-url>/scripts/server-setup.sh | bash
#   或: bash server-setup.sh [--skip-rpa] [--branch main]
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ==================== 默认参数 ====================
INSTALL_DIR="/opt/clip-workflow"
GIT_REPO="https://github.com/ben500500/clip-workflow.git"
GIT_BRANCH="main"
SKIP_RPA=true  # 默认跳过 RPA（视频号发布）

# ==================== 参数解析 ====================
while [[ $# -gt 0 ]]; do
    case $1 in
        --dir=*) INSTALL_DIR="${1#*=}"; shift ;;
        --repo=*) GIT_REPO="${1#*=}"; shift ;;
        --branch=*) GIT_BRANCH="${1#*=}"; shift ;;
        --skip-rpa) SKIP_RPA=true; shift ;;
        --with-rpa) SKIP_RPA=false; shift ;;
        -h|--help)
            echo "用法: bash server-setup.sh [选项]"
            echo "  --dir=PATH       安装目录 (默认: /opt/clip-workflow)"
            echo "  --repo=URL       Git 仓库地址"
            echo "  --branch=NAME    Git 分支 (默认: main)"
            echo "  --skip-rpa       跳过 RPA 模块（默认）"
            echo "  --with-rpa       包含 RPA 模块（视频号自动发布）"
            exit 0
            ;;
        *) shift ;;
    esac
done

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${CYAN}[STEP]${NC} $1"; }

echo ""
echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  Clip Workflow - 阿里云服务器一键部署${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""
log_info "安装目录: $INSTALL_DIR"
log_info "Git 仓库: $GIT_REPO"
log_info "Git 分支: $GIT_BRANCH"
log_info "RPA 模块: $(if $SKIP_RPA; then echo '跳过'; else echo '包含'; fi)"
echo ""

# ==================== Step 1: 系统检测 ====================
log_step "检测系统环境..."

OS_TYPE=$(uname -s)
if [ "$OS_TYPE" != "Linux" ]; then
    log_error "此脚本仅支持 Linux 系统"
    exit 1
fi

# 检测发行版
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    DISTRO_VERSION=$VERSION_ID
    log_info "操作系统: $PRETTY_NAME"
else
    log_warn "无法检测操作系统版本"
    DISTRO="unknown"
fi

# 检查内存
TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
if [ "$TOTAL_MEM" -lt 4 ]; then
    log_warn "内存 ${TOTAL_MEM}GB 低于推荐配置 8GB，可能影响性能"
else
    log_info "内存: ${TOTAL_MEM}GB ✓"
fi

# 检查磁盘
DISK_FREE=$(df -BG / | awk 'NR==2{gsub("G",""); print $4}')
if [ "$DISK_FREE" -lt 20 ]; then
    log_warn "可用磁盘 ${DISK_FREE}GB 低于推荐配置 50GB"
else
    log_info "可用磁盘: ${DISK_FREE}GB ✓"
fi

# 检查 CPU
CPU_CORES=$(nproc)
log_info "CPU 核心: $CPU_CORES"

echo ""

# ==================== Step 2: 安装 Docker ====================
log_step "检查 Docker..."

if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    log_info "Docker 已安装: $DOCKER_VERSION ✓"
else
    log_warn "Docker 未安装，正在安装..."
    
    case "$DISTRO" in
        ubuntu|debian)
            apt-get update -qq
            apt-get install -y -qq ca-certificates curl gnupg lsb-release
            
            install -m 0755 -d /etc/apt/keyrings
            curl -fsSL "https://download.docker.com/linux/${DISTRO}/gpg" | \
                gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
            chmod a+r /etc/apt/keyrings/docker.gpg
            
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${DISTRO} $(lsb_release -cs) stable" | \
                tee /etc/apt/sources.list.d/docker.list > /dev/null
            
            apt-get update -qq
            apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        centos|rhel|alinux|aliyunlinux)
            yum install -y -q yum-utils
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            yum install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        *)
            log_warn "未知发行版 $DISTRO，尝试通用安装方式..."
            curl -fsSL https://get.docker.com | bash
            ;;
    esac
    
    systemctl enable docker
    systemctl start docker
    log_info "Docker 安装完成 ✓"
fi

# 检查 Docker Compose
if docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || docker compose version | grep -oP '\d+\.\d+\.\d+')
    log_info "Docker Compose: $COMPOSE_VERSION ✓"
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    log_info "docker-compose: $(docker-compose --version) ✓"
    COMPOSE_CMD="docker-compose"
else
    log_warn "Docker Compose 未安装，正在安装..."
    COMPOSE_LATEST=$(curl -fsSL "https://api.github.com/repos/docker/compose/releases/latest" | grep '"tag_name"' | grep -oP '\d+\.\d+\.\d+')
    curl -fsSL "https://github.com/docker/compose/releases/download/v${COMPOSE_LATEST}/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    COMPOSE_CMD="docker-compose"
    log_info "Docker Compose 安装完成 ✓"
fi

# 验证 Docker 运行
if ! docker info &> /dev/null; then
    log_error "Docker 守护进程未运行"
    exit 1
fi

echo ""

# ==================== Step 3: 克隆代码 ====================
log_step "获取项目代码..."

if [ -d "$INSTALL_DIR/.git" ]; then
    log_info "项目目录已存在，拉取最新代码..."
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout "$GIT_BRANCH"
    git pull origin "$GIT_BRANCH"
else
    if [ -d "$INSTALL_DIR" ]; then
        log_warn "$INSTALL_DIR 已存在但非 Git 仓库，备份后重新克隆..."
        mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
    fi
    git clone --branch "$GIT_BRANCH" --depth 1 "$GIT_REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

log_info "代码就绪: $(git log --oneline -1)"
echo ""

# ==================== Step 4: 配置环境变量 ====================
log_step "配置环境变量..."

if [ ! -f ".env" ]; then
    cp .env.example .env
    
    # 生成随机密钥
    SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | base64 | tr -d '\n/+=' | head -c 64)
    DB_PASS=$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -d '\n/+=' | head -c 32)
    REDIS_PASS=$(openssl rand -hex 12 2>/dev/null || head -c 24 /dev/urandom | base64 | tr -d '\n/+=' | head -c 24)
    MINIO_PASS=$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -d '\n/+=' | head -c 32)
    
    # 替换默认值
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASS}|" .env
    sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=${REDIS_PASS}|" .env
    sed -i "s|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=${MINIO_PASS}|" .env
    sed -i "s|^DEBUG=.*|DEBUG=false|" .env
    
    log_info ".env 已生成（含随机密钥）"
else
    log_info ".env 已存在，跳过生成"
fi

echo ""

# ==================== Step 5: 构建和启动 ====================
log_step "构建 Docker 镜像（这可能需要几分钟）..."

if $SKIP_RPA; then
    # 不构建 RPA 镜像
    $COMPOSE_CMD build --parallel postgres redis minio minio_init autoclip backend worker-video worker-publish worker-fast beat frontend nginx
else
    $COMPOSE_CMD build --parallel
fi

log_info "镜像构建完成 ✓"
echo ""

log_step "启动服务..."

if $SKIP_RPA; then
    $COMPOSE_CMD up -d postgres redis minio minio_init autoclip backend worker-video worker-publish worker-fast beat frontend nginx
else
    $COMPOSE_CMD up -d
fi

log_info "服务启动完成 ✓"
echo ""

# ==================== Step 6: 等待服务就绪 ====================
log_step "等待服务就绪..."

MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost/health > /dev/null 2>&1; then
        log_info "Nginx 已就绪 (${WAITED}s)"
        break
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    printf "."
done
echo ""

if [ $WAITED -ge $MAX_WAIT ]; then
    log_warn "服务启动超时，请检查日志: $COMPOSE_CMD logs"
fi

# ==================== Step 7: 验证 ====================
echo ""
echo -e "${CYAN}==================== 服务状态 ====================${NC}"
$COMPOSE_CMD ps
echo -e "${CYAN}=================================================${NC}"
echo ""

# 检查各服务健康状态
check_service() {
    local name=$1
    local url=$2
    if curl -sf "$url" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name"
    else
        echo -e "  ${RED}✗${NC} $name (未就绪)"
    fi
}

log_step "服务健康检查:"
check_service "前端 (Nginx)" "http://localhost/"
check_service "Backend API" "http://localhost/api/health"
check_service "AutoClip API" "http://localhost/autoclip/health"
check_service "MinIO" "http://localhost:9000/minio/health/live"

echo ""

# ==================== Step 8: 防火墙配置 ====================
log_step "检查防火墙..."

# 阿里云通常使用安全组，但也要检查本机防火墙
if command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-service=http > /dev/null 2>&1 || true
    firewall-cmd --permanent --add-service=https > /dev/null 2>&1 || true
    firewall-cmd --reload > /dev/null 2>&1 || true
    log_info "firewalld 已放行 HTTP/HTTPS"
elif command -v ufw &> /dev/null; then
    ufw allow 80/tcp > /dev/null 2>&1 || true
    ufw allow 443/tcp > /dev/null 2>&1 || true
    log_info "ufw 已放行 HTTP/HTTPS"
else
    log_info "未检测到本机防火墙（阿里云通过安全组控制）"
fi

echo ""

# ==================== 完成 ====================
SERVER_IP=$(curl -sf http://100.100.100.200/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Clip Workflow 部署完成！${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "  访问地址:"
echo -e "  ${CYAN}前端应用:${NC}      http://${SERVER_IP}"
echo -e "  ${CYAN}API 文档:${NC}      http://${SERVER_IP}/api/docs"
echo -e "  ${CYAN}MinIO 控制台:${NC}  http://${SERVER_IP}:9001"
echo ""
echo -e "  ${YELLOW}重要提醒:${NC}"
echo -e "  1. 确保阿里云安全组已放行端口: 80, 9001"
echo -e "  2. 如需 HTTPS，请配置 SSL 证书后修改 nginx.conf"
echo -e "  3. 如需启用 RPA（视频号发布），运行:"
echo -e "     cd $INSTALL_DIR && $COMPOSE_CMD up -d rpa_worker"
echo ""
echo -e "  管理命令:"
echo -e "  ${YELLOW}查看日志:${NC}  cd $INSTALL_DIR && $COMPOSE_CMD logs -f"
echo -e "  ${YELLOW}重启服务:${NC}  cd $INSTALL_DIR && $COMPOSE_CMD restart"
echo -e "  ${YELLOW}停止服务:${NC}  cd $INSTALL_DIR && $COMPOSE_CMD down"
echo -e "  ${YELLOW}更新代码:${NC}  cd $INSTALL_DIR && git pull && $COMPOSE_CMD up -d --build"
echo ""
echo -e "${GREEN}================================================${NC}"
