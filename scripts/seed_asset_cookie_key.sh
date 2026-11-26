#!/usr/bin/env bash
# 把现有主 backend 的 refresh-cookie 密钥安全种入独立部署单元共用的命名卷。
# 只复制密钥文件，不输出其内容，不启动/停止任何容器。
set -euo pipefail

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-clip-workflow}"
VOLUME="${COMPOSE_PROJECT_NAME}_backend_cookie_data"
SOURCE_CONTAINER="${SOURCE_CONTAINER:-clip-backend}"
# 163 的 Docker daemon 与 SSH 会话 /tmp 不共命名空间；临时目录必须位于
# Docker 可见的宿主路径（仓库目录在 /home/cc12703 下），否则 docker cp 会假失败。
TMP_DIR="$(mktemp -d "$PWD/.asset-cookie-seed.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

if ! docker inspect "${SOURCE_CONTAINER}" >/dev/null 2>&1; then
  printf '找不到主 backend 容器 %s；请先确认容器名。\n' "${SOURCE_CONTAINER}" >&2
  exit 1
fi

# 显式 COOKIE_ENCRYPT_KEY 由 env_file 原样注入两个后端，不需要卷内文件。
if docker exec "${SOURCE_CONTAINER}" sh -c 'test -n "${COOKIE_ENCRYPT_KEY}"'; then
  printf '主 backend 已显式配置 COOKIE_ENCRYPT_KEY；无需种入文件，启用 overlay 后须保持该环境变量一致。\n'
  exit 0
fi

if ! docker exec "${SOURCE_CONTAINER}" test -s /app/data/cookie_key; then
  printf '主 backend 没有可复用的 /app/data/cookie_key；停止操作，避免生成新密钥使现有会话失效。\n' >&2
  exit 1
fi

docker cp "${SOURCE_CONTAINER}:/app/data/cookie_key" "${TMP_DIR}/cookie_key" >/dev/null
docker volume create "${VOLUME}" >/dev/null

# 已有同内容文件＝幂等；已有不同文件＝拒绝覆盖，绝不静默轮换密钥。
docker run --rm \
  -v "${VOLUME}:/seed" \
  -v "${TMP_DIR}:/source:ro" \
  alpine:3.20 sh -eu -c '
    if [ -e /seed/cookie_key ]; then
      cmp -s /seed/cookie_key /source/cookie_key || {
        printf "共享卷已有不同 cookie_key；停止操作。请人工核对，不要覆盖。\n" >&2
        exit 1
      }
      chmod 600 /seed/cookie_key
    else
      umask 077
      cp /source/cookie_key /seed/cookie_key
    fi
  '
printf 'Cookie 密钥已种入共享卷 %s（未回显内容）；下一步可执行 compose config 校验。\n' "${VOLUME}"
