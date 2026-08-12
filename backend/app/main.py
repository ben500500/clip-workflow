import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings, cors_origins
from app.database import init_db, close_db, async_session_factory
from app.api import projects, upload, autoclip, intervals, slice, preview, publications, config as config_api, publish, dashboard, auth, workers, monitor, maintenance, watermark, shortdrama, publish_material, batch_slice
from app.auth import get_password_hash, get_current_user
from app.models.models import User, UserRole, PlatformProfile
from app.api.config import DEFAULT_PLATFORM_PROFILES
from app.services.monitor_service import ensure_default_alert_rules

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections for progress updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, task_id: str, websocket: WebSocket):
        if task_id in self.active_connections:
            self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]

    async def send_progress(self, task_id: str, progress: float, message: str = ""):
        if task_id not in self.active_connections:
            return
        data = json.dumps({"progress": progress, "message": message})
        for ws in self.active_connections[task_id]:
            try:
                await ws.send_text(data)
            except Exception:
                pass


manager = ConnectionManager()


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


@app.websocket("/ws/progress/{task_id}")
async def websocket_progress(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time task progress updates."""
    await manager.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(task_id, websocket)
    except Exception:
        manager.disconnect(task_id, websocket)


# Mount all API routers
# 业务路由统一加用户鉴权依赖；auth(login/refresh) 与 Worker/心跳回调（走各自 Token）不在此列
_protected_routers = [
    projects, upload, autoclip, intervals, slice, preview, publications,
    config_api, publish, dashboard, workers, monitor, maintenance,
    watermark, shortdrama, publish_material, batch_slice,
]
for _r in _protected_routers:
    app.include_router(_r.router, prefix="/api", dependencies=[Depends(get_current_user)])

# auth 自带 /api/auth 前缀，保持开放（login/refresh）
app.include_router(auth.router)

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