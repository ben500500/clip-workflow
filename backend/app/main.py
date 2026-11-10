import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings, cors_origins
from app.database import init_db, close_db, async_session_factory
from app.logging_setup import install_credential_redaction
from app.api import projects, upload, autoclip, intervals, slice, preview, publications, config as config_api, publish, dashboard, auth, workers, monitor, maintenance, watermark, shortdrama, publish_material, batch_slice, channel_accounts, variants, dramas, dedupe, theaters, remotion, assets
from app.auth import get_password_hash, get_current_user
from app.models.models import User, UserRole, PlatformProfile
from app.api.config import DEFAULT_PLATFORM_PROFILES
from app.services.monitor_service import ensure_default_alert_rules

# 视频号素材导入下载（wechat_download 独立包，立项决策④：并入 + 可剥离）
from wechat_download import api as wechat_dl_api

# 局域网获取剧集导入（lan_source 独立包，并入 + 可剥离）
from lan_source import api as lan_source_api
# 推送到下载平台（dupload 独立包，并入 + 可剥离）
from dupload import api as dupload_api


logging.basicConfig(level=logging.INFO)
# 密钥脱敏（11-09）：智令 doc/119 轮询把 key 放在查询串里，httpx 的 INFO 逐请求行会把它
# 原样写进 docker logs。抬掉 httpx/httpcore 级别 + 给根 handler 挂打码过滤器，
# 起因与口径见 app/logging_setup.py。必须在 basicConfig 之后调用才有 handler 可挂。
install_credential_redaction()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 种子用户配置
# ──────────────────────────────────────────────

SEED_USERS: list[dict] = []


async def _create_seed_users():
    """在 DEBUG 环境下创建种子用户；生产环境不自动建弱口令账号。

    种子账号来自环境变量 SEED_USERS_JSON（形如
    [{"username":"admin","password":"<强口令>","role":"admin"}]），无默认弱口令。
    """
    if not settings.DEBUG:
        # 生产不自动建弱口令账号，请通过注册/邀请流程开通
        logger.info("非 DEBUG 环境，跳过种子用户创建（请通过注册/邀请流程开通）")
        return
    raw = os.getenv("SEED_USERS_JSON")
    if not raw:
        logger.warning("DEBUG 环境未提供 SEED_USERS_JSON，跳过种子用户创建")
        return
    try:
        seeds = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("SEED_USERS_JSON 解析失败，跳过种子用户创建: %s", exc)
        return
    async with async_session_factory() as session:
        for seed in seeds:
            username = seed.get("username")
            password = seed.get("password")
            if not username or not password:
                logger.warning("种子用户缺少 username/password，跳过: %s", seed)
                continue
            result = await session.execute(
                select(User).where(User.username == username)
            )
            if result.scalar_one_or_none() is not None:
                continue  # 已存在，跳过
            user = User(
                username=username,
                password_hash=get_password_hash(password),
                display_name=seed.get("display_name") or username,
                role=seed.get("role", UserRole.operator.value),
                is_active=True,
            )
            session.add(user)
            logger.info("Created seed user: %s (%s)", username, user.role)
        await session.commit()


async def _create_seed_platform_profiles():
    """在数据库初始化时预置平台去重默认配置（视频号/抖音/快手，如果尚不存在）."""
    async with async_session_factory() as session:
        for seed in DEFAULT_PLATFORM_PROFILES:
            result = await session.execute(
                select(PlatformProfile).where(PlatformProfile.name == seed["name"])
            )
            if result.scalar_one_or_none() is not None:
                continue  # 已存在，跳过
            profile = PlatformProfile(
                name=seed["name"],
                platform=seed["platform"],
                description=seed.get("description"),
                dedupe_config=seed.get("dedupe_config"),
                target_resolution=seed.get("target_resolution"),
                target_bitrate=seed.get("target_bitrate"),
                max_duration=seed.get("max_duration"),
            )
            session.add(profile)
            logger.info("Created seed platform profile: %s (%s)", seed["name"], seed["platform"])
        await session.commit()


async def _create_seed_alert_rules():
    """在数据库初始化时预置默认告警规则（幂等）."""
    await ensure_default_alert_rules()


async def _sweep_asset_jobs_at_startup():
    """素材库后台任务（D-1）的启动清扫，放在 init_db 之后。

    延迟 import：`app.api.assets` 依赖一整套 models/services，模块加载期拉它没必要，
    而且表是 `init_db()` 的 create_all 刚建的（本仓库不跑 alembic upgrade）。
    """
    from app.api.assets import sweep_interrupted_asset_jobs

    await sweep_interrupted_asset_jobs()


