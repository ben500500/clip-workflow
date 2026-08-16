"""wechat_download API 路由（前缀 /api/wechat-dl/*，独立路由，立项决策④）。

P0 提供：
- POST /api/wechat-dl/import   提交分享链接 + 授权材料 → 创建下载任务并投递 wechat_dl 队列
- GET  /api/wechat-dl/tasks     下载任务列表
- GET  /api/wechat-dl/tasks/:id 下载任务详情
- GET  /api/wechat-dl/auths     已登记授权材料列表

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

from wechat_download.models import WechatDownloadTask, WechatSourceAuth
from wechat_download.service import (
    AuthRequiredError,
    create_import_task,
    get_task,
    _serialize_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat-dl", tags=["wechat-dl"])


class ImportRequest(BaseModel):
    """导入请求：分享链接 + 授权材料（P0 单链接）。

    合规（R1）：source_type=authorized（默认）时，必须提供 auth_id（复用已登记
    授权记录）或 authorize_note（文字备注，双通道之 P0 通道）二选一，否则拦截。
    """
    source_url: str = Field(..., description="视频号分享链接")
    source_type: str = Field("authorized", description="authorized(已授权第三方) / self_owned(自有)")
    project_id: Optional[uuid.UUID] = None
    auth_id: Optional[uuid.UUID] = None
    authorize_owner: Optional[str] = None
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
    """提交视频号分享链接导入下载任务（合规校验后投递 wechat_dl 队列）。"""
    try:
        task = await create_import_task(
            db,
            created_by=current_user.id if current_user else None,
            source_url=data.source_url.strip(),
            source_type=data.source_type,
            project_id=data.project_id,
            auth_id=data.auth_id,
            authorize_owner=data.authorize_owner,
            authorize_note=data.authorize_note,
        )
    except AuthRequiredError as e:
        raise HTTPException(status_code=403, detail=str(e))

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


@router.get("/auths")
async def list_auths(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """已登记授权材料列表（供导入时选择 auth_id）。"""
    result = await db.execute(
        select(WechatSourceAuth).order_by(WechatSourceAuth.created_at.desc()).limit(limit)
    )
    auths = result.scalars().all()
    return {
        "items": [
            {
                "id": str(a.id),
                "owner": a.authorize_owner,
                "type": a.authorize_type,
                "note": a.authorize_note,
                "is_active": a.is_active,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in auths
        ],
        "total": len(auths),
    }
