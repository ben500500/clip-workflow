"""wechat_download API 路由（前缀 /api/wechat-dl/*，独立路由，立项决策④）。

提供：
- POST /api/wechat-dl/import        提交视频号分享链接 → 创建下载任务并投递 wechat_dl 队列
- GET  /api/wechat-dl/tasks         下载任务列表
- GET  /api/wechat-dl/tasks/:id     下载任务详情
- POST /api/wechat-dl/import/batch  批量链接导入

授权校验已移除：任意视频号链接均可直接导入，无需绑定授权材料。

鉴权：import 端点显式依赖 get_current_user；其余查询由 main.py 统一
挂载到 `_protected_routers`（Depends(get_current_user)）。
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import User

from wechat_download.models import WechatDownloadTask
from wechat_download.service import (
    create_import_task,
    create_import_tasks_batch,
    get_task,
    _serialize_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat-dl", tags=["wechat-dl"])


class ImportRequest(BaseModel):
    """导入请求：视频号分享链接（单链接）。"""
    source_url: str = Field(..., description="视频号分享链接")
    source_type: str = Field("self_owned", description="素材类型标签（仅作审计字段，不再强制）")
    project_id: Optional[uuid.UUID] = None
    authorize_note: Optional[str] = None


class ImportResponse(BaseModel):
    task_id: str
    status: str
    source_type: str
    source_authorize: str
    message: str


@router.post("/import", response_model=ImportResponse, status_code=201)
async def import_wechat_video(
    data: ImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交视频号分享链接导入下载任务（直接创建并投递 wechat_dl 队列）。"""
    task = await create_import_task(
        db,
        created_by=current_user.id if current_user else None,
        source_url=data.source_url.strip(),
        source_type=data.source_type,
        project_id=data.project_id,
        authorize_note=data.authorize_note,
    )

    # 投递到 wechat_dl 队列
    from app.celery.tasks import celery_app
    celery_task = celery_app.send_task(
        "wechat_dl.download",
        args=[str(task.id)],
        queue=settings.WECHAT_DL_QUEUE,
    )
    task.celery_task_id = celery_task.id if celery_task else None
    await db.commit()

    return ImportResponse(
        task_id=str(task.id),
        status=task.status,
        source_type=task.source_type,
        source_authorize=task.source_authorize or "",
        message="已创建下载任务并进入 wechat_dl 队列",
    )


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """下载任务列表（按创建时间倒序）。"""
    stmt = select(WechatDownloadTask).order_by(
        WechatDownloadTask.created_at.desc()
    ).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(WechatDownloadTask.status == status)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return {"items": [_serialize_task(t) for t in tasks], "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def task_detail(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """下载任务详情。"""
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _serialize_task(task)


# ───────────────────────────────
# 批量链接导入
# ───────────────────────────────

class BatchImportRequest(BaseModel):
    """批量导入请求：多个分享链接。"""
    source_urls: list[str] = Field(..., min_length=1, max_length=100, description="视频号分享链接列表")
    source_type: str = Field("self_owned", description="素材类型标签（仅作审计字段）")
    project_id: Optional[uuid.UUID] = None
    authorize_note: Optional[str] = None


class BatchImportResponse(BaseModel):
    task_ids: list[str]
    created: int
    skipped: int
    skipped_reasons: list[str]
    message: str


@router.post("/import/batch", response_model=BatchImportResponse, status_code=201)
async def import_wechat_video_batch(
    data: BatchImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量提交视频号分享链接导入下载任务。"""
    tasks, errors = await create_import_tasks_batch(
        db,
        created_by=current_user.id if current_user else None,
        source_urls=data.source_urls,
        source_type=data.source_type,
        project_id=data.project_id,
        authorize_note=data.authorize_note,
    )

    from app.celery.tasks import celery_app
    task_ids: list[str] = []
    for t in tasks:
        celery_task = celery_app.send_task(
            "wechat_dl.download",
            args=[str(t.id)],
            queue=settings.WECHAT_DL_QUEUE,
        )
        t.celery_task_id = celery_task.id if celery_task else None
        task_ids.append(str(t.id))
    await db.commit()

    return BatchImportResponse(
        task_ids=task_ids,
        created=len(task_ids),
        skipped=len(errors),
        skipped_reasons=errors,
        message=f"已创建 {len(task_ids)} 个下载任务并进入 wechat_dl 队列",
    )
