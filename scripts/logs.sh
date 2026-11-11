#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 日志查看脚本
# 支持查看单个服务或所有服务的日志
# 用法: bash scripts/logs.sh [service_name] [options]
# 示例:
#   bash scripts/logs.sh          # 查看所有服务日志
#   bash scripts/logs.sh backend  # 查看 backend 日志
#   bash scripts/logs.sh nginx -f # 实时跟踪 nginx 日志
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

# 可用的服务列表
# 2026-11-11 运维席 P2：原来这里硬编码 14 个名字，compose 后来加的
# worker-selection / worker-wechat-dl / worker-remotion / rpa_worker / slice-worker /
# alembic-migrate 一个都不在表里——`logs.sh worker-wechat-dl` 直接报「无效的服务名」，
# 而微信下载恰恰是最需要看日志的那个（它不在部署重建名单里时就是靠这里发现的）。
# 改成从 compose 现算；compose 不可用（缺 .env、语法错）时退回一份保底名单，
# 至少 backend/frontend 这些老名字还能看——宁可列表旧一点，别让脚本在排障当场罢工。
COMPOSE_SERVICES="$(cd "$PROJECT_DIR" && $COMPOSE_CMD config --services 2>/dev/null | sort || true)"
if [ -n "$COMPOSE_SERVICES" ]; then
    # shellcheck disable=SC2207
    SERVICES=($COMPOSE_SERVICES)
    SERVICES_SRC="docker compose config --services"
else
    SERVICES=("postgres" "redis" "minio" "minio_init" "autoclip" "autoclip_worker" "backend" "beat" \
              "frontend" "nginx" "worker-video" "worker-variant" "worker-publish" "worker-fast" \
              "worker-selection" "worker-wechat-dl")
    SERVICES_SRC="内置保底名单（compose 读不到，服务列表可能已过期）"
    echo -e "${YELLOW}[WARN]${NC} 读不到 compose 服务清单，退回保底名单" >&2
fi

show_usage() {
    echo "用法: bash scripts/logs.sh [service_name] [options]"
    echo ""
    echo "可用服务（来源：${SERVICES_SRC}）:"
    for s in "${SERVICES[@]}"; do
        echo "  - $s"
    done
    echo ""
    echo "选项:"
    echo "  -f, --follow        实时跟踪日志"
    echo "  -n, --tail <N>      显示最后 N 行（默认: 100）"
    echo "  -t, --timestamps    显示时间戳"
    echo ""
    echo "示例:"
    echo "  bash scripts/logs.sh              # 所有服务日志"
    echo "  bash scripts/logs.sh backend      # backend 日志"
    echo "  bash scripts/logs.sh nginx -f     # 实时跟踪 nginx 日志"
    echo "  bash scripts/logs.sh worker-video -n 50 # 显示视频 worker 最后 50 行"
}

# 如果没有参数，显示所有日志
if [ $# -eq 0 ]; then
    echo -e "${CYAN}[INFO]${NC} 显示所有服务日志（最近 100 行）..."
    echo -e "${YELLOW}提示: 按 Ctrl+C 退出${NC}"
    echo ""
    $COMPOSE_CMD logs --tail=100 -f
    exit 0
fi

# 检查第一个参数是否是服务名
service_name="$1"
is_valid=false

for s in "${SERVICES[@]}"; do
    if [ "$service_name" = "$s" ]; then
        is_valid=true
        break
    fi
done

if [ "$is_valid" = false ]; then
    # 如果第一个参数不是有效服务名，可能是 help 或其他选项
    case "$service_name" in
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo -e "${RED}[ERROR]${NC} 无效的服务名: $service_name"
            show_usage
            exit 1
            ;;
    esac
fi

# 移除第一个参数（服务名），剩余参数传给 docker compose logs
shift

echo -e "${CYAN}[INFO]${NC} 显示 ${service_name} 的日志..."
echo -e "${YELLOW}提示: 按 Ctrl+C 退出${NC}"
echo ""

$COMPOSE_CMD logs --tail=100 "$@" "$service_name"