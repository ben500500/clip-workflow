#!/usr/bin/env bash
# =============================================================================
# Clip Workflow - 生成 Ubuntu 节点部署包
#
# 在具备 Go 1.22+ 的环境中运行，产出可直接拷贝到 Ubuntu 机器离线部署的 tar.gz：
#   clip-slice-worker-ubuntu-<arch>-<version>.tar.gz
#
# 部署包内含：
#   - slice-worker-linux-<arch>   预编译二进制（无需目标机安装 Go）
#   - engines/                    引擎脚本（slice.py 等）
#   - deploy_ubuntu.sh            一键部署脚本（systemd 管理）
#   - clip-slice-worker.service.in systemd 服务模板
#   - README.md                   部署说明
#
# 用法：
#   ./build_package.sh                     # 当前架构
#   ./build_package.sh --arch amd64        # 指定架构 (amd64|arm64)
#   ./build_package.sh --all               # 同时构建 amd64 + arm64
#   ./build_package.sh --version v3.0.0    # 指定版本号（默认取最近 git tag 或日期）
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$WORKER_DIR/.." && pwd)"

ARCHS=()
VERSION=""
ACTION="build"

while [[ $# -gt 0 ]]; do
    case $1 in
        --arch) ARCHS+=("$2"); shift 2 ;;
        --all) ARCHS=(amd64 arm64); shift ;;
        --version) VERSION="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $0 [--arch amd64|arm64] [--all] [--version vX.Y.Z]"
            exit 0 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

log() { echo -e "\033[32m[INFO]\033[0m $1"; }
die()  { echo -e "\033[31m[ERROR]\033[0m $1" >&2; exit 1; }

command -v go >/dev/null 2>&1 || die "缺少 go (1.22+)，请先安装"

if [[ ${#ARCHS[@]} -eq 0 ]]; then
    case "$(uname -m)" in
        x86_64|amd64) ARCHS=(amd64) ;;
        aarch64|arm64) ARCHS=(arm64) ;;
        *) die "无法识别架构，请用 --arch 指定" ;;
    esac
fi

if [[ -z "$VERSION" ]]; then
    VERSION="$(cd "$ROOT_DIR" && git describe --tags --abbrev=0 2>/dev/null || echo "dev")"
fi

echo "=== 生成 Ubuntu 部署包 ==="
echo "  架构: ${ARCHS[*]} | 版本: $VERSION"

for ARCH in "${ARCHS[@]}"; do
    STAGE="$SCRIPT_DIR/release/${VERSION}/${ARCH}"
    rm -rf "$STAGE"
    mkdir -p "$STAGE/engines"

    log "编译 slice-worker ($ARCH)..."
    ( cd "$WORKER_DIR" && CGO_ENABLED=0 GOOS=linux GOARCH="$ARCH" \
        go build -ldflags="-s -w" -o "$STAGE/slice-worker-linux-${ARCH}" . )

    log "复制引擎脚本..."
    cp -r "$ROOT_DIR/engines"/. "$STAGE/engines/"

    log "复制部署脚本..."
    cp "$SCRIPT_DIR/deploy_ubuntu.sh" "$STAGE/"
    cp "$SCRIPT_DIR/clip-slice-worker.service.in" "$STAGE/"
    cp "$SCRIPT_DIR/README.md" "$STAGE/"

    # 生成最终 tar.gz
    PKG_NAME="clip-slice-worker-ubuntu-${ARCH}-${VERSION}.tar.gz"
    PKG_PATH="$SCRIPT_DIR/release/$PKG_NAME"
    ( cd "$STAGE" && tar czf "$PKG_PATH" . )
    log "已生成: $PKG_PATH"
    echo "  拷贝到 Ubuntu 机器后:"
    echo "    tar xzf $PKG_NAME && cd <解压目录>"
    echo "    sudo ./deploy_ubuntu.sh --server-ip <服务器IP> --redis-password <密码>"
    echo ""
done

echo "=== 完成 ==="
echo "部署包目录: $SCRIPT_DIR/release/"
ls -lh "$SCRIPT_DIR"/release/*.tar.gz 2>/dev/null || true
