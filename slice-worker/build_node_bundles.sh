#!/usr/bin/env bash
# =============================================================================
# build_node_bundles.sh — 生成 Linux / Windows 分布式切片节点分发包
#
# 产物（dist/worker-node-bundles/）：
#   slice-worker-node-linux-amd64.tar.gz / linux-arm64.tar.gz
#   slice-worker-node-windows-amd64.zip  / windows-arm64.zip
#
# 每个包含：节点主程序、engines/ 切片引擎（纯标准库）、启动脚本、README。
# 目标机前置：Python 3.10+ 与 ffmpeg（libx264+aac；字幕任务需 libass），详见包内 README。
#
# 用法：./build_node_bundles.sh
# 注意：Windows 目标需要拉 golang.org/x/text 依赖，国内网络请导出
#       GOPROXY=https://goproxy.cn,direct 再跑。
# =============================================================================
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
OUT="$ROOT/dist/worker-node-bundles"
export CGO_ENABLED=0

rm -rf "$OUT"; mkdir -p "$OUT"
for target in "linux amd64" "linux arm64" "windows amd64" "windows arm64"; do
  set -- $target
  GOOS=$1 GOARCH=$2 go build -o "$OUT/build_$1_$2" "$DIR"
done

for arch in amd64 arm64; do
  # Linux 包
  d="linux-$arch"; mkdir -p "$OUT/$d"
  mv "$OUT/build_linux_$arch" "$OUT/$d/slice-worker"
  cp -R "$ROOT/engines" "$OUT/$d/engines"
  cp "$ROOT/dist/start-worker.sh" "$ROOT/dist/README-node.md" "$OUT/$d/"
  chmod +x "$OUT/$d/slice-worker" "$OUT/$d/start-worker.sh"
  (cd "$OUT" && tar czf "slice-worker-node-$d.tar.gz" "$d" && rm -rf "$d")
  # Windows 包（zip，Windows 自带解压）
  d="windows-$arch"; mkdir -p "$OUT/$d"
  mv "$OUT/build_windows_$arch.exe" "$OUT/$d/slice-worker.exe"
  cp -R "$ROOT/engines" "$OUT/$d/engines"
  cp "$ROOT/dist/start-worker.bat" "$ROOT/dist/README-node.md" "$OUT/$d/"
  (cd "$OUT" && python3 -c "
import zipfile, os, sys
d = '$d'
with zipfile.ZipFile('slice-worker-node-$d.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(d):
        for f in files:
            z.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), '.'))
" && rm -rf "$d")
done
rm -f "$OUT"/build_*
echo "完成。产物在 $OUT/："
ls -la "$OUT" | grep -E "tar.gz|zip"
