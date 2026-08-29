# ============================================================
# Remotion 混剪增强 Worker（P2 T7）
# 职责：独占消费 remotion 队列的 Celery worker。一个容器同时承载：
#   - Python + Celery（编排：读 SliceTask、调 render.js、上传 MinIO、回写状态）
#   - Node + Chromium + Remotion（渲染：dist/render.js 逐帧渲染增强版混剪）
# 镜像基础：node:20-slim + chromium（P1 决策，非 playwright 镜像）
# ============================================================

# ---------- Stage 1: Remotion 前端构建 ----------
FROM node:20-slim AS remotion-builder
WORKDIR /remotion
# 仅复制锁文件与清单，利用 Docker 层缓存
COPY remotion/package.json remotion/package-lock.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
# 复制源码并编译 dist/render.js
COPY remotion/tsconfig.json remotion/remotion.config.ts ./
COPY remotion/scripts ./scripts
COPY remotion/src ./src
RUN npm run build

# ---------- Stage 2: Python 依赖构建 ----------
FROM python:3.11-slim AS python-builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---------- Stage 3: 运行时 ----------
FROM python:3.11-slim
ENV DEBIAN_FRONTEND=noninteractive

# 运行系统依赖：chromium（Remotion 渲染内核）+ ffmpeg + 中文字体 + curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-noto-cjk \
    fontconfig \
    ffmpeg \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 20（用于 Remotion 渲染）
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# 指定 Remotion 使用系统 chromium，避免运行时内置下载
ENV REMOTION_CHROMIUM_EXECUTABLE=/usr/bin/chromium

# 安装 Python 依赖（来自 Stage 2）
COPY --from=python-builder /root/.local /usr/local

# 复制 backend 代码（Celery 任务运行目录：app.celery.tasks.celery_app）
WORKDIR /app
COPY backend/requirements.txt ./
COPY backend/ ./

# 复制 Remotion 构建产物与运行依赖（来自 Stage 1）
COPY --from=remotion-builder /remotion /remotion
WORKDIR /app

# 暴露 healthcheck 端点端口（python http.server）
EXPOSE 8081

# 轻量健康检查 HTTP 端点：GET /health → 200 {"status":"ok"}
COPY docker/remotion-worker/healthcheck.py /app/healthcheck.py
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30s \
    CMD ["python", "/app/healthcheck.py"]

# 默认以 Celery worker 启动（compose 中通过 command 覆盖为消费 remotion 队列）
CMD ["celery", "-A", "app.celery.tasks.celery_app", "worker", "-Q", "remotion", "--loglevel=info", "--concurrency=1"]
