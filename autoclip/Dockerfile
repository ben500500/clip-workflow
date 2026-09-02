# =============================================================================
# AutoClip Service Dockerfile
# AI 驱动的智能视频剪辑服务
# 基于 python:3.11-slim
# =============================================================================

FROM python:3.11-slim

# ==================== 构建参数 ====================
ARG APP_USER=autoclip
ARG APP_GROUP=autoclip
ARG APP_HOME=/app
ARG WORKER_CONCURRENCY=4
# 可选：是否安装 faster-whisper 的 CUDA 后端（ctranslate2 的 CUDA 版）。
# 默认 false（镜像更小，纯 CPU）。构建 GPU 版时传 --build-arg ENABLE_CUDA=true，
# 并在部署机安装 NVIDIA 驱动 + nvidia-container-toolkit，配合 docker-compose
# 的 WHISPER_DEVICE=cuda / WHISPER_COMPUTE_TYPE=float16 使用。
# 踩坑记录：历史版本误写为 "nvidia-ctranslate2"——该包在 PyPI 上根本不存在
# （404 实锤），任何 ENABLE_CUDA=true 的构建都必然失败，即当年「装不上」的根因。
# 另注意：ctranslate2==4.4.0 需 cuDNN 8，而 torch CUDA 轮子（cu121）固定依赖
# cuDNN 9（nvidia-cudnn-cu12==9.x），同名 pip 包无法并存两个版本——因此
# ENABLE_CUDA 与 ENABLE_FUNASR 的 torch CUDA 版不能同时开启。
ARG ENABLE_CUDA=false
# 可选：是否安装本地 FunASR 重依赖（torch/torchaudio/funasr/modelscope，见
# requirements-funasr.txt）。默认 false，避免拉取 ~190MB 的 torch CPU 轮子导致
# 构建超时（CNB runner 超过 10min 无输出会强制关闭任务）。需要
# AUTOCLIP_ASR_METHOD=funasr_local 时传 --build-arg ENABLE_FUNASR=true。
ARG ENABLE_FUNASR=false
# torch 轮子来源：默认 CPU 轮子源（163 等无 GPU 部署）。有 GPU 部署（如 40，
# 驱动 535.261.03 最高支持 CUDA 12.2）在 .env 配
#   TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121
# 即安装 torch 2.5.1+cu121（含 sm_75），FunASR 运行时自动检测 cuda:0。
# 注意：cu126+ 索引已无 cp311（Python 3.11）轮子；cu124 最高 torch 2.6.0。
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

# ==================== 环境变量 ====================
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    APP_HOME=${APP_HOME} \
    SERVICE_MODE=${SERVICE_MODE:-api} \
    UMASK=0000

# ==================== 系统依赖 ====================
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        # 运行时依赖
        ffmpeg \
        curl \
        ca-certificates \
        tzdata \
        # 编译依赖
        gcc \
        libffi-dev \
        libpq-dev \
    ; \
    # 清理 apt 缓存以减小镜像体积
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*; \
    # 设置时区
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime; \
    echo "Asia/Shanghai" > /etc/timezone

# ==================== 创建用户 ====================
RUN set -eux; \
    groupadd -r ${APP_GROUP} --gid 1000; \
    useradd -r -g ${APP_GROUP} --uid 1000 -d ${APP_HOME} -s /sbin/nologin ${APP_USER}; \
    mkdir -p ${APP_HOME}/media ${APP_HOME}/logs; \
    chown -R ${APP_USER}:${APP_GROUP} ${APP_HOME}

# ==================== 安装 Python 依赖 ====================
WORKDIR ${APP_HOME}

COPY requirements.txt requirements-funasr.txt ./
RUN set -eux; \
    pip install --no-cache-dir -r requirements.txt; \
    # 可选 CUDA 后端：faster-whisper 的 GPU 推理依赖 ctranslate2 的 CUDA 版。
    # 驱动 535 兼容链：CUDA ≤12.2 + cuDNN 8 → ctranslate2 只能用 4.4.0
    if [ "$ENABLE_CUDA" = "true" ]; then \
        pip install --no-cache-dir "ctranslate2==4.4.0" "nvidia-cudnn-cu12==8.9.*" "nvidia-cublas-cu12==12.2.*"; \
    fi; \
    # 可选本地 FunASR 重依赖（torch/funasr/modelscope 等，默认不装避免构建超时）。
    # torch/torchaudio 先按 TORCH_INDEX_URL 装好对应 CUDA/CPU 版本，再装
    # requirements-funasr.txt 时 pip 检测 torch 已满足即跳过（不会重装覆盖）。
    if [ "$ENABLE_FUNASR" = "true" ]; then \
        pip install --no-cache-dir torch torchaudio --index-url "$TORCH_INDEX_URL"; \
        pip install --no-cache-dir -r requirements-funasr.txt; \
    fi; \
    # 验证关键包安装成功
    python -c "import fastapi; import uvicorn; import celery; import redis; import httpx; import sqlalchemy; print('All dependencies verified')"

# ==================== 复制应用代码 ====================
COPY . .

# ==================== 权限设置 ====================
# media 卷被 backend / worker 等多个容器挂载共享。autoclip 以 uid 1000 写入，
# 若目录/文件保持默认 0755/0644，backend(appuser) 删除时会 PermissionDenied 残留孤儿。
# 这里把 media 置为 0777，配合运行时 umask 0000，使新写入的文件世界可写，
# 任何挂载该卷的容器都能清理自己的产物。
RUN set -eux; \
    chown -R ${APP_USER}:${APP_GROUP} ${APP_HOME}; \
    chmod -R 755 ${APP_HOME}; \
    chmod -R 0777 ${APP_HOME}/media

# ==================== 健康检查 ====================
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ==================== 切换用户 ====================
USER ${APP_USER}

# ==================== 暴露端口 ====================
EXPOSE 8000

# ==================== 启动命令 ====================
# 根据 SERVICE_MODE 环境变量决定启动方式:
#   api    - 启动 FastAPI 服务
#   worker - 启动 Celery Worker
# 启动前先 umask 0000，使运行时新建的 media 子目录/文件世界可写（避免 backend 删不动残留孤儿）；
# 并对已有 media 目录递归修正权限（修复镜像升级前已存在的 0755 旧目录）。
ENTRYPOINT ["sh", "-c", "umask ${UMASK:-0000}; find /app/media -type d -exec chmod 0777 {} + 2>/dev/null; exec python -m app.main \"$@\"", "autoclip-entrypoint"]
CMD ["--mode", "api"]