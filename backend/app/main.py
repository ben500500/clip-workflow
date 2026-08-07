import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings, cors_origins
from app.database import init_db, close_db, async_session_factory
from app.api import projects, upload, autoclip, intervals, slice, preview, publications, config as config_api, publish, dashboard, auth, workers, monitor, maintenance, watermark
from app.auth import get_password_hash
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

SEED_USERS: list[dict] = [
    {"username": "admin",     "password": "admin123",     "display_name": "管理员",     "role": UserRole.admin.value},
    {"username": "operator",  "password": "operator123",  "display_name": "运营专员",   "role": UserRole.operator.value},
    {"username": "publisher", "password": "publisher123", "display_name": "发布专员",   "role": UserRole.publisher.value},
    {"username": "material",  "password": "material123",  "display_name": "素材专员",   "role": UserRole.material.value},
]


async def _create_seed_users():
    """在数据库初始化时创建默认种子用户（如果尚不存在）."""
    async with async_session_factory() as session:
        for seed in SEED_USERS:
            result = await session.execute(
                select(User).where(User.username == seed["username"])
            )
            if result.scalar_one_or_none() is not None:
                continue  # 已存在，跳过
            user = User(
                username=seed["username"],
                password_hash=get_password_hash(seed["password"]),
                display_name=seed["display_name"],
                role=seed["role"],
                is_active=True,
            )
            session.add(user)
            logger.info("Created seed user: %s (%s)", seed["username"], seed["role"])
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
app.include_router(auth.router)  # 自带 /api/auth 前缀
app.include_router(projects.router, prefix="/api", tags=["Projects"])
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(autoclip.router, prefix="/api", tags=["AutoClip"])
app.include_router(intervals.router, prefix="/api", tags=["Intervals"])
app.include_router(slice.router, prefix="/api", tags=["Slice"])
app.include_router(preview.router, prefix="/api", tags=["Preview"])
app.include_router(publications.router, prefix="/api", tags=["Publications"])
app.include_router(config_api.router, prefix="/api", tags=["Config"])
app.include_router(publish.router, prefix="/api", tags=["Publish"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(workers.router, prefix="/api", tags=["Workers"])
app.include_router(monitor.router, prefix="/api", tags=["Monitor"])
app.include_router(maintenance.router, prefix="/api", tags=["Maintenance"])
app.include_router(watermark.router, prefix="/api", tags=["Watermark"])


@app.get("/api/health")
async def health_check():
    """基础健康检查（轻量，供 Docker healthcheck 使用）."""
    return {"status": "ok", "service": "clip-workflow-backend"}


@app.get("/api/health/detailed")
async def health_check_detailed():
    """增强版健康检查（数据库/Redis/MinIO/磁盘，三期监控告警）."""
    from app.services.monitor_service import check_health
    return await check_health()