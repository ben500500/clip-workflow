from pydantic_settings import BaseSettings


def _parse_origins(raw: str) -> list[str]:
    """Parse comma-separated CORS origins into a list."""
    return [o.strip() for o in raw.split(",") if o.strip()]


class Settings(BaseSettings):
    # Database
    # 必填：必须通过 .env / 环境变量注入，缺失时启动即报错
    # 示例：postgresql+asyncpg://user:password@host:5432/dbname
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    # 浏览器可直接访问的 MinIO 地址（如 localhost:9000 或通过 nginx /minio/ 代理的地址）。
    # 容器内 MINIO_ENDPOINT=minio:9000 生成的 presigned URL 浏览器无法解析，
    # 设置本字段后生成的 presigned URL 会用该地址替换 host，修复"视频不播放 / 下载拒绝连接"。
    MINIO_EXTERNAL_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "minio_admin"
    # 必填：必须通过 .env / 环境变量注入
    MINIO_SECRET_KEY: str
    MINIO_BUCKET_RAW: str = "raw-footage"
    MINIO_BUCKET_SLICED: str = "sliced"
    MINIO_BUCKET_PREVIEWS: str = "previews"
    MINIO_BUCKET_EXPORTS: str = "exports"
    MINIO_USE_SSL: bool = False

    # AutoClip
    AUTOCLIP_URL: str = "http://autoclip:8000/api/v1"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Upload
    UPLOAD_CHUNK_SIZE: int = 5 * 1024 * 1024  # 5MB
    UPLOAD_TEMP_DIR: str = "/tmp/uploads"
    UPLOAD_MAX_SIZE: int = 50 * 1024 * 1024 * 1024  # 50GB
    ALLOWED_VIDEO_EXTENSIONS: str = ".mp4,.avi,.mov,.mkv,.webm"

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8080
    DEBUG: bool = False

    # CORS（逗号分隔；默认放行所有来源，但不带凭据）
    CORS_ORIGINS: str = "*"

    # RPA / Publish
    CHROME_DEBUG_PORT: int = 9222
    RPA_REQUIRE_MANUAL_CONFIRM: bool = True
    MINIO_BUCKET_SCREENSHOTS: str = "publish-screenshots"

    # Chrome CDP 地址（容器内发布时指向 rpa_worker）
    CHROME_DEBUG_HOST: str = "localhost"

    # 视频处理引擎根目录
    ENGINES_DIR: str = "engines"

    # ── 去水印功能（v4） ──
    # 去水印输出存储桶（处理后视频）
    MINIO_BUCKET_WATERMARK: str = "watermark-output"
    # 去水印源视频存储桶（复用 raw-footage 之外的独立桶）
    MINIO_BUCKET_WATERMARK_RAW: str = "watermark-raw"
    # remove-ai-watermarks CLI 可执行文件（pip 安装后为 remove-ai-watermarks）
    WATERMARK_RAIW_CLI: str = "remove-ai-watermarks"
    # Seedance 去水印脚本文件名（位于 ENGINES_DIR 下；容器内 /app/engines/seedance_watermark_remover.py）
    WATERMARK_SEEDANCE_SCRIPT: str = "seedance_watermark_remover.py"
    # seedance_wm（remover 仓库 5 阶段流水线）执行入口脚本（位于 ENGINES_DIR 下）
    WATERMARK_SEEDANCE_WM_SCRIPT: str = "seedance_wm_runner.py"
    # remove_mask（remove-mask 仓库 ROI + cv2.inpaint TELEA）执行入口脚本（位于 ENGINES_DIR 下）
    WATERMARK_REMOVE_MASK_SCRIPT: str = "remove_mask_remover.py"
    # 单个去水印视频最大时长（秒），超长会显著耗时
    WATERMARK_MAX_DURATION: int = 3600

    # 切片分发引擎：worker（Redis Stream / Go Worker）或 celery（回退）
    SLICE_ENGINE: str = "worker"
    # Worker 回调/上传 URL 的基础地址（远程物理机部署时配置为可访问的地址）
    WORKER_CALLBACK_BASE_URL: str = "http://backend:8080"
    # Worker 任务超时（秒）
    SLICE_TASK_TIMEOUT_SECONDS: int = 7200

    # JWT
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_EXPIRE_MINUTES: int = 30  # access_token 有效期（分钟）
    # refresh_token 有效期（天），双 Token 机制
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    # RPA Cookie 加密密钥（AES-256/Fernet），未配置时回退 JWT_SECRET
    COOKIE_ENCRYPT_KEY: str = ""

    # 监控告警（三期）
    # 钉钉机器人 Webhook 地址，用于推送告警消息
    DINGTALK_WEBHOOK: str = ""
    # 告警轮询间隔（秒），Celery beat 周期
    ALERT_CHECK_INTERVAL_SECONDS: int = 300

    # 数据归档（三期性能优化）：video_metrics 超过该天数（默认 90 天）自动归档
    METRICS_ARCHIVE_DAYS: int = 90
    # MinIO 生命周期：未访问超过该天数（默认 90 天）的对象转低频存储
    MINIO_LIFECYCLE_DAYS: int = 90

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # .env 中包含 Docker Compose 使用的扩展变量（如 POSTGRES_HOST、MINIO_PORT 等），
        # 后端 Settings 未定义这些字段，忽略而非报错，避免启动失败。
        "extra": "ignore",
    }


settings = Settings()

cors_origins = _parse_origins(settings.CORS_ORIGINS)
