import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Episode, SliceTask, SliceOutput, ClipCandidate, DetectedInterval
from app.utils.helpers import generate_cutlist, generate_intervals_file
from app.celery.tasks import slice_task as celery_slice_task
from app.services.minio_service import get_presigned_url

router = APIRouter()


class SliceRunRequest(BaseModel):
    mode: str = "fast"
    dedupe_config: Optional[dict] = None
    video_path: Optional[str] = None


class SliceRunResponse(BaseModel):
    task_id: str
    celery_task_id: str
    message: str


class SliceTaskResponse(BaseModel):
    id: str
    episode_id: str
    celery_task_id: Optional[str] = None
    mode: Optional[str] = None
    status: Optional[str] = None
    progress: float
    output_count: int
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class SliceOutputResponse(BaseModel):
    id: str
    task_id: str
    clip_id: Optional[str] = None
    file_key: Optional[str] = None
    file_name: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    resolution: Optional[str] = None
    created_at: str
    presigned_url: Optional[str] = None

    model_config = {"from_attributes": True}


def _serialize_task(task: SliceTask) -> dict:
    return {
        "id": str(task.id),
        "episode_id": str(task.episode_id),
        "celery_task_id": task.celery_task_id,
        "mode": task.mode,
        "status": task.status,
        "progress": task.progress or 0.0,
        "output_count": task.output_count or 0,
        "error_message": task.error_message,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else "",
    }


def _serialize_output(output: SliceOutput, presigned_url: Optional[str] = None) -> dict:
    return {
        "id": str(output.id),
        "task_id": str(output.task_id),
        "clip_id": str(output.clip_id) if output.clip_id else None,
        "file_key": output.file_key,
        "file_name": output.file_name,
        "duration": output.duration,
        "file_size": output.file_size,
        "resolution": output.resolution,
        "created_at": output.created_at.isoformat() if output.created_at else "",
        "presigned_url": presigned_url,
    }


