# ========== 构建阶段 ==========
FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o slice-worker .

# ========== 运行阶段 ==========
FROM alpine:3.19

RUN apk add --no-cache \
    ffmpeg \
    bash \
    ca-certificates \
    tzdata \
    gettext

WORKDIR /app
COPY --from=builder /build/slice-worker .
COPY worker.json /app/worker.json.template

RUN mkdir -p /tmp/slice-worker

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD pgrep -f slice-worker || exit 1

# 使用 envsubst 替换环境变量，然后启动 Worker
CMD envsubst < /app/worker.json.template > /app/worker.json && \
    ./slice-worker --config /app/worker.json --no-tui