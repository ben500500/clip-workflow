#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clip Workflow - 首个管理员账号初始化脚本
# -----------------------------------------------------------------------------
# 为什么需要它：
#   后端仅在 DEBUG=true 且设置 SEED_USERS_JSON 时，启动才会自动创建种子用户
#   （见 backend/app/main.py 的 _create_seed_users）。本项目生产模式默认
#   DEBUG=false，且 POST /api/v1/auth/register 要求调用者本身已是管理员，
#   因此「第一个 admin」无法用注册接口创建，只能走本脚本的临时通道。
#
# 本脚本自动完成：
#   1) 临时把 DEBUG 改为 true，并写入 SEED_USERS_JSON（含管理员账号）
#   2) 重启 backend，让其启动时创建该管理员
#   3) 轮询 /api/v1/auth/login 验证登录成功
#   4) 无论成功与否，都还原 DEBUG 原值并删除临时 SEED_USERS_JSON（不留存明文密码）
#
# 用法：
#   bash scripts/init_admin.sh                                    # 交互输入账号密码
#   INIT_ADMIN_USER=admin INIT_ADMIN_PASS='强口令' bash scripts/init_admin.sh   # 非交互
# =============================================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE=".env"
[ -f "$ENV_FILE" ] || { log_error ".env 不存在，请先完成项目初始化（bash scripts/init.sh）与配置"; exit 1; }

# ---- 确定 compose 命令 ----
if docker compose version &> /dev/null; then COMPOSE_CMD="docker compose";
elif command -v docker-compose &> /dev/null; then COMPOSE_CMD="docker-compose";
else log_error "未找到 docker compose，无法重启 backend"; exit 1; fi

# ---- 确定管理员凭据 ----
ADMIN_USER="${INIT_ADMIN_USER:-}"
ADMIN_PASS="${INIT_ADMIN_PASS:-}"
if [ -z "$ADMIN_USER" ]; then
  read -r -p "请输入管理员用户名 [admin]: " ADMIN_USER
  ADMIN_USER="${ADMIN_USER:-admin}"
fi
if [ -z "$ADMIN_PASS" ]; then
  read -r -s -p "请输入管理员密码: " ADMIN_PASS; echo
  [ -z "$ADMIN_PASS" ] && { log_error "密码不能为空"; exit 1; }
fi

# 转义密码中的反斜杠与双引号，避免破坏 JSON
ADMIN_PASS_ESC=$(printf '%s' "$ADMIN_PASS" | sed 's/\\/\\\\/g; s/"/\\"/g')

# ---- 检查 backend 容器是否在运行 ----
if ! docker ps --format '{{.Names}}' | grep -q "clip-backend"; then
  log_error "backend 容器未运行。请先部署/启动服务（bash deploy.sh 或 $COMPOSE_CMD up -d backend）"
  exit 1
fi

# ---- 备份原 DEBUG 值，并临时改写 .env ----
ORIG_DEBUG=$(grep -E '^DEBUG=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)
ORIG_DEBUG="${ORIG_DEBUG:-false}"

# 移除任何已存在的 SEED_USERS_JSON 行，避免重复累积
grep -vE '^SEED_USERS_JSON=' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
# 写入临时种子（外层单引号包裹 JSON，python-dotenv 会正确解析内部双引号）
printf "SEED_USERS_JSON='[{\"username\":\"%s\",\"password\":\"%s\",\"role\":\"admin\"}]'\n" "$ADMIN_USER" "$ADMIN_PASS_ESC" >> "$ENV_FILE"
# 临时开启 DEBUG
sed -i "s/^DEBUG=.*/DEBUG=true/" "$ENV_FILE"

log_info "已临时开启 DEBUG 并写入种子账号，正在重启 backend..."
$COMPOSE_CMD restart backend >/dev/null 2>&1 || docker restart clip-backend >/dev/null 2>&1

# ---- 轮询验证：最多 90s，尝试登录 /api/v1/auth/login ----
log_info "等待 backend 启动并创建管理员（最多 90 秒）..."
OK=0
for _ in $(seq 1 30); do
  sleep 3
  TOKEN=$(curl -sf -X POST "http://localhost/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS_ESC\"}" 2>/dev/null \
    | grep -o '"access_token":"[^"]*"' | head -1 | cut -d'"' -f4) || true
  if [ -n "$TOKEN" ]; then OK=1; break; fi
done

# ---- 无论成功与否，先还原 .env，避免 DEBUG 长期开启、避免明文密码留存 ----
log_info "还原 .env（关闭 DEBUG、移除临时种子配置）..."
grep -vE '^SEED_USERS_JSON=' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
if grep -q '^DEBUG=' "$ENV_FILE"; then
  sed -i "s/^DEBUG=.*/DEBUG=${ORIG_DEBUG}/" "$ENV_FILE"
else
  printf 'DEBUG=%s\n' "$ORIG_DEBUG" >> "$ENV_FILE"
fi
$COMPOSE_CMD restart backend >/dev/null 2>&1 || docker restart clip-backend >/dev/null 2>&1

if [ "$OK" -eq 1 ]; then
  log_info "管理员账号 '$ADMIN_USER' 初始化成功！可前往前端（http://<服务器IP>）使用该账号登录。"
  log_info "登录后进入「用户管理」可用管理员身份创建 operator 等其他成员。"
else
  log_error "登录验证失败（90s 内未返回 token）。可能 backend 尚未就绪或密码不匹配。"
  log_error "DEBUG 已还原为 $ORIG_DEBUG，临时种子配置已清除，可手动排查："
  log_error "  docker logs clip-backend 2>&1 | grep -iE 'seed|种子|SEED_USERS'"
  exit 1
fi