@router.post("/episodes/{episode_id}/slice/run", response_model=SliceRunResponse)
async def run_slice(
    episode_id: str,
    data: SliceRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger video slicing for an episode."""
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

    # Generate cutlist from accepted clips
    clips_result = await db.execute(
        select(ClipCandidate).where(
            ClipCandidate.episode_id == eid,
            ClipCandidate.status == "accepted",
        )
    )
    accepted_clips = clips_result.scalars().all()
    if not accepted_clips:
        raise HTTPException(
            status_code=400,
            detail="没有已通过的候选片段，无法生成切片。请先在片段审核中通过至少一个片段，或重新触发选点。",
        )
    cutlist = generate_cutlist(accepted_clips)

    # Generate intervals from enabled intervals
    intervals_result = await db.execute(
        select(DetectedInterval).where(
            DetectedInterval.episode_id == eid,
            DetectedInterval.enabled == True,
        )
    )
    enabled_intervals = intervals_result.scalars().all()
    intervals_content = generate_intervals_file(enabled_intervals)

    # Create slice task record
    slice_task = SliceTask(
        episode_id=eid,
        mode=data.mode,
        cutlist=cutlist,
        intervals=intervals_content,
        dedupe_config=data.dedupe_config,
        status="pending",
        progress=0.0,
    )
    db.add(slice_task)
    await db.flush()
    await db.refresh(slice_task)

    # 切片启动时推进剧集状态，使工作流步骤条正确展示到“切片执行”
    if episode.status not in ("slicing", "completed"):
        episode.status = "slicing"
    await db.flush()

    # Dispatch Celery task
    task = celery_slice_task.delay(
        episode_id=str(eid),
        source_path=video_path,
        cutlist=cutlist,
        intervals=intervals_content,
        mode=data.mode,
        dedupe_config=data.dedupe_config,
        task_id=str(slice_task.id),
        source_file_key=source_file_key,
    )

    # Update slice task with celery task ID
    slice_task.celery_task_id = task.id
    slice_task.status = "running"
    slice_task.started_at = datetime.utcnow()
    await db.flush()

    return SliceRunResponse(
        task_id=str(slice_task.id),
        celery_task_id=task.id,
        message=f"切片任务已启动（模式: {data.mode}），正在处理中…",
    )


@router.get("/episodes/{episode_id}/slice/tasks", response_model=List[SliceTaskResponse])
async def list_slice_tasks(
    episode_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all slice tasks for an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 排除 detect_* 内部进度跟踪记录（区间检测复用了 slice_tasks 表）
    result = await db.execute(
        select(SliceTask)
        .where(SliceTask.episode_id == eid)
        .where(~SliceTask.mode.like("detect_%"))
        .order_by(SliceTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_serialize_task(t) for t in tasks]


@router.get("/slice-tasks/{task_id}", response_model=SliceTaskResponse)
async def get_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a slice task's details and progress."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # Try to get progress from Celery
    if task.celery_task_id:
        try:
            from celery.result import AsyncResult
            from app.celery.tasks import celery_app

            async_result = AsyncResult(task.celery_task_id, app=celery_app)
            if async_result.state == "PROGRESS":
                meta = async_result.info or {}
                task.progress = meta.get("progress", task.progress)
            elif async_result.state == "SUCCESS":
                task.progress = 100.0
                task.status = "completed"
                task.completed_at = datetime.utcnow()
            elif async_result.state == "FAILURE":
                task.status = "failed"
                task.error_message = str(async_result.info) if async_result.info else "Unknown error"
            elif async_result.state == "REVOKED":
                task.status = "cancelled"
        except Exception:
            pass

    await db.flush()
    return _serialize_task(task)


@router.get("/slice-tasks/{task_id}/outputs", response_model=List[SliceOutputResponse])
async def get_slice_outputs(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all outputs for a slice task."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # Verify task exists
    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Slice task not found")

    # Get outputs
    outputs_result = await db.execute(
        select(SliceOutput)
        .where(SliceOutput.task_id == tid)
        .order_by(SliceOutput.created_at.asc())
    )
    outputs = outputs_result.scalars().all()

    # Generate presigned URLs for each output
    result_list = []
    for output in outputs:
        url = None
        if output.file_key:
            url = await get_presigned_url("sliced", output.file_key, expires_seconds=3600)
        result_list.append(_serialize_output(output, url))

    return result_list


@router.post("/slice-tasks/{task_id}/retry", response_model=SliceRunResponse)
async def retry_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed or cancelled slice task by re-dispatching it."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    if task.status not in ("failed", "cancelled", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry task with status '{task.status}'",
        )

    episode = await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ep = episode.scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")

    source_file_key = ep.source_file_key
    if not source_file_key:
        raise HTTPException(status_code=400, detail="Episode has no source file")

    new_task = SliceTask(
        episode_id=task.episode_id,
        mode=task.mode,
        cutlist=task.cutlist,
        intervals=task.intervals,
        dedupe_config=task.dedupe_config,
        status="pending",
        progress=0.0,
    )
    db.add(new_task)
    await db.flush()
    await db.refresh(new_task)

    celery = celery_slice_task.delay(
        episode_id=str(task.episode_id),
        source_path=f"/data/videos/{source_file_key}",
        cutlist=task.cutlist or "",
        intervals=task.intervals or "",
        mode=task.mode or "fast",
        dedupe_config=task.dedupe_config,
        task_id=str(new_task.id),
        source_file_key=source_file_key,
    )
    new_task.celery_task_id = celery.id
    new_task.status = "running"
    new_task.started_at = datetime.utcnow()
    if ep.status not in ("slicing", "completed"):
        ep.status = "slicing"
    await db.flush()

    return SliceRunResponse(
        task_id=str(new_task.id),
        celery_task_id=celery.id,
        message="切片任务已重新调度",
    )


@router.post("/slice-tasks/{task_id}/cancel", response_model=dict)
async def cancel_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running slice task."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status '{task.status}'",
        )

    # Revoke Celery task
    if task.celery_task_id:
        try:
            from celery.result import AsyncResult
            from app.celery.tasks import celery_app

            celery_app.control.revoke(task.celery_task_id, terminate=True)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to cancel Celery task: {e}",
            )

    task.status = "cancelled"
    await db.flush()

    return {"message": "任务已取消", "task_id": task_id}