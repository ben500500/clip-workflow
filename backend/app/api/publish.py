"""
Publish API routes - manage publish tasks and profiles for video distribution.

Phase 1 上帝类拆分：原「上帝类」publish.py（~1666 行 / 6+ 子域）已按子域拆分为多个
独立 router 模块，本文件作为**门面（facade）**统一聚合，URL 保持不变：

- publish_tasks.py        → `/publish/tasks*`        发布任务 CRUD/批量/截图/确认/死信重发
- publish_profiles.py     → `/publish/profiles*`     发布配置 CRUD
- publish_video_accounts.py → `/publish/video-accounts*`  账号库 CRUD/批量导入
- publish_mini_programs.py → `/publish/mini-programs*`    小程序链接库 CRUD
- publish_batches.py      → `/publish/batches*`      多运营者发布批次
- publish_audit.py        → `/publish/multi-operator/*` `/publish/audit*`  审计/矩阵/运营者
- publish_login_qr.py     → `/publish/login*`        登录态自服务扫码

main.py 通过 `include_router(publish.router, prefix="/api", ...)` 挂载，
此处仅需保留 `router` 属性并把所有子域 router include 进来，即可保证既有 URL 与鉴权不变。
"""
from fastapi import APIRouter

from app.api.publish_tasks import router as _tasks_router
from app.api.publish_profiles import router as _profiles_router
from app.api.publish_video_accounts import router as _video_accounts_router
from app.api.publish_mini_programs import router as _mini_programs_router
from app.api.publish_batches import router as _batches_router
from app.api.publish_audit import router as _audit_router
from app.api.publish_login_qr import router as _login_qr_router

router = APIRouter()
router.include_router(_tasks_router)
router.include_router(_profiles_router)
router.include_router(_video_accounts_router)
router.include_router(_mini_programs_router)
router.include_router(_batches_router)
router.include_router(_audit_router)
router.include_router(_login_qr_router)
