import os
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import Episode, AutoClipProject, ClipCandidate, AutoClipRun, User, SystemConfig
from app.services.data_scope import check_project_access_by_episode
from app.services.autoclip_service import (
    create_autoclip_project,
    upload_video,
    get_pipeline_progress,
    get_clips,
    check_autoclip_health,
    delete_autoclip_project,
)
from app.celery.tasks import autoclip_task as celery_autoclip_task
from app.utils.helpers import utc_iso

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


async def _merge_default_autoclip_config(db, config: Optional[dict]) -> dict:
    """合并系统设置 default_autoclip_config 到本次选点 config。

    - 系统设置（default_autoclip_config.llm_model / llm_provider / min_score_threshold 等）
      作为默认值打底；
    - 请求体传入的 config 字段（前端/批量任务覆盖）优先生效。
    这样在“系统设置”里修改模型名/评分阈值能真正作用于选点引擎。
    """
    base: dict = {}
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "default_autoclip_config")
        )
        cfg = result.scalar_one_or_none()
        if cfg and isinstance(cfg.value, dict):
            base = dict(cfg.value)
    except Exception as e:
        logger.warning("读取系统设置 default_autoclip_config 失败，使用请求参数: %s", e)
    if not isinstance(config, dict):
        config = {}
    merged = dict(base)
    merged.update(config)
    return merged



class AutoClipRunRequest(BaseModel):
    config: Optional[dict] = None
    video_path: Optional[str] = None


class AutoClipRunResponse(BaseModel):
    celery_task_id: str
    autoclip_project_id: Optional[str] = None
    message: str


class AutoClipProgressResponse(BaseModel):
    status: str
    progress: float
    message: str
    error_message: Optional[str] = None


class AutoClipRunResponseItem(BaseModel):
    id: str
    episode_id: str
    autoclip_project_id: Optional[str] = None
    celery_task_id: Optional[str] = None
    status: str
    progress: float
    message: Optional[str] = None
    error_message: Optional[str] = None
    config: Optional[dict] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class ClipUpdateRequest(BaseModel):
    status: Optional[str] = None
    adjusted_start: Optional[float] = None
    adjusted_end: Optional[float] = None


class ClipResponse(BaseModel):
    id: str
    episode_id: str
    clip_index: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    title: Optional[str] = None
    content: Optional[str] = None
    outline: Optional[str] = None
    score: Optional[float] = None
    recommend_reason: Optional[str] = None
    status: str
    adjusted_start: Optional[float] = None
    adjusted_end: Optional[float] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_clip(clip: ClipCandidate) -> dict:
    return {
        "id": str(clip.id),
        "episode_id": str(clip.episode_id),
        "clip_index": clip.clip_index,
        "start_time": clip.start_time,
        "end_time": clip.end_time,
        "duration": clip.duration,
        "title": clip.title,
        "content": clip.content,
        "outline": clip.outline,
        "score": clip.score,
        "recommend_reason": clip.recommend_reason,
        "status": clip.status,
        "adjusted_start": clip.adjusted_start,
        "adjusted_end": clip.adjusted_end,
        "created_at": utc_iso(clip.created_at) if clip.created_at else "",
    }


def _serialize_autoclip_run(run: AutoClipRun) -> dict:
    return {
        "id": str(run.id),
        "episode_id": str(run.episode_id),
        "autoclip_project_id": run.autoclip_project_id,
        "celery_task_id": run.celery_task_id,
        "status": run.status or "pending",
        "progress": run.progress or 0.0,
        "message": run.message,
        "error_message": run.error_message,
        "config": run.config or {},
        "started_at": utc_iso(run.started_at) if run.started_at else None,
        "completed_at": utc_iso(run.completed_at) if run.completed_at else None,
        "created_at": utc_iso(run.created_at) if run.created_at else "",
    }