async def _sweep_wechat_dl_zombies_at_startup():
    """反推提示词僵尸 processing 行的启动收口（11-10）。

    判据一直在 `refresh_prompt_task` 里，但它只有「有人点开那条任务」才会跑到——
    upload 型又没有别的入口会刷它，现网就是这么攒了 6 条永远「生成中」的行、最后人工
    进库判的（docs 8-11/8-12）。这里补的是**触发**。0 元、不发外部请求，且**有意只收
    没有上游任务号的行**：有 pid 的行会连带触发自动补投，启动时无人值守花钱不能接受。

    fail-soft：收口失败只记日志，绝不能把整个服务启动带崩。
    """
    from wechat_download.prompt_service import sweep_zombie_prompt_tasks

    try:
        async with async_session_factory() as db:
            swept = await sweep_zombie_prompt_tasks(db)
        if swept:
            logger.warning("启动收口反推僵尸任务 %s 条", swept)
    except Exception:  # noqa: BLE001 - 清扫不阻断启动
        logger.exception("反推僵尸任务启动收口失败（不影响其他功能）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    logger.info("Starting up...")
    await init_db()
    logger.info("Database initialized.")
    await _create_seed_users()
    logger.info("Seed users initialized.")
    await _create_seed_platform_profiles()
    logger.info("Seed platform profiles initialized.")
    await _create_seed_alert_rules()
    logger.info("Seed alert rules initialized.")
    await _sweep_asset_jobs_at_startup()
    logger.info("Asset background jobs swept.")
    await _sweep_wechat_dl_zombies_at_startup()
    logger.info("Wechat-dl zombie prompt tasks swept.")
    yield
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database connections closed.")


app = FastAPI(
    title="Clip Workflow API",
    description="Short drama clip workflow backend service",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
if "*" in cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.websocket("/ws/wechat-dl/{task_id}")
async def websocket_wechat_dl(websocket: WebSocket, task_id: str):
    """视频号导入下载进度实时回传（WebSocket，跨进程 Redis pub/sub）。

    订阅 Redis 频道 `wechat_dl:progress`，按 task_id 过滤后转发给前端。
    celery worker 在下载流水线各阶段通过 _publish_progress 发布进度。
    """
    import asyncio
    import json
    import redis.asyncio as aioredis

    from app.config import settings as _s
    await websocket.accept()
    try:
        r = aioredis.from_url(_s.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe("wechat_dl:progress")
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    try:
                        data = json.loads(msg["data"])
                    except Exception:
                        continue
                    if data.get("task_id") == task_id:
                        await websocket.send_text(json.dumps(data))
                # 前端断开/心跳中断时退出
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except (asyncio.TimeoutError, Exception):
                    pass
        finally:
            await pubsub.unsubscribe("wechat_dl:progress")
            await r.aclose()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.websocket("/ws/lan-source/{task_id}")
async def websocket_lan_source(websocket: WebSocket, task_id: str):
    """局域网剧集导入进度实时回传（WebSocket，跨进程 Redis pub/sub）。

    订阅 Redis 频道 `lan_source:progress`，按 task_id 过滤后转发给前端。
    """
    import asyncio
    import json
    import redis.asyncio as aioredis

    from app.config import settings as _s
    await websocket.accept()
    try:
        r = aioredis.from_url(_s.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe("lan_source:progress")
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    try:
                        data = json.loads(msg["data"])
                    except Exception:
                        continue
                    if data.get("task_id") == task_id:
                        await websocket.send_text(json.dumps(data))
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except (asyncio.TimeoutError, Exception):
                    pass
        finally:
            await pubsub.unsubscribe("lan_source:progress")
            await r.aclose()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# Mount all API routers
# 业务路由统一加用户鉴权依赖；auth(login/refresh) 与 Worker/心跳回调（走各自 Token）不在此列
_protected_routers = [
    projects, upload, autoclip, intervals, slice, preview, publications,
    config_api, publish, dashboard, workers, monitor, maintenance,
    watermark, shortdrama, publish_material, batch_slice,
    wechat_dl_api, channel_accounts, variants, dramas, lan_source_api,
    dupload_api,
    dedupe,
    theaters,
    remotion,
    assets,
]
for _r in _protected_routers:
    app.include_router(_r.router, prefix="/api", dependencies=[Depends(get_current_user)])

# auth 自带 /api/auth 前缀，保持开放（login/refresh）
app.include_router(auth.router)

# 登录二维码图片代理：同源免鉴权返回 PNG（qr_key 为随机 UUID 能力令牌，
# 等同原 MinIO presigned 安全模型；前端 <img> 无法携带 JWT，故不走全局鉴权依赖）
from app.api import publish_login_qr as _publish_login_qr
app.include_router(_publish_login_qr.img_router, prefix="/api")

# 供 Go slice-worker 回调的开放路由（X-Worker-Token 鉴权）
app.include_router(slice.worker_router, prefix="/api")
# 供 Go slice-worker 心跳上报的开放路由
app.include_router(workers.internal_router, prefix="/api")


@app.get("/api/health")
async def health_check():
    """基础健康检查（轻量，供 Docker healthcheck 使用）."""
    return {"status": "ok", "service": "clip-workflow-backend"}


@app.get("/api/health/detailed")
async def health_check_detailed():
    """增强版健康检查（数据库/Redis/MinIO/磁盘，三期监控告警）."""
    from app.services.monitor_service import check_health
    return await check_health()