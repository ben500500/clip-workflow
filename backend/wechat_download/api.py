"""wechat_download API 路由（前缀 /api/wechat-dl/*，独立路由，立项决策④）。

P0 提供：
- POST /api/wechat-dl/import   提交分享链接 + 授权材料 → 创建下载任务并投递 wechat_dl 队列
- GET  /api/wechat-dl/tasks     下载任务列表
- GET  /api/wechat-dl/tasks/:id 下载任务详情
- GET  /api/wechat-dl/auths     已登记授权材料列表

P1 新增：
- POST /api/wechat-dl/import/batch  批量链接导入（复用统一授权材料）
- POST /api/wechat-dl/auths         登记授权材料
- PUT  /api/wechat-dl/auths/:id     更新授权材料
- DELETE /api/wechat-dl/auths/:id   删除授权材料
- POST /api/wechat-dl/auths/:id/toggle  切换授权材料有效/失效（未绑定失效则拦截）

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
    create_import_tasks_batch,
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
                "scope": a.authorize_scope,
                "file_key": a.authorize_file_key,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "is_active": a.is_active,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in auths
        ],
        "total": len(auths),
    }


# ───────────────────────────────
# P1：批量链接导入
# ───────────────────────────────

class BatchImportRequest(BaseModel):
    """批量导入请求：多个分享链接 + 统一授权材料。"""
    source_urls: list[str] = Field(..., min_length=1, max_length=100, description="视频号分享链接列表")
    source_type: str = Field("authorized", description="authorized / self_owned")
    project_id: Optional[uuid.UUID] = None
    auth_id: Optional[uuid.UUID] = None
    authorize_owner: Optional[str] = None
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
    """批量提交视频号分享链接导入下载任务（P1：批量链接）。

    复用统一授权材料；未授权（无任何授权材料）整批 403 拦截（R1 硬红线）。
    成功创建的每个任务分别投递到 wechat_dl 队列。
    """
    try:
        tasks, errors = await create_import_tasks_batch(
            db,
            created_by=current_user.id if current_user else None,
            source_urls=data.source_urls,
            source_type=data.source_type,
            project_id=data.project_id,
            auth_id=data.auth_id,
            authorize_owner=data.authorize_owner,
            authorize_note=data.authorize_note,
        )
    except AuthRequiredError as e:
        raise HTTPException(status_code=403, detail=str(e))

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


# ───────────────────────────────
# P1：授权材料管理（不含文件通道）
# ───────────────────────────────

class AuthCreateRequest(BaseModel):
    """登记授权材料（P1：文字备注通道管理，不含授权文件上传）。"""
    authorize_owner: str = Field(..., description="授权主体，如「XX 版权方」")
    authorize_type: str = Field("channel_auth", description="copyright/channel_auth/other")
    authorize_scope: Optional[str] = None
    authorize_note: Optional[str] = Field(None, description="授权材料文字备注")
    expires_at: Optional[str] = None
    is_active: bool = Field(True)


class AuthUpdateRequest(BaseModel):
    authorize_owner: Optional[str] = None
    authorize_type: Optional[str] = None
    authorize_scope: Optional[str] = None
    authorize_note: Optional[str] = None
    expires_at: Optional[str] = None
    is_active: Optional[bool] = None


@router.post("/auths", status_code=201)
async def create_auth(
    data: AuthCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """登记一条授权材料记录（P1 授权材料管理）。"""
    from datetime import datetime

    expires = None
    if data.expires_at:
        try:
            expires = datetime.fromisoformat(data.expires_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="expires_at 格式应为 ISO 时间")
    if not (data.authorize_note and data.authorize_note.strip()):
        raise HTTPException(status_code=422, detail="授权材料至少需要文字备注（authorize_note）")
    auth = WechatSourceAuth(
        created_by=current_user.id if current_user else None,
        authorize_owner=data.authorize_owner,
        authorize_type=data.authorize_type or "channel_auth",
        authorize_scope=data.authorize_scope,
        authorize_note=data.authorize_note.strip(),
        expires_at=expires,
        is_active=data.is_active,
    )
    db.add(auth)
    await db.commit()
    await db.refresh(auth)
    return {
        "id": str(auth.id),
        "owner": auth.authorize_owner,
        "type": auth.authorize_type,
        "note": auth.authorize_note,
        "is_active": auth.is_active,
        "created_at": auth.created_at.isoformat() if auth.created_at else None,
    }


@router.put("/auths/{auth_id}")
async def update_auth(
    auth_id: uuid.UUID,
    data: AuthUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新授权材料记录（P1 授权材料管理）。"""
    from datetime import datetime

    result = await db.execute(
        select(WechatSourceAuth).where(WechatSourceAuth.id == auth_id)
    )
    auth = result.scalar_one_or_none()
    if auth is None:
        raise HTTPException(status_code=404, detail="授权记录不存在")
    if data.authorize_owner is not None:
        auth.authorize_owner = data.authorize_owner
    if data.authorize_type is not None:
        auth.authorize_type = data.authorize_type
    if data.authorize_scope is not None:
        auth.authorize_scope = data.authorize_scope
    if data.authorize_note is not None:
        auth.authorize_note = data.authorize_note
    if data.is_active is not None:
        auth.is_active = data.is_active
    if data.expires_at is not None:
        try:
            auth.expires_at = datetime.fromisoformat(data.expires_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="expires_at 格式应为 ISO 时间")
    await db.commit()
    await db.refresh(auth)
    return {
        "id": str(auth.id),
        "owner": auth.authorize_owner,
        "type": auth.authorize_type,
        "note": auth.authorize_note,
        "is_active": auth.is_active,
    }


@router.delete("/auths/{auth_id}", status_code=204)
async def delete_auth(auth_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """删除授权材料记录（P1 授权材料管理）。"""
    result = await db.execute(
        select(WechatSourceAuth).where(WechatSourceAuth.id == auth_id)
    )
    auth = result.scalar_one_or_none()
    if auth is None:
        raise HTTPException(status_code=404, detail="授权记录不存在")
    await db.delete(auth)
    await db.commit()
    return None


@router.post("/auths/{auth_id}/toggle")
async def toggle_auth(auth_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """切换授权材料有效/失效状态（失效后关联链接导入将被拦截）。"""
    result = await db.execute(
        select(WechatSourceAuth).where(WechatSourceAuth.id == auth_id)
    )
    auth = result.scalar_one_or_none()
    if auth is None:
        raise HTTPException(status_code=404, detail="授权记录不存在")
    auth.is_active = not auth.is_active
    await db.commit()
    await db.refresh(auth)
    return {"id": str(auth.id), "is_active": auth.is_active}
