import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Episode, DetectedInterval
from app.services.interval_service import detect_intervals as run_detect
from app.celery.tasks import detect_task as celery_detect_task

router = APIRouter()


class DetectRequest(BaseModel):
    mode: str = "credits"
    config: Optional[dict] = None
    video_path: Optional[str] = None


class DetectResponse(BaseModel):
    celery_task_id: str
    message: str


class IntervalCreate(BaseModel):
    episode_id: str
    interval_type: str
    start_time: float
    end_time: float
    confidence: Optional[float] = None
    label: Optional[str] = None
    enabled: bool = True
    source: str = "manual"


class IntervalUpdate(BaseModel):
    interval_type: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None
    label: Optional[str] = None
    enabled: Optional[bool] = None
    source: Optional[str] = None


class IntervalResponse(BaseModel):
    id: str
    episode_id: str
    interval_type: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None
    label: Optional[str] = None
    enabled: bool
    source: Optional[str] = None
    detection_config: Optional[dict] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_interval(interval: DetectedInterval) -> dict:
    return {
        "id": str(interval.id),
        "episode_id": str(interval.episode_id),
        "interval_type": interval.interval_type,
        "start_time": interval.start_time,
        "end_time": interval.end_time,
        "confidence": interval.confidence,
        "label": interval.label,
        "enabled": interval.enabled if interval.enabled is not None else True,
        "source": interval.source,
        "detection_config": interval.detection_config,
        "created_at": interval.created_at.isoformat() if interval.created_at else "",
    }


@router.post("/episodes/{episode_id}/intervals/detect", response_model=DetectResponse)
async def detect_intervals(
    episode_id: str,
    data: DetectRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger interval detection for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # Get episode
    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    video_path = data.video_path or (
        f"/data/videos/{episode.source_file_key}" if episode.source_file_key else None
    )
    if not video_path:
        raise HTTPException(
            status_code=400,
            detail="Episode has no source file. Upload a video first or provide video_path.",
        )

    # Dispatch Celery task
    task = celery_detect_task.delay(
        episode_id=str(eid),
        video_path=video_path,
        mode=data.mode,
        config=data.config or {},
    )

    return DetectResponse(
        celery_task_id=task.id,
        message=f"Interval detection task dispatched (mode: {data.mode})",
    )


@router.get("/episodes/{episode_id}/intervals", response_model=List[IntervalResponse])
async def list_intervals(
    episode_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all detected intervals for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(
        select(DetectedInterval)
        .where(DetectedInterval.episode_id == eid)
        .order_by(DetectedInterval.start_time.asc().nullslast())
    )
    intervals = result.scalars().all()
    return [_serialize_interval(i) for i in intervals]


@router.post("/intervals", response_model=IntervalResponse, status_code=201)
async def create_interval(
    data: IntervalCreate,
    db: AsyncSession = Depends(get_db),
):
    """Manually add a detected interval."""
    try:
        eid = uuid.UUID(data.episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode_id format")

    # Verify episode exists
    result = await db.execute(select(Episode).where(Episode.id == eid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Episode not found")

    interval = DetectedInterval(
        episode_id=eid,
        interval_type=data.interval_type,
        start_time=data.start_time,
        end_time=data.end_time,
        confidence=data.confidence,
        label=data.label,
        enabled=data.enabled,
        source=data.source,
    )
    db.add(interval)
    await db.flush()
    await db.refresh(interval)
    return _serialize_interval(interval)


@router.put("/intervals/{interval_id}", response_model=IntervalResponse)
async def update_interval(
    interval_id: str,
    data: IntervalUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a detected interval."""
    try:
        iid = uuid.UUID(interval_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interval ID format")

    result = await db.execute(
        select(DetectedInterval).where(DetectedInterval.id == iid)
    )
    interval = result.scalar_one_or_none()
    if not interval:
        raise HTTPException(status_code=404, detail="Interval not found")

    if data.interval_type is not None:
        interval.interval_type = data.interval_type
    if data.start_time is not None:
        interval.start_time = data.start_time
    if data.end_time is not None:
        interval.end_time = data.end_time
    if data.confidence is not None:
        interval.confidence = data.confidence
    if data.label is not None:
        interval.label = data.label
    if data.enabled is not None:
        interval.enabled = data.enabled
    if data.source is not None:
        interval.source = data.source

    await db.flush()
    await db.refresh(interval)
    return _serialize_interval(interval)


@router.delete("/intervals/{interval_id}", status_code=204)
async def delete_interval(interval_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a detected interval."""
    try:
        iid = uuid.UUID(interval_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interval ID format")

    result = await db.execute(
        select(DetectedInterval).where(DetectedInterval.id == iid)
    )
    interval = result.scalar_one_or_none()
    if not interval:
        raise HTTPException(status_code=404, detail="Interval not found")

    await db.delete(interval)
    await db.flush()


@router.put("/intervals/{interval_id}/toggle", response_model=IntervalResponse)
async def toggle_interval(interval_id: str, db: AsyncSession = Depends(get_db)):
    """Toggle the enabled/disabled state of an interval."""
    try:
        iid = uuid.UUID(interval_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interval ID format")

    result = await db.execute(
        select(DetectedInterval).where(DetectedInterval.id == iid)
    )
    interval = result.scalar_one_or_none()
    if not interval:
        raise HTTPException(status_code=404, detail="Interval not found")

    interval.enabled = not interval.enabled
    await db.flush()
    await db.refresh(interval)
    return _serialize_interval(interval)