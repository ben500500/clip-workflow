"""素材库独立 ASGI 入口（运行/发布轨道与主 backend 解耦）。

边界：只注册素材库业务路由、登录路由和健康检查。素材审计与切片产物查询仍由
同源 nginx 转发到主 backend；数据库 schema 继续由主 backend 的 init_db 负责，
避免两个进程同时 create_all/补列。素材后台任务的启动清扫在本入口独占执行。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assets, auth
from app.auth import get_current_user
from app.config import cors_origins, settings
from app.database import close_db
from app.logging_setup import install_credential_redaction

# 显式加载用户/会话等共享模型；独立入口不能依赖 main.py 的 import 副作用。
import app.models.models  # noqa: F401,E402

logging.basicConfig(level=logging.INFO)
install_credential_redaction()
logger = logging.getLogger(__name__)


def _asset_session_router() -> APIRouter:
    """只暴露素材前端需要的会话端点；用户/角色管理仍归主 backend。"""
    router = APIRouter()
    for path, endpoint, methods, response_model in (
        ("/auth/login", auth.login, ["POST"], auth.LoginResponse),
        ("/auth/refresh", auth.refresh_token, ["POST"], auth.RefreshResponse),
        ("/auth/logout", auth.logout, ["POST"], auth.LogoutResponse),
        ("/auth/me", auth.get_me, ["GET"], auth.UserResponse),
    ):
        router.add_api_route(path, endpoint, methods=methods, response_model=response_model)
    return router


def create_asset_app(*, run_job_sweep: bool | None = None) -> FastAPI:
    """创建独立素材 API；测试可关闭启动清扫以保持数据库夹具隔离。"""
    sweep_enabled = settings.ASSET_JOB_SWEEP_ENABLED if run_job_sweep is None else run_job_sweep

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if sweep_enabled:
            await assets.sweep_interrupted_asset_jobs()
            logger.info("Asset background jobs swept by asset-api.")
        try:
            yield
        finally:
            await close_db()

    application = FastAPI(
        title="Clip Asset Library API",
        description="Short-drama asset library, independently deployed API",
        version="1.0.0",
        lifespan=lifespan,
    )
    if "*" in cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.include_router(
        assets.router,
        prefix="/api",
        dependencies=[Depends(get_current_user)],
    )
    application.include_router(_asset_session_router(), prefix="/api")

    @application.get("/api/health")
    async def health():
        return {"status": "ok", "service": "clip-asset-backend"}

    return application


app = create_asset_app()
