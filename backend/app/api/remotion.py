"""Remotion 高光混剪增强 API 路由。

提供：
- GET  /v1/remotion/status/{slice_task_id} — 查询 Remotion 渲染状态与产物 file_key；
- POST /v1/remotion/render/{slice_task_id} — 手动触发 Remotion 渲染（用于失败重试）。

鉴权：与其它业务路由一致，在 main.py 统一挂 Depends(get_current_user)，这里只做数据隔离校验。
路径前缀 /v1/remotion 最终经 main.py prefix="/api" 暴露为 /api/v1/remotion/...。
"""
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import SliceTask, User, Episode
from app.services.data_scope import check_project_access_by_episode

logger = logging.getLogger(__name__)

router = APIRouter()


class RemotionStatusResponse(BaseModel):
    """Remotion 渲染状态查询响应。"""

    slice_task_id: str
    remotion_status: str | None
    remotion_output_file_key: str | None
    remotion_enabled: bool
    error_message: str | None = None


class RemotionRenderResponse(BaseModel):
    """手动触发 Remotion 渲染响应。"""

    slice_task_id: str
    triggered: bool
    remotion_status: str | None
    message: str = ""


async def _load_remotion_task(
    slice_task_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession,
) -> SliceTask:
    """按 id 加载 SliceTask 并做数据隔离校验；不存在/无权限抛 404/403。"""
    try:
        tid = uuid.UUID(slice_task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slice task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)
    return task


@router.get("/v1/remotion/status/{slice_task_id}", response_model=RemotionStatusResponse)
async def get_remotion_status(
    slice_task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询指定切片任务的 Remotion 渲染状态。"""
    task = await _load_remotion_task(slice_task_id, current_user, db)
    return RemotionStatusResponse(
        slice_task_id=str(task.id),
        remotion_status=getattr(task, "remotion_status", None),
        remotion_output_file_key=getattr(task, "remotion_output_file_key", None),
        remotion_enabled=settings.REMOTION_ENABLED,
        error_message=getattr(task, "error_message", None),
    )


@router.post("/v1/remotion/render/{slice_task_id}", response_model=RemotionRenderResponse)
async def trigger_remotion_render(
    slice_task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """手动触发 Remotion 渲染（用于失败后重试 / 已 done 时重新渲染）。

    仅当任务启用 remotion_mix_config 时才投递；未启用返回 400。投递前先重置状态为
    pending，由渲染任务置 rendering/done/failed。
    """
    task = await _load_remotion_task(slice_task_id, current_user, db)

    if not task.remotion_mix_config:
        raise HTTPException(
            status_code=400,
            detail="该切片任务未启用 Remotion 混剪增强（remotion_mix_config 为空）",
        )
    if not settings.REMOTION_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="REMOTION_ENABLED 未开启，无法触发 Remotion 渲染",
        )

    from app.celery.remotion_tasks import run_remotion_mix_task

    # 互斥锁：防同任务重复渲染（输出写同一 MinIO key 会互相覆盖）
    from app.services.distributed_lock import acquire_lock, release_lock
    lock_key = f"remotion:lock:{task.id}"
    lock_token = await acquire_lock(lock_key, ttl=1800)
    if not lock_token:
        raise HTTPException(status_code=409, detail="该切片任务已有 Remotion 渲染在进行中，请稍后再试")

    # 重置状态，便于手动重试
    task.remotion_status = "pending"
    task.error_message = None
    await db.flush()

    try:
        run_remotion_mix_task.delay(str(task.id), lock_token=lock_token)
    except Exception as e:
        await release_lock(lock_key, lock_token)
        logger.error("手动触发 Remotion 渲染失败 slice_task=%s: %s", task.id, e)
        task.remotion_status = "failed"
        task.error_message = f"触发 Remotion 渲染失败: {e}"
        await db.flush()
        raise HTTPException(status_code=500, detail=f"触发 Remotion 渲染失败: {e}")

    await db.commit()
    return RemotionRenderResponse(
        slice_task_id=str(task.id),
        triggered=True,
        remotion_status="pending",
        message="Remotion 渲染任务已投递",
    )
