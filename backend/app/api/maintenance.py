"""运维与性能优化 API（三期）。

- POST /api/maintenance/archive        数据归档（>90 天看板数据）
- POST /api/maintenance/cleanup-temp   清理临时文件
- POST /api/maintenance/minio-lifecycle 设置 MinIO 生命周期策略
- GET  /api/maintenance/status         查看运维状态
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_roles
from app.models.models import UserRole
from app.services.maintenance_service import (
    apply_minio_lifecycle,
    archive_old_metrics,
    cleanup_temp_files,
)

router = APIRouter()


class ArchiveRequest(BaseModel):
    days: int | None = None


class CleanupRequest(BaseModel):
    max_age_hours: int = 24


class MaintenanceStatusResponse(BaseModel):
    archive_days: int
    minio_lifecycle_days: int
    temp_cleanup_hours: int


@router.post("/maintenance/archive")
async def run_archive(
    req: ArchiveRequest,
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
):
    """执行数据归档（>90 天看板数据）."""
    try:
        return await archive_old_metrics(req.days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"归档失败: {e}")


@router.post("/maintenance/cleanup-temp")
async def run_cleanup(
    req: CleanupRequest,
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
):
    """清理任务遗留的本地临时文件."""
    try:
        return await cleanup_temp_files(req.max_age_hours)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理失败: {e}")


@router.post("/maintenance/minio-lifecycle")
async def run_minio_lifecycle(
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
):
    """为 MinIO 设置生命周期策略（未访问对象转低频存储）."""
    try:
        return await apply_minio_lifecycle()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"设置生命周期失败: {e}")


@router.get("/maintenance/status", response_model=MaintenanceStatusResponse)
async def maintenance_status(
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
):
    """查看运维配置状态."""
    from app.config import settings

    return MaintenanceStatusResponse(
        archive_days=settings.METRICS_ARCHIVE_DAYS,
        minio_lifecycle_days=settings.MINIO_LIFECYCLE_DAYS,
        temp_cleanup_hours=24,
    )
