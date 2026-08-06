"""切片任务 API。

支持通过 Redis Stream 将切片任务分发到 Worker 节点，
并接收 Worker 的回调结果。
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import (
    Episode,
    SliceTask,
    SliceOutput,
    ClipCandidate,
    DetectedInterval,
)
from app.utils.helpers import generate_cutlist, generate_intervals_file
from app.services.minio_service import get_presigned_url, get_presigned_upload_url
from app.services.redis_stream import (
    publish_slice_task,
    get_task_redis_status,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class SliceRunRequest(BaseModel):
    mode: str = "fast"
    dedupe_config: Optional[dict] = None
    video_path: Optional[str] = None


class SliceRunResponse(BaseModel):
    task_id: str
    message: str


class SliceTaskResponse(BaseModel):
    id: str
    episode_id: str
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


class SliceTaskCallback(BaseModel):
    """Worker 回调请求体"""
    task_id: str
    status: str  # "completed" | "failed" | "progress"
    node_id: Optional[str] = None
    outputs: list[dict] = []
    output_count: int = 0
    error: str = ""
    progress: Optional[float] = None
    phase: str = ""
    completed_at: Optional[str] = None


# ──────────────────────────────────────────────
# 序列化函数
# ──────────────────────────────────────────────


def _serialize_task(task: SliceTask) -> dict:
    return {
        "id": str(task.id),
        "episode_id": str(task.episode_id),
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


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


async def _publish_to_worker(
    slice_task: SliceTask,
    episode: Episode,
    cutlist: str,
    intervals_content: str,
    source_file_key: Optional[str],
    dedupe_config: Optional[dict],
) -> bool:
    """构造 Worker 任务 payload 并发布到 Redis Stream。

    Returns:
        是否成功发布
    """
    # 生成源视频的 presigned GET URL（有效期 2 小时）
    source_url = None
    if source_file_key:
        source_url = await get_presigned_url(
            "raw-footage", source_file_key, expires_seconds=7200
        )

    # 生成输出文件的 presigned PUT URL 前缀
    # Worker 会在上传时拼接文件名
    output_prefix = f"slices/{str(slice_task.episode_id)}/{str(slice_task.id)}/"
    upload_url = await get_presigned_upload_url(
        "sliced",
        f"{output_prefix}placeholder.mp4",
        expires_seconds=7200,
    )

    # 构造 Worker 任务 payload（匹配 Go Worker 的 SliceTask 结构体）
    task_payload = {
        "task_id": str(slice_task.id),
        "episode_id": str(slice_task.episode_id),
        "priority": "normal",
        "mode": slice_task.mode or "fast",
        "required_tags": [],
        "source": {
            "url": source_url or "",
        },
        "cutlist": cutlist,
        "intervals": intervals_content,
        "dedupe_config": dedupe_config or {},
        "output": {
            "upload_urls": {
                "default": upload_url or "",
            },
            "callback_url": f"http://backend:8080/api/slice-tasks/{slice_task.id}/callback",
        },
        "timeout_seconds": 7200,
        "created_at": datetime.utcnow().isoformat(),
    }

    # 发布到 Redis Stream
    msg_id = await publish_slice_task(task_payload)
    if not msg_id:
        logger.error("Failed to publish slice task %s to Redis Stream", slice_task.id)
        return False

    logger.info(
        "Published slice task %s to Redis Stream (msg_id=%s)",
        slice_task.id,
        msg_id,
    )
    return True


# ──────────────────────────────────────────────
# API 端点
# ──────────────────────────────────────────────


@router.post("/episodes/{episode_id}/slice/run", response_model=SliceRunResponse)
async def run_slice(
    episode_id: str,
    data: SliceRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger video slicing for an episode via Worker node."""
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

    # Publish to Redis Stream for Worker
    published = await _publish_to_worker(
        slice_task,
        episode,
        cutlist,
        intervals_content,
        source_file_key,
        data.dedupe_config,
    )

    if not published:
        # 如果发布失败，标记任务为失败
        slice_task.status = "failed"
        slice_task.error_message = "发布到 Worker 队列失败，请检查 Redis 连接"
        await db.flush()
        raise HTTPException(
            status_code=500,
            detail="发布切片任务到 Worker 队列失败，请检查 Redis 连接",
        )

    slice_task.status = "running"
    slice_task.started_at = datetime.utcnow()
    await db.flush()

    return SliceRunResponse(
        task_id=str(slice_task.id),
        message=f"切片任务已发布到 Worker 队列（模式: {data.mode}），正在处理中…",
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

    result = await db.execute(
        select(SliceTask)
        .where(SliceTask.episode_id == eid)
        .order_by(SliceTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_serialize_task(t) for t in tasks]


@router.get("/slice-tasks/{task_id}", response_model=SliceTaskResponse)
async def get_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a slice task's details and progress.

    同时从 Redis 获取 Worker 上报的实时进度，同步到数据库。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 从 Redis 获取 Worker 上报的实时状态
    try:
        redis_status = await get_task_redis_status(task_id)
        if redis_status:
            rs = redis_status
            if rs.get("status") == "completed" and task.status != "completed":
                task.status = "completed"
                task.progress = 100.0
                task.completed_at = datetime.utcnow()
            elif rs.get("status") == "failed" and task.status != "failed":
                task.status = "failed"
                task.error_message = rs.get("error", "Worker 报告错误")
                task.completed_at = datetime.utcnow()
            elif rs.get("progress") is not None:
                task.progress = max(task.progress or 0, rs["progress"])
    except Exception as e:
        logger.warning("Failed to get Redis status for task %s: %s", task_id, e)

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


@router.post("/slice-tasks/{task_id}/callback")
async def slice_task_callback(
    task_id: str,
    data: SliceTaskCallback,
    db: AsyncSession = Depends(get_db),
):
    """Worker 完成任务后的回调。

    Worker 在处理完切片任务后，调用此接口通知后端结果。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    now = datetime.utcnow()

    if data.status == "completed":
        # 创建 SliceOutput 记录
        for out in data.outputs:
            clip_id = None
            # 尝试从文件名匹配 clip_id（文件名格式：clip_{index}.mp4）
            fname = out.get("file_name", "")
            db_output = SliceOutput(
                task_id=tid,
                clip_id=clip_id,
                file_key=out.get("file_key", ""),
                file_name=fname,
                duration=out.get("duration"),
                file_size=out.get("file_size"),
                created_at=now,
            )
            db.add(db_output)

        task.status = "completed"
        task.progress = 100.0
        task.output_count = data.output_count or len(data.outputs)
        task.completed_at = now
        task.error_message = None
        logger.info("Slice task %s completed with %d outputs", task_id, task.output_count)

    elif data.status == "progress":
        # 进度更新
        if data.progress is not None:
            task.progress = max(task.progress or 0, data.progress)

    else:  # failed
        task.status = "failed"
        task.error_message = (data.error or "Worker 报告错误")[:2000]
        task.completed_at = now
        logger.warning("Slice task %s failed: %s", task_id, task.error_message)

    await db.flush()
    return {"ok": True}


@router.post("/slice-tasks/{task_id}/progress")
async def update_slice_progress(
    task_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Worker 实时进度上报端点。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    progress = data.get("progress")
    if progress is not None:
        task.progress = max(task.progress or 0, float(progress))

    await db.flush()
    return {"ok": True}


@router.post("/slice-tasks/{task_id}/retry", response_model=SliceRunResponse)
async def retry_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed or cancelled slice task by re-dispatching it to Worker."""
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

    published = await _publish_to_worker(
        new_task,
        ep,
        task.cutlist or "",
        task.intervals or "",
        source_file_key,
        task.dedupe_config,
    )

    if not published:
        new_task.status = "failed"
        new_task.error_message = "发布到 Worker 队列失败"
        await db.flush()
        raise HTTPException(
            status_code=500,
            detail="发布切片任务到 Worker 队列失败",
        )

    new_task.status = "running"
    new_task.started_at = datetime.utcnow()
    await db.flush()

    return SliceRunResponse(
        task_id=str(new_task.id),
        message="切片任务已重新发布到 Worker 队列",
    )


@router.post("/slice-tasks/{task_id}/cancel", response_model=dict)
async def cancel_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running slice task.

    注意：Worker 模式下，取消操作仅更新数据库状态，
    Worker 端的任务需要通过心跳机制或任务超时来终止。
    """
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

    task.status = "cancelled"
    await db.flush()

    return {"message": "任务已取消（Worker 端任务将在下次心跳时超时终止）", "task_id": task_id}