import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Episode, AutoClipProject, ClipCandidate
from app.services.autoclip_service import (
    create_autoclip_project,
    upload_video,
    get_pipeline_progress,
    get_clips,
    check_autoclip_health,
)
from app.celery.tasks import autoclip_task as celery_autoclip_task

router = APIRouter()


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
        "created_at": clip.created_at.isoformat() if clip.created_at else "",
    }


@router.post("/episodes/{episode_id}/autoclip/run", response_model=AutoClipRunResponse)
async def run_autoclip(
    episode_id: str,
    data: AutoClipRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger the AutoClip 6-step pipeline for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # Get episode
    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

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
    config = data.config or {}
    autoclip_project_id = await create_autoclip_project(
        name=f"episode_{episode_id}",
        config=config,
    )
    if not autoclip_project_id:
        raise HTTPException(status_code=500, detail="Failed to create AutoClip project")

    # Save or update AutoClip project association
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

    # Determine video path
    video_path = data.video_path or f"/data/videos/{episode.source_file_key}"

    # Dispatch Celery task
    task = celery_autoclip_task.delay(
        episode_id=str(eid),
        autoclip_project_id=autoclip_project_id,
        video_path=video_path,
        config=config,
    )

    # Update celery task ID
    autoclip_project.celery_task_id = task.id
    await db.flush()

    return AutoClipRunResponse(
        celery_task_id=task.id,
        autoclip_project_id=autoclip_project_id,
        message="AutoClip pipeline task dispatched",
    )


@router.get("/episodes/{episode_id}/autoclip/progress", response_model=AutoClipProgressResponse)
async def get_autoclip_progress(
    episode_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the AutoClip pipeline progress for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

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
            )

    # Fall back to local database status
    status_map = {
        "pending": "running",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
    }
    return AutoClipProgressResponse(
        status=status_map.get(autoclip_project.pipeline_status or "pending", "unknown"),
        progress=0,
        message=autoclip_project.pipeline_status or "pending",
    )


@router.get("/episodes/{episode_id}/autoclip/clips", response_model=List[ClipResponse])
async def get_autoclip_clips(
    episode_id: str,
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    db: AsyncSession = Depends(get_db),
):
    """Get the clip candidates for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

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
    db: AsyncSession = Depends(get_db),
):
    """Update a clip candidate's status or adjusted times."""
    try:
        cid = uuid.UUID(clip_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid clip ID format")

    result = await db.execute(select(ClipCandidate).where(ClipCandidate.id == cid))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

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
    db: AsyncSession = Depends(get_db),
):
    """Regenerate AutoClip clips with updated parameters."""
    # Delete existing clips for this episode
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(
        select(ClipCandidate).where(ClipCandidate.episode_id == eid)
    )
    existing_clips = result.scalars().all()
    for clip in existing_clips:
        await db.delete(clip)
    await db.flush()

    # Re-run autoclip
    return await run_autoclip(episode_id, data, db)