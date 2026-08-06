import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Episode, DetectedInterval, SliceTask
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


class DetectProgressResponse(BaseModel):
    status: str
    progress: float
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

    if data.video_path and not os.path.isfile(data.video_path):
        raise HTTPException(
            status_code=400,
            detail=f"video_path 指向的文件不存在: {data.video_path}",
        )
    source_file_key = episode.source_file_key
    if not data.video_path and not source_file_key:
        raise HTTPException(
            status_code=400,
            detail="Episode has no source file. Upload a video first or provide video_path.",
        )
    video_path = data.video_path or f"/data/videos/{source_file_key}"

    # 先落库一条检测任务记录（mode 前缀 detect_），
    # 使 /intervals/progress 能立即查到进度，避免前端进度条一闪而过
    detect_record = SliceTask(
        episode_id=eid,
        mode=f"detect_{data.mode}",
        status="pending",
        progress=10.0,
    )
    db.add(detect_record)
    # 立即提交，确保 worker 侧查询能立刻看到该记录（否则进度查询会一直 unknown）
    await db.commit()

    # Dispatch Celery task
    try:
        task = celery_detect_task.delay(
            episode_id=str(eid),
            video_path=video_path,
            mode=data.mode,
            config=data.config or {},
            source_file_key=source_file_key,
            task_id=str(detect_record.id),
        )
    except Exception:
        # 调度失败：将记录标记为 failed，避免前端进度条悬挂在 0%
        detect_record.status = "failed"
        detect_record.error_message = "检测任务调度失败"
        detect_record.completed_at = datetime.utcnow()
        await db.commit()
        raise

    # 刷新后再更新，避免 worker 已把记录推进到 completed/failed 时被覆盖
    await db.refresh(detect_record)
    detect_record.celery_task_id = task.id
    if detect_record.status in (None, "pending"):
        detect_record.status = "running"
        detect_record.started_at = datetime.utcnow()
    await db.commit()

    return DetectResponse(
        celery_task_id=task.id,
        message=f"区间检测任务已启动（模式: {data.mode}），正在处理中…",
    )


@router.get("/episodes/{episode_id}/intervals/progress", response_model=DetectProgressResponse)
async def get_detect_progress(
    episode_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the interval detection progress for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # Check if there are any running detect tasks for this episode
    from app.models.models import SliceTask
    result = await db.execute(
        select(SliceTask)
        .where(SliceTask.episode_id == eid)
        .where(SliceTask.mode.like("detect_%"))
        .order_by(SliceTask.created_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()

    if task:
        status_map = {
            "pending": "running",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
        }
        message_map = {
            "pending": "检测任务排队中，等待处理…",
            "running": "检测任务运行中，正在分析视频…",
            "completed": "检测任务已完成",
            "failed": "检测任务执行失败",
        }
        ts = task.status or "pending"
        return DetectProgressResponse(
            status=status_map.get(ts, "unknown"),
            progress=task.progress or 0,
            message=message_map.get(ts, ts),
        )

    # No running task found
    return DetectProgressResponse(
        status="unknown",
        progress=0,
        message="暂无运行中的检测任务",
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