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
#
# 基座选型（关键）：必须用 Debian(glibc) 而非 alpine(musl)——宿主机 NVIDIA 驱动库
# （libnvidia-encode.so.1 等）是 glibc 产物，musl 进程 dlopen 即失败
# （「Cannot load libnvidia-encode.so.1」，2026-09 生产已踩坑）。glibc 基座下
# ffmpeg 才能加载透传进容器的 NVIDIA 驱动库，NVENC 才真正可用。
# 需 Gitee 可达（拉 ffmpeg 源码）；首次构建约 15-30 分钟，之后依赖层被 Docker 缓存。
FROM debian:bookworm-slim AS ffmpeg-nvenc
# 国内镜像源加速（bookworm 源文件为 /etc/apt/sources.list.d/debian.sources）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential yasm nasm git pkg-config curl ca-certificates \
    libx264-dev libx265-dev libass-dev libfreetype-dev libharfbuzz-dev libfribidi-dev \
 && rm -rf /var/lib/apt/lists/*
# nv-codec-headers（n12.1.14.0，匹配 ffmpeg 6.1.1）：打进仓库，构建时免网络依赖。
# 含 5 个 ffnvcodec 头文件 + ffnvcodec.pc（ffmpeg configure 用 pkg-config 校验版本）。
COPY nv-codec-headers /nv-codec-headers
RUN mkdir -p /usr/include/ffnvcodec /usr/lib/pkgconfig \
 && cp /nv-codec-headers/include/ffnvcodec/*.h /usr/include/ffnvcodec/ \
 && cp /nv-codec-headers/ffnvcodec.pc /usr/lib/pkgconfig/ffnvcodec.pc
# ffmpeg 6.1.1 与 40 生产既有版本对齐，降低行为差异风险。
# 用 Gitee 镜像 clone（国内稳），规避 GitHub 大仓库 clone/tar 下载断流。
RUN git -c http.version=HTTP/1.1 clone --depth 1 --branch n6.1.1 \
      https://gitee.com/mirrors/FFmpeg.git /ffmpeg
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
# Debian(glibc) 运行时：NVENC 依赖的宿主机 NVIDIA 驱动库可正常 dlopen。
# apt 自带 ffmpeg 保留只为提供共享库（libass/libxcb/harfbuzz/fribidi 等，
# 自编译 ffmpeg 对这些是动态链接）；随后用自编译二进制覆盖 /usr/bin/ffmpeg|ffprobe。
FROM debian:bookworm-slim

# 国内镜像源加速（bookworm 源文件为 /etc/apt/sources.list.d/debian.sources）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# OpenCV 不用 apt 的 python3-opencv：bookworm 只有 4.6.0，跑不动引擎内置的 yunet.onnx
# （DNN 层报 eltwise 形状错，且 apt 版缺 cv2.data.haarcascades），竖转横人脸检测会静默退化
# （2026-09-02 在 163 的 glibc 兼容性验证发现）。改装 pip 预编译 wheel（opencv-python-headless，
# 免编译），版本对齐 alpine 期验证过的 4.8.1。
# fonts-noto-cjk 提供中文字幕渲染字体。
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    python3 \
    python3-pip \
    bash \
    ca-certificates \
    tzdata \
    gettext \
    fontconfig \
    fonts-noto-cjk \
    fonts-droid-fallback \
    python3-fonttools \
    procps \
 && rm -rf /var/lib/apt/lists/*
# pip 轮子：清华源（国内稳），Debian12 的 PEP668 需 --break-system-packages（容器单用途可接受）
RUN python3 -m pip install --no-cache-dir --break-system-packages \
      -i https://pypi.tuna.tsinghua.edu.cn/simple \
      "opencv-python-headless==4.8.1.78"

# 用自编译的 ffmpeg（含 nvenc + libx264/x265 + libass/freetype）替换发行版自带二进制
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
