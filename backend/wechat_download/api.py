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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import User, user_can_access_all_materials

from wechat_download.models import WechatDownloadTask
from wechat_download.provider_registry import (
    fetch_provider_balances,
    get_provider_infos,
)
from wechat_download.service import (
    create_import_task,
    create_import_tasks_batch,
    get_task,
    _serialize_task,
    ST_COMPLETED,
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


@router.get("/providers")
async def wechat_dl_providers(
    current_user: User = Depends(get_current_user),
):
    """返回资源下载当前使用的解析服务（API 名称 / 官网 / 是否需充值）及其余量。

    - 官网链接用于跳转充值/开通页面。
    - 余量：对配置了 WECHAT_DL_<NAME>_QUOTA_PATH 的第三方服务商实时查询；
      未配置或无余量接口的 provider 返回 balance=null（未知）。
    """
    infos = get_provider_infos()
    balances = await fetch_provider_balances()
    items = []
    for info in infos:
        bal = balances.get(info.channel)
        d = info.to_dict()
        if bal:
            d["balance"] = bal.get("balance")
            d["balance_unit"] = bal.get("unit") or d["balance_unit"]
            d["balance_error"] = bal.get("error")
        items.append(d)
    return {"items": items}


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
# 一键导入切片项目
# ───────────────────────────────

class ImportToProjectRequest(BaseModel):
    """将下载结果导入切片项目。

    - target="new"：以 project_name 新建切片项目，并把 Episode 归属过去
    - target="existing"：将 Episode 归属到指定 project_id 的已有切片项目
    """
    target: str = Field(..., description="'new' 或 'existing'")
    project_name: Optional[str] = None
    project_id: Optional[uuid.UUID] = None


class ImportToProjectResponse(BaseModel):
    project_id: str
    episode_id: str
    target: str


@router.post("/tasks/{task_id}/import-to-project", response_model=ImportToProjectResponse)
async def import_task_to_project(
    task_id: uuid.UUID,
    data: ImportToProjectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """一键导入切片：将已完成下载任务的素材 Episode 归属到新建/已有切片项目。

    源视频已落在 MinIO（raw-footage 桶），file_key 与项目无关，因此只重指向
    Episode.project_id 即可，无需搬运文件。返回目标 project_id 供前端跳转。
    """
    from sqlalchemy import select as _select
    from app.models.models import Project, Episode

    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != ST_COMPLETED or not task.episode_id:
        raise HTTPException(status_code=400, detail="仅已完成且已生成素材的下载任务可导入切片")

    ep_result = await db.execute(_select(Episode).where(Episode.id == task.episode_id))
    episode = ep_result.scalar_one_or_none()
    if episode is None:
        raise HTTPException(status_code=404, detail="素材 Episode 不存在")

    if data.target == "new":
        name = (data.project_name or "").strip()
        if not name:
            meta = task.video_meta or {}
            name = meta.get("title") or "视频号导入切片项目"
        proj = Project(
            name=name,
            description="视频号资源下载一键导入切片",
            status="processing",
            created_by=current_user.id if current_user else None,
        )
        db.add(proj)
        await db.flush()
        await db.refresh(proj)
        target_project_id = proj.id
    elif data.target == "existing":
        if not data.project_id:
            raise HTTPException(status_code=400, detail="请选择目标切片项目")
        p_result = await db.execute(_select(Project).where(Project.id == data.project_id))
        proj = p_result.scalar_one_or_none()
        if proj is None:
            raise HTTPException(status_code=404, detail="目标切片项目不存在")
        if not user_can_access_all_materials(current_user) and proj.created_by != current_user.id:
            raise HTTPException(status_code=404, detail="目标切片项目不存在")
        target_project_id = proj.id
    else:
        raise HTTPException(status_code=400, detail="target 必须是 new 或 existing")

    # 重指向 Episode 到目标切片项目（file_key 不变，MinIO 对象仍有效）
    episode.project_id = target_project_id
    task.project_id = target_project_id
    await db.commit()

    return ImportToProjectResponse(
        project_id=str(target_project_id),
        episode_id=str(episode.id),
        target=data.target,
    )


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


# ───────────────────────────────
# 方向① 发布→资源下载闭环：下载完成 → 一键入切片
# ───────────────────────────────


class ToSliceRequest(BaseModel):
    """入切片请求：可选切片模式与去重配置。"""
    mode: str = Field("fast", description="切片模式：fast/standard/dedupe")
    dedupe_config: Optional[dict] = None


class ToSliceResponse(BaseModel):
    slice_task_id: str
    episode_id: str
    mode: str
    message: str


@router.post("/tasks/{task_id}/to-slice", response_model=ToSliceResponse, status_code=201)
async def to_slice(
    task_id: uuid.UUID,
    data: ToSliceRequest,
    db: AsyncSession = Depends(get_db),
):
    """将已下载完成的素材一键投入切片（方向① 闭环：下载 → 切片 → 发布）。

    校验下载任务已完成（status=completed 且已入库 episode），随后创建
    SliceTask（fast 模式）并投递到 video_processing 切片队列。切片完成后
    即可在发布管理直接发布，实现「下载 → 自动切片 → 自动发布」闭环。
    """
    from app.models.models import Episode, SliceTask

    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    if task.status != "completed" or not task.episode_id:
        raise HTTPException(
            status_code=400,
            detail="下载任务尚未完成（无已入库素材），请等待下载完成后再入切片",
        )

    ep_result = await db.execute(
        select(Episode).where(Episode.id == task.episode_id)
    )
    episode = ep_result.scalar_one_or_none()
    if episode is None:
        raise HTTPException(status_code=404, detail="关联的剧集素材不存在")

    # 创建切片任务（fast 模式：整片直接切片，无需 AI 选点）
    slice_task = SliceTask(
        episode_id=episode.id,
        mode=data.mode or "fast",
        source_bucket=settings.MINIO_BUCKET_RAW,
        source_file_key=episode.source_file_key,
        dedupe_config=data.dedupe_config,
        subtitle_align_mask=True,
        status="pending",
        progress=0.0,
    )
    db.add(slice_task)
    await db.flush()
    await db.refresh(slice_task)

    # 投递到切片队列（复用现有 slice Celery 任务）
    from app.celery.tasks import slice_task as celery_slice_task

    celery_task = celery_slice_task.delay(
        episode_id=str(episode.id),
        source_path=None,
        cutlist="",
        intervals="",
        mode=data.mode or "fast",
        dedupe_config=data.dedupe_config,
        task_id=str(slice_task.id),
        source_file_key=episode.source_file_key,
        source_bucket=settings.MINIO_BUCKET_RAW,
        subtitle_align_mask=True,
    )
    slice_task.celery_task_id = celery_task.id if celery_task else None
    slice_task.status = "running"
    slice_task.started_at = datetime.utcnow()
    episode.status = "slicing" if episode.status not in ("slicing", "completed") else episode.status
    await db.commit()

    return ToSliceResponse(
        slice_task_id=str(slice_task.id),
        episode_id=str(episode.id),
        mode=data.mode or "fast",
        message="已创建切片任务并投入 video_processing 队列，切片完成后即可在发布管理发布",
    )
