#!/usr/bin/env bash
#
# gen_selfsigned_cert.sh — 生成内网 HTTPS 自签证书（2026-11-09）
#
# 为什么自签：163 是内网 IP、没有公网域名，Let's Encrypt 不适用；而浏览器的
# 桌面通知（Notification API）只在「安全上下文」（HTTPS / localhost）可用。
# 自签证书 + 首次访问点「高级 → 继续前往」信任一次，即可满足安全上下文。
#
# 用法（在服务器上跑）：
#   bash scripts/gen_selfsigned_cert.sh [IP或域名...]
# 默认：192.168.1.163 + localhost + 127.0.0.1
#
# 产物：certs/clip.crt、certs/clip.key（.gitignore 忽略，不入库）
# 生效：docker compose up -d --force-recreate nginx
set -euo pipefail

cd "$(dirname "$0")/.."
OUT_DIR="${CERT_DIR:-./certs}"
DAYS="${CERT_DAYS:-3650}"

IPS=("$@")
if [ ${#IPS[@]} -eq 0 ]; then
  IPS=(192.168.1.163 localhost 127.0.0.1)
fi

# 组装 SAN：IP 类进 IP:，域名类进 DNS:
SAN=""
for h in "${IPS[@]}"; do
  if [[ "$h" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="${SAN}IP:${h},"
  else
    SAN="${SAN}DNS:${h},"
  fi
done
SAN="${SAN%,}"

mkdir -p "$OUT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$OUT_DIR/clip.key" \
  -out "$OUT_DIR/clip.crt" \
  -days "$DAYS" \
  -subj "/C=CN/O=clip-workflow/CN=${IPS[0]}" \
  -addext "subjectAltName=${SAN}" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"

chmod 644 "$OUT_DIR/clip.crt"
chmod 600 "$OUT_DIR/clip.key"
echo "已生成：$OUT_DIR/clip.crt / clip.key（SAN=${SAN}，${DAYS} 天）"
openssl x509 -in "$OUT_DIR/clip.crt" -noout -subject -dates -ext subjectAltName
