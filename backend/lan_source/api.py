"""lan_source API 路由（前缀 /api/lan-source/*，独立路由）。

提供：
- GET  /api/lan-source/config           获取可用配置（只读，不含密码）
- GET  /api/lan-source/dramas           剧目清单（来自管理平台，或空）
- GET  /api/lan-source/preview          预览某剧目直链（发现但不入库）
- POST /api/lan-source/import           提交导入任务（剧目 → 下载 → 入库）
- GET  /api/lan-source/tasks            导入任务列表
- GET  /api/lan-source/tasks/:id        导入任务详情
- POST /api/lan-source/tasks/:id/to-slice  已入库剧集一键投入切片

鉴权：由 main.py 统一挂载到 `_protected_routers`（Depends(get_current_user)）。
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
from app.models.models import User, SystemConfig

from lan_source.client import LanSourceNotFound, get_client
from lan_source.config import load_lan_source_config
from lan_source.models import LanSourceImport
from lan_source.service import (
    create_import_task,
    get_import_task,
    serialize_task,
    ST_COMPLETED,
    LAN_SOURCE_CONFIG_KEY,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lan-source", tags=["lan-source"])


async def _load_config(db: AsyncSession):
    """读取局域网源配置：system_config > 环境变量 > 默认。"""
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == LAN_SOURCE_CONFIG_KEY)
        )
        row = result.scalar_one_or_none()
        db_config = row.value if (row and isinstance(row.value, dict)) else {}
    except Exception:
        db_config = {}
    return load_lan_source_config(db_config=db_config)


@router.get("/config")
async def lan_source_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回局域网源配置（只读，不含任何密钥/密码）。"""
    return (await _load_config(db)).to_public_dict()


@router.get("/dramas")
async def lan_source_dramas(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """拉取局域网源可导入的剧目清单（来自管理平台 /api/bg/sync/tasks）。"""
    cfg = await _load_config(db)
    client = get_client(cfg)
    try:
        dramas = await client.discover_dramas()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取局域网剧目清单失败: {e}")
    return {
        "items": [
            {
                "name": d.name,
                "drama_id": d.drama_id,
                "total": d.total,
                "desc": d.desc,
            }
            for d in dramas
        ]
    }


@router.get("/preview")
async def lan_source_preview(
    drama_name: str = Query(..., description="剧目名"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """预览某剧目直链（仅发现，不入库）。"""
    cfg = await _load_config(db)
    client = get_client(cfg)
    try:
        episodes = await client.fetch_episodes(drama_name)
    except LanSourceNotFound:
        raise HTTPException(status_code=404, detail=f"《{drama_name}》在局域网源暂无剧集")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取《{drama_name}》剧集直链失败: {e}")
    return {
        "drama_name": drama_name,
        "items": [
            {
                "episode": e.episode,
                "title": e.title,
                "url": e.url,
                "size": e.size,
            }
            for e in episodes
        ],
    }


class ImportRequest(BaseModel):
    """导入请求：剧目名 + 可选目标项目与集数限制。"""
    drama_name: str = Field(..., description="剧目名")
    project_id: Optional[uuid.UUID] = None
    total_episodes: Optional[int] = Field(None, ge=1, description="导入集数限制（空=整剧）")


class ImportResponse(BaseModel):
    task_id: str
    drama_name: str
    status: str
    message: str


@router.post("/import", response_model=ImportResponse, status_code=201)
async def lan_source_import(
    data: ImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交局域网剧集导入任务（直接创建并投递 lan_source 队列）。"""
    cfg = await _load_config(db)
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="局域网获取剧集功能未开启（可在系统设置-局域网获取剧集中开启）")
    name = (data.drama_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="剧目名不能为空")

    task = await create_import_task(
        db,
        created_by=current_user.id if current_user else None,
        drama_name=name,
        project_id=data.project_id,
        total_episodes=data.total_episodes,
    )

    from app.celery.tasks import celery_app
    celery_task = celery_app.send_task(
        "lan_source.import_episodes",
        args=[str(task.id)],
        queue=cfg.queue,
    )
    task.celery_task_id = celery_task.id if celery_task else None
    await db.commit()

    return ImportResponse(
        task_id=str(task.id),
        drama_name=task.drama_name,
        status=task.status,
        message="已创建局域网剧集导入任务并进入 lan_source 队列",
    )


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """导入任务列表（按创建时间倒序）。"""
    stmt = select(LanSourceImport).order_by(LanSourceImport.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(LanSourceImport.status == status)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return {"items": [serialize_task(t) for t in tasks], "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def task_detail(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """导入任务详情。"""
    task = await get_import_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return serialize_task(task)


# ───────────────────────────────
# 一键投入切片
# ───────────────────────────────

class ToSliceRequest(BaseModel):
    """入切片请求：可选切片模式与去重配置。"""
    mode: str = Field("fast", description="切片模式：fast/standard/dedupe")
    dedupe_config: Optional[dict] = None
    subtitle_align_mask: bool = Field(
        True, description="字幕对齐裁切（裁掉上下黑边）。默认 True，可设为 False 关闭。"
    )


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
    """将已导入完成的某集一键投入切片（复用现有 SliceTask 创建 + 队列投递）。"""
    from app.models.models import Episode, SliceTask

    task = await get_import_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    items = task.episode_items or []
    completed_items = [it for it in items if it.get("status") == "completed" and it.get("episode_id")]
    if task.status != ST_COMPLETED or not completed_items:
        raise HTTPException(status_code=400, detail="导入任务尚未完成（无已入库剧集），请等待导入完成后再入切片")

    # 默认切第一集；可选通过 query 指定 episode_no
    target = completed_items[0]
    ep_result = await db.execute(select(Episode).where(Episode.id == uuid.UUID(target["episode_id"])))
    episode = ep_result.scalar_one_or_none()
    if episode is None:
        raise HTTPException(status_code=404, detail="关联的剧集素材不存在")

    slice_task = SliceTask(
        episode_id=episode.id,
        mode=data.mode or "fast",
        source_bucket=settings.MINIO_BUCKET_RAW,
        source_file_key=episode.source_file_key,
        dedupe_config=data.dedupe_config,
        subtitle_align_mask=data.subtitle_align_mask,
        status="pending",
        progress=0.0,
    )
    db.add(slice_task)
    await db.flush()
    await db.refresh(slice_task)

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
        subtitle_align_mask=data.subtitle_align_mask,
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
        message="已创建切片任务并投入切片队列，切片完成后即可在发布管理发布",
    )
