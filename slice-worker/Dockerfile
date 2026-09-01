# ========== 构建阶段 ==========
FROM golang:1.22-alpine AS builder

# 国内网络环境无法访问 proxy.golang.org，使用国内镜像代理
ENV GOPROXY=https://goproxy.cn,direct

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o slice-worker .

# ========== ffmpeg（NVENC 硬编 + 完整 CPU 软编回退）构建阶段 ==========
# 通用编码策略：有 GPU 的机器用 nvenc 硬编（引擎 detect_best_encoder 自动探测 +
# 运行时验证通过才用），无 GPU 的机器自动回退 libx264（CPU）。
# 本镜像同时带齐引擎依赖的 libx264/libx265（CPU 回退）与 libass/libfreetype
# （ass/subtitles/drawtext 滤镜），保证两种机器上功能都完整。
# 需 GitHub 可达（拉 ffmpeg + nv-codec-headers 源码）；首次构建约 20-40 分钟，
# 之后依赖层被 Docker 缓存。
FROM alpine:3.19 AS ffmpeg-nvenc
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories \
 && apk add --no-cache build-base yasm nasm git pkgconf \
    x264-dev x265-dev libass-dev freetype-dev fribidi-dev harfbuzz-dev fontconfig-dev
# ffmpeg 6.1.1 与运行环境当前使用的 alpine ffmpeg 版本对齐，降低行为差异风险；
# nv-codec-headers 无对应版本标签，取 master（与 6.1.1 兼容）。
RUN git clone --depth 1 https://github.com/FFmpeg/nv-codec-headers.git /nv-codec-headers \
 && make -C /nv-codec-headers install
RUN git clone --depth 1 --branch n6.1.1 https://github.com/FFmpeg/FFmpeg.git /ffmpeg
WORKDIR /ffmpeg
RUN ./configure \
      --prefix=/usr \
      --disable-doc --disable-debug --disable-htmlpages --disable-manpages \
      --enable-gpl --enable-version3 \
      --enable-libx264 --enable-libx265 \
      --enable-libass --enable-libfreetype --enable-libharfbuzz --enable-libfribidi \
      --enable-nvenc --enable-ffnvcodec \
    && make -j"$(nproc)" \
    && make install

# ========== 运行阶段 ==========
FROM alpine:3.19

# 使用国内镜像源：font-noto-cjk 包约 75MB，从官方 dl-cdn.alpinelinux.org 下载易超时卡死
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories

RUN apk add --no-cache \
    python3 \
    py3-opencv \
    bash \
    ca-certificates \
    tzdata \
    gettext \
    font-noto-cjk \
    font-droid \
    fontconfig \
    py3-fonttools

# 竖屏转横屏智能裁切：引擎 vert2horiz_crop.py 依赖 OpenCV（人脸检测/动态跟踪）
# 使用 Alpine 包管理器安装 py3-opencv，避免 pip 编译需要 gcc
# 用自编译的 ffmpeg（含 nvenc + libx264/x265 + libass/freetype）替换 alpine 自带包
COPY --from=ffmpeg-nvenc /usr/bin/ffmpeg /usr/bin/ffmpeg
COPY --from=ffmpeg-nvenc /usr/bin/ffprobe /usr/bin/ffprobe

WORKDIR /app
COPY --from=builder /build/slice-worker .
# engines/ 由打包前 scripts/sync-engines-to-worker.sh 拷入 slice-worker context
COPY --from=builder /build/engines /app/engines
COPY worker.json /app/worker.json.template

# CPU 分配比例默认值（1~100，默认 50）：直接 docker run 未设置时也能正常生成配置
ENV CPU_PERCENT=80

RUN mkdir -p /tmp/slice-worker

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD pgrep -f slice-worker || exit 1

# 使用 envsubst 替换环境变量，然后启动 Worker
CMD envsubst < /app/worker.json.template > /app/worker.json && \
    ./slice-worker --config /app/worker.json --no-tui