@router.post("/episodes/{episode_id}/autoclip/run", response_model=AutoClipRunResponse)
async def run_autoclip(
    episode_id: str,
    data: AutoClipRunRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger the AutoClip 6-step pipeline for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # Get episode
    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 数据隔离
    await check_project_access_by_episode(db, episode, current_user)

    if data.video_path and not os.path.isfile(data.video_path):
        raise HTTPException(
            status_code=400,
            detail=f"video_path 指向的文件不存在: {data.video_path}",
        )
    if not episode.source_file_key and not data.video_path:
        raise HTTPException(
            status_code=400,
            detail="Episode has no source file. Upload a video first or provide video_path.",
        )

    # Check if AutoClip is reachable
    healthy = await check_autoclip_health()
    if not healthy:
        raise HTTPException(status_code=503, detail="AutoClip service is not reachable")

    # Create AutoClip project
    # 合并系统设置 default_autoclip_config（模型名/评分阈值等），使系统设置生效
    config = await _merge_default_autoclip_config(db, data.config)
    autoclip_project_id = await create_autoclip_project(
        name=f"episode_{episode_id}",
        config=config,
    )
    if not autoclip_project_id:
        raise HTTPException(status_code=500, detail="Failed to create AutoClip project")

    # Save or update AutoClip project association
    try:
        existing = await db.execute(
            select(AutoClipProject).where(AutoClipProject.episode_id == eid)
        )
        autoclip_project = existing.scalar_one_or_none()
        if autoclip_project:
            autoclip_project.autoclip_project_id = autoclip_project_id
            autoclip_project.config = config
            autoclip_project.pipeline_status = "pending"
        else:
            autoclip_project = AutoClipProject(
                episode_id=eid,
                autoclip_project_id=autoclip_project_id,
                config=config,
                pipeline_status="pending",
            )
            db.add(autoclip_project)
        await db.flush()
    except Exception:
        # Rollback: clean up remote project if local DB save fails
        await delete_autoclip_project(autoclip_project_id)
        raise

    # 每次选点都落库一条执行历史记录（供工作台历史展示）
    autoclip_run = AutoClipRun(
        episode_id=eid,
        autoclip_project_id=autoclip_project_id,
        status="pending",
        progress=0.0,
        message="选点任务排队中，等待处理…",
        config=config,
    )
    db.add(autoclip_run)
    # 先提交历史记录，避免 Celery 任务抢先查询时找不到记录而重复建一条
    await db.commit()
    await db.refresh(autoclip_run)

    # Determine video path
    source_file_key = episode.source_file_key
    video_path = data.video_path or f"/data/videos/{source_file_key}"

    # Dispatch Celery task
    try:
        task = celery_autoclip_task.delay(
            episode_id=str(eid),
            autoclip_project_id=autoclip_project_id,
            video_path=video_path,
            config=config,
            source_file_key=source_file_key,
        )
    except Exception as e:
        # Celery dispatch failed: mark DB status as failed
        autoclip_project.pipeline_status = "failed"
        autoclip_project.error_message = f"选点任务调度失败: {e}"
        autoclip_run.status = "failed"
        autoclip_run.error_message = f"选点任务调度失败: {e}"
        autoclip_run.completed_at = datetime.utcnow()
        # 历史记录已提前提交，这里单独提交失败状态
        await db.commit()
        raise

    # Update celery task ID
    autoclip_project.celery_task_id = task.id
    autoclip_run.celery_task_id = task.id
    await db.flush()

    return AutoClipRunResponse(
        celery_task_id=task.id,
        autoclip_project_id=autoclip_project_id,
        message="AI 智能选点任务已启动，正在分析中…",
    )


@router.get("/episodes/{episode_id}/autoclip/history", response_model=List[AutoClipRunResponseItem])
async def get_autoclip_history(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询该剧集所有 AI 选点执行历史（按创建时间倒序，数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    result = await db.execute(
        select(AutoClipRun)
        .where(AutoClipRun.episode_id == eid)
        .order_by(AutoClipRun.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [_serialize_autoclip_run(r) for r in runs]


@router.get("/episodes/{episode_id}/autoclip/progress", response_model=AutoClipProgressResponse)
async def get_autoclip_progress(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get the AutoClip pipeline progress for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    # Get autoclip project
    result = await db.execute(
        select(AutoClipProject).where(AutoClipProject.episode_id == eid)
    )
    autoclip_project = result.scalar_one_or_none()
    if not autoclip_project:
        raise HTTPException(status_code=404, detail="No AutoClip project found for this episode")

    # Try to get progress from AutoClip service
    if autoclip_project.autoclip_project_id:
        progress = await get_pipeline_progress(autoclip_project.autoclip_project_id)
        if progress:
            return AutoClipProgressResponse(
                status=progress.get("status", "unknown"),
                progress=progress.get("progress", 0),
                message=progress.get("message", ""),
                error_message=autoclip_project.error_message,
            )

    # Fall back to local database status
    status_map = {
        "pending": "running",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
    }
    message_map = {
        "pending": "选点任务排队中，等待处理…",
        "running": "选点任务运行中，正在分析视频…",
        "completed": "选点任务已完成",
        "failed": "选点任务执行失败",
    }
    status = autoclip_project.pipeline_status or "pending"
    progress_value = 100.0 if status == "completed" else 0.0
    return AutoClipProgressResponse(
        status=status_map.get(status, "unknown"),
        progress=progress_value,
        message=message_map.get(status, status),
        error_message=autoclip_project.error_message,
    )


@router.get("/episodes/{episode_id}/autoclip/clips", response_model=List[ClipResponse])
async def get_autoclip_clips(
    episode_id: str,
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get the clip candidates for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    query = select(ClipCandidate).where(ClipCandidate.episode_id == eid)
    if min_score > 0:
        query = query.where(ClipCandidate.score >= min_score)
    query = query.order_by(ClipCandidate.clip_index.asc().nullslast())

    result = await db.execute(query)
    clips = result.scalars().all()
    return [_serialize_clip(c) for c in clips]


@router.put("/clips/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: str,
    data: ClipUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Update a clip candidate's status or adjusted times（数据隔离）. """
    try:
        cid = uuid.UUID(clip_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid clip ID format")

    result = await db.execute(select(ClipCandidate).where(ClipCandidate.id == cid))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == clip.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    if data.status is not None:
        if data.status not in ("pending", "accepted", "rejected", "adjusted"):
            raise HTTPException(
                status_code=400,
                detail="Status must be one of: pending, accepted, rejected, adjusted",
            )
        clip.status = data.status
    if data.adjusted_start is not None:
        clip.adjusted_start = data.adjusted_start
    if data.adjusted_end is not None:
        clip.adjusted_end = data.adjusted_end

    await db.flush()
    await db.refresh(clip)
    return _serialize_clip(clip)


@router.post("/episodes/{episode_id}/autoclip/regenerate", response_model=AutoClipRunResponse)
async def regenerate_autoclip(
    episode_id: str,
    data: AutoClipRunRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate AutoClip clips with updated parameters（数据隔离）. 

    Creates the new AutoClip project first; only after it is successfully
    created are the old clips deleted, so a failure does not lose existing data.
    """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离：先校验当前用户对剧集所属项目的访问权限
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    # First, run autoclip to create new project and dispatch task
    response = await run_autoclip(episode_id, data, current_user, db)

    # Only after successful creation, delete old clips
    result = await db.execute(
        select(ClipCandidate).where(ClipCandidate.episode_id == eid)
    )
    existing_clips = result.scalars().all()
    for clip in existing_clips:
        # Keep clips that belong to the new run (just created by _save_autoclip_results
        # would not have happened yet since the Celery task is async). Delete all
        # pending clips from previous runs.
        if clip.status == "pending":
            await db.delete(clip)
    await db.flush()

    return response