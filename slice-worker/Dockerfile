# ========== 构建阶段 ==========
FROM golang:1.22-alpine AS builder

# 国内网络环境无法访问 proxy.golang.org，使用国内镜像代理
ENV GOPROXY=https://goproxy.cn,direct

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o slice-worker .

# ========== 运行阶段 ==========
FROM alpine:3.19

# 使用国内镜像源：font-noto-cjk 包约 75MB，从官方 dl-cdn.alpinelinux.org 下载易超时卡死
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories

RUN apk add --no-cache \
    ffmpeg \
    python3 \
    py3-opencv \
    bash \
    ca-certificates \
    tzdata \
    gettext \
    font-noto-cjk \
    font-droid \
    fontconfig

# 竖屏转横屏智能裁切：引擎 vert2horiz_crop.py 依赖 OpenCV（人脸检测/动态跟踪）
# 使用 Alpine 包管理器安装 py3-opencv，避免 pip 编译需要 gcc

WORKDIR /app
COPY --from=builder /build/slice-worker .
COPY worker.json /app/worker.json.template

# CPU 分配比例默认值（1~100，默认 50）：直接 docker run 未设置时也能正常生成配置
ENV CPU_PERCENT=50

RUN mkdir -p /tmp/slice-worker

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD pgrep -f slice-worker || exit 1

# 使用 envsubst 替换环境变量，然后启动 Worker
CMD envsubst < /app/worker.json.template > /app/worker.json && \
    ./slice-worker --config /app/worker.json --no-tui
