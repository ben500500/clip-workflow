from pydantic_settings import BaseSettings
from pydantic import field_validator
import os
import secrets
import stat
from pathlib import Path
from typing import Optional


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
    # 多视频上传「秒差检测」（音画同步粗检）总开关：默认关闭。
    # 开启后多视频批量上传会对每个视频做音画时长差校验，发现不同步时
    # 改为「提示警告 + 标注剧集」而非拦截上传；前端上传弹窗另有独立开关，
    # 前端显式传 true 时生效，env=true 作为默认/总闸（前端未传或传 false 仍受 env 强制）。
    MULTI_UPLOAD_SECOND_DIFF_DETECT: bool = False

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

    # ── 素材变体去重 · BGM 音频差异化（配方分配层）──
    # 在音频维度叠加弱背景音乐（BGM）拉稳 RMS 指纹距离（配合 engines/slice.py 的
    # slice_segment 多输入 filter_complex 改造：bgm/bgm_volume/duck 三个入参）。
    # BGM_ENABLED：总开关。由于 slice_segment 多输入改造由 FFmpeg 侧 PR 落地，
    #   在引擎侧合并前保持 False（纯配方层结构，向后兼容）；引擎就绪后置 True 生效。
    # BGM_DIR：授权 BGM 素材目录（自产/CC0/明确商用授权源）。空串表示未配置。
    #   recipe 层只从该目录挑选 source 并做授权校验（红线），杜绝非授权曲库入库。
    # BGM_LICENSE_MANIFEST：可选授权清单 JSON（映射文件名->授权类型），
    #   未配置时按"整目录视为已授权"兜底；配置后仅放行 manifest 标记为
    #   cc0 / self_produced / commercial 的文件。
    # BGM_VOLUME：BGM 母音量（默认 0.35，弱背景、不压人声，与 FFmpeg bgm_volume 对齐）。
    # BGM_MIX_RATIO：派生变体中采用 BGM 模式的比例（0~1，默认 0.4，其余走原音频模式池）。
    BGM_ENABLED: bool = False
    BGM_DIR: str = ""
    BGM_LICENSE_MANIFEST: str = ""
    BGM_VOLUME: float = 0.35
    BGM_MIX_RATIO: float = 0.4

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
    # 卡死任务守护巡检间隔（秒）：周期把超时未收敛的 pending/中间态任务回写 failed
    WECHAT_DL_STALE_INTERVAL_SECONDS: int = 300
    # 卡死任务超时阈值（秒）：超过该时长未更新仍非终态视为 worker 崩溃遗留的孤儿任务。
    # 默认 3600：远大于 WECHAT_DL_DOWNLOAD_TIMEOUT(600) + 解析/入库耗时，避免误杀在跑任务。
    WECHAT_DL_STALE_TIMEOUT_SECONDS: int = 3600
    # ── 视频反推提示词（智令 doc/120 提交 + doc/119 轮询，异步接口）──
    # 提交接口基础地址（与 doc/107 解析同域，密钥复用 WECHAT_DL_ZHILING_KEY）。
    WECHAT_DL_ZHILING_PROMPT_BASE: str = "https://api.17zhiling.com"
    # 提交路径：POST，form-urlencoded（key/videoUrl/maxDuration），data 返回 taskId
    WECHAT_DL_ZHILING_PROMPT_SUBMIT_PATH: str = "/api/video-inference/parse-video-url-time"
    # 轮询路径：GET ?key=&taskId=（官方免费，建议 3~5s 一次）
    WECHAT_DL_ZHILING_PROMPT_STATUS_PATH: str = "/api/video-inference/task-status"
    # 外部请求超时（秒）
    WECHAT_DL_PROMPT_TIMEOUT: int = 15
    # 计时上限（秒）：官方最大 600；**按这个上限计费**（约 0.00054 元/秒），不是按视频实际长度。
    # 11-09 现网实测把默认从 600 降到 180：留空＝按 600 投＝每条 0.324 元，比 180 档（0.097 元）
    # 贵 3 倍，而且上游失败照样扣——当天 7 条「视频理解服务返回空结果」就白花了 2.268 元。
    # 资源下载页粘的多是 1~3 分钟的短剧切片，180 够用；长视频界面上显式选 300/600。
    WECHAT_DL_PROMPT_MAX_DURATION: int = 180
    # 上游「视频理解服务返回空结果」这类终态失败，自动原地补投一次（默认开）。
    # 现网事实：同一链接失败后人工再点一次多数就成（10-11 月 5 条链接都是 fail→success），
    # 但要点两下、而且每点一次再扣一次钱。这里只补**一次**（retry_count 闸门＋原子认领
    # 防两个轮询请求同时看到 FAIL 而双扣），关掉＝回到「失败就等人工重试」。
    WECHAT_DL_PROMPT_AUTO_RETRY: bool = True
    # 补投那一次先过 doc/107 把分享链接解析成视频直链（约 0.01 元/次）再反推：
    # 上游读不到短链背后的视频时，换直链是另一条取数路径；解析失败就退回原链接重投。
    # 关掉＝补投照原链接重投，不花这份解析钱（但少一条排障路径）。
    WECHAT_DL_PROMPT_RETRY_VIA_DIRECT: bool = True
    # 反推轮询「查询不通」的容忍时长（秒，默认 3600＝1 小时）：
    # 智令网关自己转发超时（code=500 转发请求失败）时不再当场判死，保持 processing 继续轮；
    # 但连续不通超过本时长就判 failed 收口，避免任务永远挂在「处理中」。与下载侧
    # WECHAT_DL_STALE_TIMEOUT_SECONDS 同一量纲、同一默认值，运维只需记一个数。
    WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS: int = 3600
    # 本地视频上传反推（智令 doc/125 签名 + S3 POST，ISSUE #363）：
    # 签名接口路径（GET ?key=&fileName=&contentType=&expiresIn=）
    WECHAT_DL_ZHILING_UPLOAD_SIGN_PATH: str = "/api/upload/signature"
    # 上传文件大小上限（MB）：前端预校验 + 后端硬校验，默认 500（S3 POST 单次上限 5GB）
    WECHAT_DL_PROMPT_UPLOAD_MAX_MB: int = 500
    # 上传到 S3 的超时下限（秒）：实际超时按 max(该值, 文件MB*6) 动态计算
    WECHAT_DL_PROMPT_UPLOAD_TIMEOUT: int = 120

    # 解析缓存（wechat_parse_records 复用）有效期（秒）。
    # 腾讯签名直链 play_url 仅 1~3 小时有效，超期复用必然 direct download http 400，
    # 因此缓存必须带时效窗口：TTL 内的成功解析记录才可复用，超期一律重新实时解析。
    # 默认 600（10 分钟），建议范围 300~900：既避开易变/限流的元宝接口重复调用，
    # 又远小于直链有效期，杜绝把过期直链交给下载器。
    WECHAT_DL_PARSE_CACHE_TTL_SECONDS: int = 600

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

    # ── 看板指标自动导入（ISSUE #366：163 data-update 采集系统 board_data.json）──
    # board_data.json 路径（163 宿主机目录以只读卷挂到 /data/board）。
    # 文件缺失/解析失败时任务 fail-soft 跳过本轮，等下一个采集周期，不重试不告警。
    BOARD_DATA_JSON_PATH: str = "/data/board/board_data.json"
    # 导入任务队列（复用 worker-fast 已订阅的 metrics 队列）
    BOARD_METRICS_QUEUE: str = "metrics"

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
    # 可选：指定推送的 workHost（字符串）；配置了则仅推送该主机
    DUPLOAD_WORK_HOST: str = ""
    # 可选：指定推送的 workHost 列表（逗号分隔或 JSON 数组）；work_host 优先，均未配置时默认拉取全部 hosts
    DUPLOAD_WORK_HOSTS: str = ""
    # 可选：appSecret（按 workHost 匹配；缺省时尝试从 hosts 接口探测，否则传空串）
    DUPLOAD_APP_SECRET: str = ""
    # dupload 批量导入必填：cpID（下载平台侧合作方 ID）
    DUPLOAD_CP_ID: str = ""

    # 飞书（Lark）表格自动爬取（ISSUE #142）
    # 方式一（公共分享）：直接填表格链接，无需凭证；
    # 方式二（Open API）：填 app_id / app_secret 走飞书开放平台，可访问受限表格。
    FEISHU_SPREADSHEET_URL: str = ""
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    # 剧目名称列 / 剧场列 在飞书表中的列名（按表头自动匹配，可空则走默认匹配）
    FEISHU_DRAMA_COL: str = "剧目名称"
    FEISHU_THEATER_COL: str = "剧场"
    # 平阅剧单本地快照目录（无 FEISHU_APP_ID/SECRET 时的回退数据源）：
    # 存放 lark-cli 拉取的 6 个 Sheet JSON（{sheet_id}.json，scripts/refresh_pingyue_roster.sh 产出）
    FEISHU_ROSTER_CACHE_DIR: str = "/app/media/pingyue"

    # ── Remotion 高光混剪增强（MVP：模板化编排的混剪包装层）──
    # 生产安全开关（参考 SPARKLE_ENABLED 思路）：默认关闭，开启后切片启用
    # remotion_mix_enabled 时才会触发 Remotion 渲染容器出增强版混剪。
    REMOTION_ENABLED: bool = False
    # Remotion 渲染容器内 render.js 入口路径（可被 env 覆盖）
    REMOTION_RENDER_SCRIPT: str = "/remotion/dist/render.js"
    # Remotion 渲染临时目录（源视频/封面/props/产物落盘）
    REMOTION_TMP_DIR: str = "/tmp/remotion"
    # 渲染产物上传到 sliced 桶的 key 前缀
    REMOTION_OUTPUT_PREFIX: str = "remotion"
    # Remotion 渲染独立队列（由 worker-remotion 独占消费）
    REMOTION_QUEUE: str = "remotion"
    # Remotion 渲染超时守护巡检间隔（秒）：周期回写 stuck 在 rendering 的超时任务为 failed
    REMOTION_STALE_INTERVAL_SECONDS: int = 300
    # Remotion 渲染任务超时阈值（秒）：超过该时长仍 rendering 视为卡死，守护任务回写 failed
    REMOTION_RENDER_TIMEOUT_SECONDS: int = 3600

    # ── 素材库（asset_library，设计方案 20261103 P0）──
    # 单批导入上限（条）：超过必须拆批，防一次粘 500 条链接把解析打爆。
    # 与 asset_service.normalize_source_list 的 limit 参数默认值保持一致。
    ASSET_IMPORT_BATCH_MAX: int = 100
    # 单批反推预算上限（元）：批量反推按**计时上限**扣费，这是最大的烧钱杠杆；
    # 预估超过该值时 budget_gate 判 need_approval，必须前端二次确认后才放行。
    ASSET_BATCH_BUDGET_CAP: float = 50.0
    # 余额安全系数：预估成本 × 该系数 仍 ≤ 账户余额 才算 ok（余额接口有抖动，留余量）
    ASSET_BALANCE_SAFETY_RATIO: float = 1.2
    # 反推计时上限默认档位（秒）：可选 60/180/300/600。
    # 默认 180 而不是现有反推链路的 600 —— 素材库是「批量」场景，
    # 600 档一条就是 0.324 元，100 条 32 元；180 档一条 0.097 元，够出钩子文案。
    ASSET_PROMPT_MAX_DURATION: int = 180
    # 每条素材生成的钩子文案候选数。11-06 用户拍板：默认只出 1 条（浓缩一句话，
    # 单审单过，也省一半模型钱）；要对照再多出几条的场合，前端按批显式传 count 覆盖。
    ASSET_HOOK_CANDIDATE_COUNT: int = 1
    # 风险词表（system_config.asset_risk_lexicon）的现读缓存时长（秒）：
    # 审核/投产/导出都要扫词，逐条查库太碎；运维改词表后最多等一个 TTL 生效，设 0 = 每次都查。
    ASSET_RISK_LEXICON_TTL_SECONDS: int = 300
    # 单条过审文案默认生产份数（N 的语义=同一文案派生 N 条**差异化**提示词，非重复投喂）
    ASSET_PRODUCE_DEFAULT_N: int = 3
    # 单条过审文案最大生产份数（硬上限，防误填 999 把号池额度一天烧光）
    ASSET_PRODUCE_MAX_N: int = 20
    # 豆包单号每日可出片数（口径来自 short-drama-hook-writer：实测 2~4 条/号/日，按 3 排产）
    # 注意：这是**额度墙**不是**时长墙**，排产天数用它算，别拿 8 小时工时反推产能。
    ASSET_DOUBAO_PER_ACCOUNT_PER_DAY: int = 3
    # 交付包（packages/）相关的 ASSET_PACKAGE_PREFIX / _KEEP_DAYS 曾在 P0 定义里挂空：
    # 全仓零引用、P2 才做交付包，届时连同桶 lifecycle Expiration 规则一起接线（B 组死配置清理）。

    # ── 素材库 · 单次请求条数上限（原直接 os.getenv，收进 Settings 供运维调）──
    # 反推/出文案都是**同步等外部接口**的，100 条串跑会把请求挂到网关超时；
    # P1 上队列后这两个上限交给队列，不由 HTTP 层扛。
    ASSET_ANALYZE_MAX_PER_CALL: int = 20
    ASSET_SUMMARY_MAX_PER_CALL: int = 10

    # ── 素材库 · 反推后台任务（11-06 三连投诉：不进任务条／首投必错／卡「反推中」）──
    # JOB_ANALYZE 的轮询节奏与总时长：智令一条反推实测 1~2 分钟出结果，30 分钟是
    # 按 600s 档 × 排队波动给的宽裕上限；到期**不判失败**——行留在 running，
    # 「收取在跑结果」按钮和单条 ⟳ 仍然收得到，只是任务台账如实记「到点没等完」。
    ASSET_ANALYZE_JOB_POLL_SECONDS: float = 10.0
    ASSET_ANALYZE_JOB_TIMEOUT_MINUTES: float = 30.0
    # 智令侧快速失败自动重试：实测「第一次总是出错」＝提交后几秒就 failed（6s 实锤），
    # 重试一次就好。只认**提交后很短时间内**的失败（真跑了一半才死的不是抖动，重试
    # 就是重复扣费）；每条素材每次任务最多自动重试一次，留审计。
    ASSET_ANALYZE_FAST_FAIL_RETRY_SECONDS: float = 120.0

    # 素材库 · 时效直链缓存（11-06 播放直链修复）：resolve 取到的 play_url 落库，
    # 这个窗口内 source-preview/resolve 免费回放；过期不作数、retake 重取自愈。
    # 6 小时与源站时效直链的有效期口径一致（界面上就写着「约 6 小时内有效」）。
    ASSET_PLAY_URL_TTL_HOURS: float = 6.0

    # ── 素材库 · 企微自动化后台「创建 AI 视频」任务板（生产通道 wework_aivideo）──
    # 权威口径：NAS《每日解压视频-操作手册-20261022.md》+ Drama/共享配置/skill/relax-video-pipeline。
    # 这条通道**不扣现金**、payload 只有七键（tag/reqID/total/date/prompt/name/picDatas）、
    # **没有时长与分辨率参数**：成片恒 10.08s / 720×1280。
    # ⚠️ 11-04 第二轮审核（D-3）时这里是两个**零读取**的假旋钮（那版 P0 是人工投板，
    # 后端从不连板），当时删掉了。11-05 批 H 做「自动投板」，随投递客户端
    # `app/services/aivideo_board.py` 一起**重新接线**——现在真的有人读了。
    # 凭据只走环境变量，仓库不写明文；现网由用户本人填进 `.env`（我们不碰那一行）。
    # `AIVIDEO_AUTH` 留空＝自动投板没启用，投递口当场白话拒绝，人工投板不受影响。
    ASSET_BOARD_BASE_URL: str = "http://mp.miwan.synology.me:8500"
    AIVIDEO_AUTH: str = ""                       # "user:pass"（客户端自己 base64）；空＝不启用
    # 三步各自的超时：建任务要等板子排队收单（权威脚本给 90s），回读是一次列表查询，
    # 下载是拉一整支 mp4。三个数分开是因为**失败成因完全不同**：90s 到＝没投出去，
    # 60s 到＝只是查不到（不许判死），180s 到＝片子取不回（单子仍算投过）。
    ASSET_BOARD_CREATE_TIMEOUT: float = 90.0
    ASSET_BOARD_READ_TIMEOUT: float = 60.0
    ASSET_BOARD_DOWNLOAD_TIMEOUT: float = 180.0
    # 投板后台任务的轮询节奏：45s 一轮、最多等 45 分钟（实测单条 45s 一轮、25 分钟出片；
    # 整批排队更久）。到期还没终态**不判失败**——留在 queued/running，由人回写或再点回收。
    ASSET_BOARD_POLL_INTERVAL: float = 45.0
    ASSET_BOARD_POLL_MAX_MINUTES: float = 45.0
    # 单次投递请求的条数上限（与反推/出文案同一类"别让一次点击干太多"的闸）。
    # 20 是拍板值：一次投 20 张＝号池当天 ≈20 条（每张 board_total=1），再大就该分批看结果。
    ASSET_DISPATCH_MAX_PER_CALL: int = 20
    # 板上 tag＝拥有者标记：不填就建成**无主任务**，按天筛不到（回收必然漏）
    ASSET_BOARD_TAG: str = "suanku"
    # 板上 total＝同一条 prompt 出几版（1..20）。与「N 份差异化提示词」是两个量，别混用。
    ASSET_BOARD_TOTAL_MAX: int = 20
    ASSET_BOARD_DEFAULT_TOTAL: int = 1
    # 号池实测 ≈120 条/日：1023 叠两份量（240）其中一批 10 分钟内 115/120 全 fail；
    # 1028 投 230 只到手 162（70%），"超出 120 的那部分基本是白投"。
    # 用户口径「产能不限」→ **不做硬限**，只在 /produce 返回里给软提示；设 0 关闭提示。
    ASSET_BOARD_DAILY_SOFT_CAP: int = 120
    # A′（2026-11-08 评审定稿）：自审自投硬闸——自己过审的候选自己投产默认拦；
    # 小团队/应急需一人包干时显式设 true（每次自审自投仍逐条写豁免审计）。
    ASSET_SELF_PRODUCE_ALLOWED: bool = False
    # P1（评审定稿⑦）：取号进界面——后端代理的取号命令（参数为数量、stdout 每行一个
    # 五位编号）。留空＝功能关闭（前端走手工粘贴）。
    ASSET_HOOK_ID_CMD: str = ""
    # 板上排日按本地时区（NAS 在 CST），后端存 UTC —— 16:00~24:00 之间会错一天，
    # 而 date 写错＝额度白烧且成片永久取不回（1021 实测 120 条）。
    ASSET_BOARD_TZ_OFFSET_HOURS: int = 8
    # 出片实测锁死的规格（用于把 duration/resolution 标成"意图"而不是"承诺"）
    ASSET_BOARD_OUTPUT_SECONDS: float = 10.08
    ASSET_BOARD_OUTPUT_RESOLUTION: str = "720x1280"

    # ── 抽帧（11-04 批 F：审核台卡片图，纯呈现层，不参与任何业务判定）──
    # 每条素材抽几张单帧（卡片左侧横排）。3 张是拍板值：1 张看不出节奏，5 张以上
    # 一行卡片放不下，一线也懒得看。
    ASSET_FRAME_THUMB_COUNT: int = 3
    # 九宫格一张图里几帧（tile=3x3）：给「这条片子整段在讲什么」用，点开才生成大图。
    # 改非平方数要同步改 asset_frame_service.GRID_COLS，不然拼图会缺一角。
    ASSET_FRAME_GRID_TILES: int = 9
    # 缩略帧宽（px）：卡片上显示宽度约 120，2x 屏留点余量；再大就是白占桶空间
    ASSET_FRAME_THUMB_WIDTH: int = 360
    # 九宫格整图宽（px）：3 格 × 360 ≈ 1080，点开看图能看清字幕但不至于拖慢页面
    ASSET_FRAME_GRID_WIDTH: int = 1080
    # 超过这个时长（秒）的原片**不抽帧**：一次抽帧＝把整个文件从桶里拉回本地再解码，
    # 十几分钟的整集片会把 worker 钉在 ffmpeg 上。素材库口径本来只要一分钟以内，
    # 这条是兜底；设 0 = 全部跳过（关掉抽帧）。
    ASSET_FRAME_MAX_SOURCE_SECONDS: float = 900.0
    # 单条 ffmpeg 命令超时（秒）：抽帧是 ffmpeg -ss 精确定位，正常 2~5s；
    # 卡住的通常是坏文件，等下去没有意义，记一笔失败就放人。
    ASSET_FRAME_TIMEOUT_SECONDS: int = 120
    # 同时在跑的抽帧协程数：导入一批 100 个文件会一次排 100 个任务，
    # 不限流就是 100 个 ffmpeg 抢同一台机的 CPU，把反推/拼接一起拖死。
    ASSET_FRAME_CONCURRENCY: int = 2
    # 手动重抽（POST /assets/frames/extract）单次条数上限。抽帧不花钱但**占 CPU**，
    # 同步等 100 条＝必挂到网关超时（和反推同一个坑），所以这里也设一道：
    # 超量要么带 async_mode=true 排后台，要么分次点。
    ASSET_FRAME_MAX_PER_CALL: int = 20

    # ── 图片素材（11-04 拍板③  11-05 批 G：图片真收进素材库，但只做生产输入）──
    # 图片**不进**反推/文案/生产/拼接四环，也不抽帧（它自己就是一张图）。
    # 上传大小上限（MB）：素材库的上传通道不分片（和 `/api/upload` 那条分片续传是两套），
    # 角色卡实测 1~3MB，20MB 已经宽到能塞下 4K 三视图；超了当场拒，别把桶塞满。
    ASSET_IMAGE_MAX_SIZE_MB: int = 20
    # 短边低于这个像素 → **只提醒不拒收**（放大到 720×1280 的画面会糊，但一线可能就想试试）。
    ASSET_IMAGE_MIN_EDGE: int = 360
    # 长边超过这个像素 → 同样只提醒（板侧会缩，白占桶空间和带宽）。
    ASSET_IMAGE_MAX_EDGE: int = 4096

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

    @field_validator("WECHAT_DL_PROMPT_MAX_DURATION")
    @classmethod
    def _prompt_max_duration_in_range(cls, v: int) -> int:
        # 官方上限 600s；下限 1s 防止 0/负数被透传成非法参数。
        if v < 1 or v > 600:
            raise ValueError("WECHAT_DL_PROMPT_MAX_DURATION 必须在 1~600 秒之间（官方最大 600）")
        return v

    @field_validator("WECHAT_DL_PROMPT_UPLOAD_MAX_MB")
    @classmethod
    def _prompt_upload_max_mb_positive(cls, v: int) -> int:
        # 0/负数会让「所有上传都超限」，必须挡在启动期。
        if v < 1:
            raise ValueError("WECHAT_DL_PROMPT_UPLOAD_MAX_MB 必须为正整数（单位 MB）")
        return v

    @field_validator("WECHAT_DL_PARSE_CACHE_TTL_SECONDS")
    @classmethod
    def _parse_cache_ttl_in_range(cls, v: int) -> int:
        # 建议窗口 300~900s：过小失去缓存意义（回到元宝限流问题），
        # 过大则可能超过直链 1~3h 有效期（死链回归）。
        if v < 300 or v > 900:
            raise ValueError(
                "WECHAT_DL_PARSE_CACHE_TTL_SECONDS 必须在 300~900 秒之间"
                "（直链有效期 1~3h，TTL 必须显著小于它）"
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
