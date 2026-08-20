from pydantic_settings import BaseSettings
from pydantic import field_validator
import os
import secrets
import stat
from pathlib import Path


DEFAULT_JWT_PLACEHOLDERS = {
    "your-secret-key-change-in-production",
    "change-this-to-a-random-jwt-secret",
}


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
    MINIO_ACCESS_KEY: str                       # 原 "minio_admin" 默认值删除，改为必填（配合 docker-compose 必填校验）
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

    # 解耦模式（AI 选点 × 切片解耦）周期任务间隔（秒）
    BATCH_DISPATCH_INTERVAL_SECONDS: int = 5   # 切片投递守护轮询已选点池间隔
    BATCH_AGGREGATE_INTERVAL_SECONDS: int = 10 # 批次状态聚合间隔

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

    # Playwright 统一管理器空闲回收超时（秒）：引用归零且无长驻句柄后，
    # 超过该时长无新使用才 stop 进程级驱动（<=0 表示禁用空闲回收，保持常驻）
    PLAYWRIGHT_IDLE_TIMEOUT: int = 300

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

    # ── Seedance 官方 API 直连出片（与豆包 RPA 并行、独立通道） ──
    # 总开关（默认关闭）。开启后短片制作「提示词生成历史」出现「Seedance 生成」按钮，
    # 走火山方舟官方 API 直连出片（无需浏览器 RPA / 扫码）。
    # 也可在 system_config 的 shortdrama_seedance_config.enabled 覆盖。
    SEEDANCE_ENABLED: bool = False
    # 火山方舟 API Key（https://console.volcengine.com/ark）
    SEEDANCE_API_KEY: str = ""
    # 模型名或推理接入点 ID（ep-xxx）。Seedance 1.0 仅支持 5s/10s
    SEEDANCE_MODEL: str = "seedance-1-0-pro-250528"
    # API Base（默认即可）
    SEEDANCE_API_BASE: str = "https://ark.cn-beijing.volces.com/api/v3"
    # 出片分辨率：480p / 720p / 1080p
    SEEDANCE_RESOLUTION: str = "1080p"
    # 是否加水印（建议 true，避免被平台判搬运）
    SEEDANCE_WATERMARK: bool = True
    # 生成超时（秒）
    SEEDANCE_TIMEOUT: int = 600
    # 时长超 10s 的处理策略：truncate(截成10s) / block(拒绝并提示)
    SEEDANCE_LONG_DURATION_POLICY: str = "truncate"
    # 每日配额（0=不限）
    SEEDANCE_DAILY_QUOTA: int = 0

    # 切片分发引擎：worker（Redis Stream / Go Worker）、local（单机同步执行）或 celery（回退）
    SLICE_ENGINE: str = "worker"
    # Worker 回调/上传 URL 的基础地址（远程物理机部署时配置为可访问的地址）
    WORKER_CALLBACK_BASE_URL: str = "http://backend:8080"
    # Worker 任务超时（秒）
    SLICE_TASK_TIMEOUT_SECONDS: int = 7200

    # ── 素材变体去重（variant_service）──
    # 常规配方 structural.reorder 默认值（运营开关，默认开）。
    # reorder 依赖拆段：仅当 segment=True 且片段数≥3 时生效（对时域序列重排以拉开 L4 指纹）。
    # 置 False 可关闭默认重排（segment 仍维持随机 [False,True] 不变）。
    STRUCTURAL_REORDER_DEFAULT: bool = True

    # JWT
    JWT_SECRET: str  # 必填无默认；启动时 field_validator 拒绝占位符/默认值
    JWT_EXPIRE_MINUTES: int = 30  # access_token 有效期（分钟）
    # refresh_token 有效期（天），双 Token 机制
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    # RPA Cookie 加密密钥（AES-256/Fernet），与 JWT_SECRET 必须不同；留空由 _ensure_cookie_key 生成并落盘
    COOKIE_ENCRYPT_KEY: str = ""

    # 发布平台登录态巡检间隔（秒），Celery beat 周期（默认每 6 小时）
    COOKIE_CHECK_INTERVAL_SECONDS: int = 21600
    # 豆包改写确认等待上限（秒）：改写稿等待用户确认的最长阻塞时长，避免长期占住 worker 槽位
    DOUBAO_REWRITE_WAIT_SECONDS: int = 30

    # 监控告警（三期）
    # 钉钉机器人 Webhook 地址，用于推送告警消息
    DINGTALK_WEBHOOK: str = ""
    # 告警轮询间隔（秒），Celery beat 周期
    ALERT_CHECK_INTERVAL_SECONDS: int = 300

    # 数据归档（三期性能优化）：video_metrics 超过该天数（默认 90 天）自动归档
    METRICS_ARCHIVE_DAYS: int = 90
    # MinIO 生命周期：未访问超过该天数（默认 90 天）的对象转低频存储
    MINIO_LIFECYCLE_DAYS: int = 90

    # ── 视频号素材导入下载（wechat_download，立项决策④：独立配置命名空间）──
    # 元宝解析接口基础地址（非公开接口，可通过环境变量覆盖；P0 主链路）
    WECHAT_DL_YUANBAO_API_BASE: str = "https://yuanbao.tencent.com"
    # 元宝解析接口 Key / 鉴权 Token（如接口需独立 Key，生产必须配置）
    WECHAT_DL_YUANBAO_KEY: str = ""
    # 预览层兜底：视频号预览页前缀
    WECHAT_DL_PREVIEW_BASE: str = "https://channels.weixin.qq.com"
    # 拉流层：finder 拉流基础地址
    WECHAT_DL_FINDER_BASE: str = "https://finder.video.qq.com"
    # 下载超时（秒，拉流整体超时）
    WECHAT_DL_DOWNLOAD_TIMEOUT: int = 600
    # 拉流并发闸门 key（复用主系统 redis_stream 并发控制）
    WECHAT_DL_QUEUE: str = "wechat_dl"
    # 默认入库归属项目名（未指定 project_id 时，按需创建/复用）
    WECHAT_DL_DEFAULT_PROJECT: str = "视频号导入"
    # 视频号解析 provider 有序列表（兜底链）：英文逗号分隔，值映射到内置 adapter
    # 或自定义 HTTP 服务商（需配套 WECHAT_DL_<NAME>_BASE/_KEY/_PATH 等 env）。
    # 未设置时回退 "yuanbao,preview"（向后兼容）。
    WECHAT_DL_PROVIDERS: str = "yuanbao,preview"

    # ── 局域网获取剧集（lan_source，立项设计：独立配置命名空间）──
    # 总开关（默认关闭）。开启后在剧目详情页出现「局域网获取剧集」面板，
    # 从局域网 dupload 源拉取剧集直链、下载入库并导入切片流程。
    LAN_SOURCE_ENABLED: bool = False
    # dupload cdn 源基础地址（返回 /videos/{drama}/cdn 直链的服务），默认局域网 8765
    LAN_SOURCE_BASE_URL: str = "http://192.168.1.163:8765"
    # 剧目清单来源（可选）：IAA 小程序管理平台基础地址（提供 /api/bg/sync/tasks 剧名清单）。
    # 未配置时允许从 API 手工提交剧名清单。
    LAN_SOURCE_MANAGE_BASE: str = ""
    # 剧集清单接口是否带路径前缀（有的源在 {base}/videos/{drama}/cdn）
    LAN_SOURCE_API_PREFIX: str = ""
    # 下载超时（秒，单集拉流整体超时）
    LAN_SOURCE_DOWNLOAD_TIMEOUT: int = 900
    # 导入任务队列（并入 worker-fast 的 metrics,default,celery,wechat_dl 同 worker）
    LAN_SOURCE_QUEUE: str = "lan_source"
    # 默认入库归属项目名（未指定 project_id 时，按需创建/复用）
    LAN_SOURCE_DEFAULT_PROJECT: str = "局域网导入"
    # 每集 HTTP 下载并发数（默认 2，避免打爆源服务器）
    LAN_SOURCE_CONCURRENCY: int = 2

    # ── 推送到下载平台（dupload，对接 21:8800 dramaupload / dupload 独立服务）──
    # 总开关（默认开启）。开启后剧目详情页出现「推送到下载平台」区块，
    # 一键调用 POST /api/dupload/tasks（action=only_download）把剧目素材链接推给下载平台。
    DUPLOAD_ENABLED: bool = True
    # dupload 服务基础地址（默认局域网 21:8800）
    DUPLOAD_BASE_URL: str = "http://192.168.1.21:8800"
    # 批量导入接口路径
    DUPLOAD_IMPORT_PATH: str = "/api/dupload/tasks"
    # 动作：only_download(仅下载)/upload_miniapp(上传小程序)
    DUPLOAD_ACTION: str = "only_download"
    # 剧目模型里素材链接(shareUrl)的字段名（默认 material_link）
    DUPLOAD_SHARE_URL_FIELD: str = "material_link"
    # 单次请求超时（秒）
    DUPLOAD_REQUEST_TIMEOUT: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # .env 中包含 Docker Compose 使用的扩展变量（如 POSTGRES_HOST、MINIO_PORT 等），
        # 后端 Settings 未定义这些字段，忽略而非报错，避免启动失败。
        "extra": "ignore",
    }

    @field_validator("JWT_SECRET")
    @classmethod
    def _no_default_secret(cls, v: str) -> str:
        if not v or v.strip() in DEFAULT_JWT_PLACEHOLDERS:
            raise ValueError(
                "生产环境必须在 .env 设置 JWT_SECRET（随机强密钥），禁止使用默认/占位值"
            )
        return v

    @field_validator("COOKIE_ENCRYPT_KEY")
    @classmethod
    def _cookie_key_differs(cls, v: str, info) -> str:
        # 若配置了 COOKIE_ENCRYPT_KEY，则不能与 JWT_SECRET 相同
        jwt_secret = info.data.get("JWT_SECRET")
        if v and jwt_secret and v == jwt_secret:
            raise ValueError("COOKIE_ENCRYPT_KEY 不得与 JWT_SECRET 相同")
        return v


def _ensure_cookie_key() -> str:
    """COOKIE_ENCRYPT_KEY 未配置时生成独立随机密钥并持久化落盘，避免回退到 JWT_SECRET。"""
    if settings.COOKIE_ENCRYPT_KEY:
        return settings.COOKIE_ENCRYPT_KEY
    p = Path(os.getenv("DATA_DIR", "/app/data")) / "cookie_key"
    try:
        if p.exists():
            return p.read_text().strip()
        k = secrets.token_urlsafe(32)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(k)
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
        return k
    except OSError:
        # 落盘失败时退化为随机密钥（进程内），避免回退到 JWT_SECRET
        return secrets.token_urlsafe(32)


settings = Settings()

# 固化独立 Cookie 密钥（启动时计算一次）
COOKIE_ENCRYPT_KEY = _ensure_cookie_key()
settings.COOKIE_ENCRYPT_KEY = COOKIE_ENCRYPT_KEY

cors_origins = _parse_origins(settings.CORS_ORIGINS)
