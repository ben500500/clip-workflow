"""切片任务 API。

支持两种引擎分发方式：
- worker：通过 Redis Stream 将切片任务分发到分布式 Worker 节点（默认）
- celery：回退到 Celery 队列（兼容旧版，迁移期可回退）

Worker 完成/失败/进度均通过回调接口上报，回调与上传 URL 申请接口使用
每次任务生成的临时 Token 鉴权，防止伪造回调。
"""

import json
import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import (
    Episode,
    SliceTask,
    SliceOutput,
    ClipCandidate,
    DetectedInterval,
    SystemConfig,
)
from app.utils.helpers import generate_cutlist, generate_intervals_file
from app.services.minio_service import (
    get_presigned_url,
    get_presigned_upload_url,
    ensure_bucket,
    list_files,
    delete_file,
)
from app.services.redis_stream import (
    publish_slice_task,
    get_task_redis_status,
    store_task_callback_token,
    get_task_callback_token,
    mark_task_cancelled,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 允许的引擎类型
ALLOWED_ENGINES = ("celery", "worker")


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class SliceRunRequest(BaseModel):
    mode: str = "fast"
    dedupe_config: Optional[dict] = None
    video_path: Optional[str] = None
    engine: Optional[str] = None  # "celery" | "worker"，默认取配置 SLICE_ENGINE


class SliceRunResponse(BaseModel):
    task_id: str
    engine: str
    message: str


class SliceTaskResponse(BaseModel):
    id: str
    episode_id: str
    mode: Optional[str] = None
    status: Optional[str] = None
    progress: float
    output_count: int
    error_message: Optional[str] = None
    # 实际执行该任务的 Worker 节点 ID
    node_id: Optional[str] = None
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
        "node_id": task.node_id,
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


def _resolve_engine(request_engine: Optional[str]) -> str:
    """解析最终使用的引擎类型。"""
    engine = request_engine or settings.SLICE_ENGINE
    if engine not in ALLOWED_ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"engine 参数不合法，仅支持 {'/'.join(ALLOWED_ENGINES)}",
        )
    return engine


async def _get_max_concurrent_tasks(db: AsyncSession) -> int:
    """读取系统配置中的全局最大并发切片任务数（多人同时切片的全局闸门）。

    默认 4；配置不存在或非法时使用默认值。
    """
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "max_concurrent_tasks")
        )
        cfg = result.scalar_one_or_none()
        if cfg and cfg.value is not None:
            val = int(cfg.value)
            if val > 0:
                return val
    except (TypeError, ValueError):
        pass
    return 4


async def _acquire_concurrency_slot(db: AsyncSession) -> None:
    """全局并发闸门：超过 max_concurrent_tasks 个运行中/排队中的切片任务时拒绝新任务。

    适用于多用户/多剧集同时发起切片，保证重任务不会无限堆积抢占资源。
    """
    max_concurrent = await _get_max_concurrent_tasks(db)
    running_count = (
        await db.execute(
            select(func.count(SliceTask.id)).where(
                SliceTask.status.in_(["running", "pending"]),
                ~SliceTask.mode.like("detect_%"),
            )
        )
    ).scalar() or 0
    # 注意：调用时新任务尚未写入 DB，因此 running_count 为当前在飞任务数；
    # 允许在 running_count < max 时放行新任务，等于最多同时处理 max 个。
    if running_count >= max_concurrent:
        raise HTTPException(
            status_code=429,
            detail=(
                f"当前已有 {running_count} 个切片任务在运行/排队，"
                f"已达到全局并发上限 {max_concurrent}。"
                "请稍后再试，或到「系统设置」调大 max_concurrent_tasks。"
            ),
        )


def _output_prefix(slice_task: SliceTask) -> str:
    """输出文件在 MinIO 中的 key 前缀。"""
    return f"slices/{str(slice_task.episode_id)}/{str(slice_task.id)}/"


async def _refresh_episode_status(db: AsyncSession, episode_id) -> None:
    """根据该剧集下所有切片任务的实际状态刷新剧集状态。

    规则：
    - 若存在 running/pending 任务 → 保持/置为 slicing
    - 否则若存在已完成任务且无失败 → completed
    - 否则若全部为失败/取消 → 保持 slicing（保留失败标识，由前端提示）
    """
    try:
        eid = uuid.UUID(str(episode_id))
    except ValueError:
        return

    ep_res = await db.execute(select(Episode).where(Episode.id == eid))
    episode = ep_res.scalar_one_or_none()
    if not episode:
        return

    tasks_res = await db.execute(
        select(SliceTask).where(
            SliceTask.episode_id == eid,
            ~SliceTask.mode.like("detect_%"),
        )
    )
    all_tasks = tasks_res.scalars().all()
    if not all_tasks:
        return

    has_running = any(t.status in ("running", "pending") for t in all_tasks)
    has_completed = any(t.status == "completed" for t in all_tasks)
    has_failed = any(t.status == "failed" for t in all_tasks)

    if has_running:
        if episode.status != "completed":
            episode.status = "slicing"
    elif has_completed and not has_failed:
        episode.status = "completed"
    # 有失败任务时保持 slicing（让用户在界面看到失败并处理/重试）


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

    # 每次任务生成独立的回调/上传鉴权 Token
    callback_token = secrets.token_hex(16)

    # 回调地址使用可配置的基础地址（支持远程 Worker 通过公网/内网访问）
    callback_base = settings.WORKER_CALLBACK_BASE_URL.rstrip("/")
    callback_url = f"{callback_base}/api/slice-tasks/{slice_task.id}/callback"

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
            "upload_url": f"{callback_base}/api/slice-tasks/{slice_task.id}/upload-url",
            "callback_url": callback_url,
            "output_prefix": _output_prefix(slice_task),
            "callback_token": callback_token,
        },
        "timeout_seconds": settings.SLICE_TASK_TIMEOUT_SECONDS,
        "created_at": datetime.utcnow().isoformat(),
    }

    # 保存回调 Token 到 Redis（供回调/上传接口鉴权校验）
    await store_task_callback_token(str(slice_task.id), callback_token)

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


async def _dispatch_celery(
    slice_task: SliceTask,
    episode: Episode,
    cutlist: str,
    intervals_content: str,
    source_file_key: Optional[str],
    dedupe_config: Optional[dict],
    video_path: Optional[str],
) -> bool:
    """通过 Celery 队列分发切片任务（回退路径）。"""
    from app.celery.tasks import slice_task as celery_slice_task

    # 与旧版 Celery 路径一致：优先使用本地视频路径
    if video_path:
        source_path = video_path
    elif source_file_key:
        source_path = f"/data/videos/{source_file_key}"
    else:
        source_path = None

    task = celery_slice_task.delay(
        episode_id=str(slice_task.episode_id),
        source_path=source_path,
        cutlist=cutlist,
        intervals=intervals_content,
        mode=slice_task.mode or "fast",
        dedupe_config=dedupe_config,
        task_id=str(slice_task.id),
        source_file_key=source_file_key,
    )
    slice_task.celery_task_id = task.id
    logger.info("Dispatched slice task %s via Celery (celery_task_id=%s)", slice_task.id, task.id)
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
    """Trigger video slicing for an episode via Worker node or Celery."""
    engine = _resolve_engine(data.engine)

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

    # 多人同时切片的全局并发闸门：超过 max_concurrent_tasks 上限直接拒绝。
    # 在创建任务记录前检查，running_count 为当前在飞任务数（不含本任务），
    # 保证“同时处理的切片任务数不超过 max_concurrent_tasks”。
    await _acquire_concurrency_slot(db)

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

    if engine == "worker":
        # 确保输出桶存在（全新部署时 sliced 桶可能未初始化）
        await ensure_bucket(settings.MINIO_BUCKET_SLICED)

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
    else:
        try:
            dispatched = await _dispatch_celery(
                slice_task,
                episode,
                cutlist,
                intervals_content,
                source_file_key,
                data.dedupe_config,
                data.video_path,
            )
        except Exception as e:
            logger.error("Celery 分发切片任务失败: %s", e)
            slice_task.status = "failed"
            slice_task.error_message = f"Celery 分发失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"Celery 分发切片任务失败: {e}")
        if not dispatched:
            slice_task.status = "failed"
            slice_task.error_message = "Celery 分发失败"
            await db.flush()
            raise HTTPException(status_code=500, detail="Celery 分发切片任务失败")

    # 切片启动时推进剧集状态，使工作流步骤条正确展示到“切片执行”
    if episode.status not in ("slicing", "completed"):
        episode.status = "slicing"
    await db.flush()

    slice_task.status = "running"
    slice_task.started_at = datetime.utcnow()
    await db.flush()

    return SliceRunResponse(
        task_id=str(slice_task.id),
        engine=engine,
        message=f"切片任务已发布到 {engine} 队列（模式: {data.mode}），正在处理中…",
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
            elif rs.get("status") == "cancelled" and task.status != "cancelled":
                task.status = "cancelled"
                task.error_message = rs.get("error", "任务已取消")
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


async def _verify_worker_token(
    task_id: str,
    x_worker_token: Optional[str],
) -> bool:
    """校验 Worker 回调/上传接口的 Token。"""
    if not x_worker_token:
        return False
    expected = await get_task_callback_token(task_id)
    if not expected:
        return False
    return secrets.compare_digest(expected, x_worker_token)


@router.get("/slice-tasks/{task_id}/upload-url")
async def get_slice_upload_url(
    task_id: str,
    file_name: str,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 上传每个输出文件前，逐一申请精确绑定 object key 的 presigned PUT URL。

    修复"单 URL 拼文件名导致 MinIO 签名失效（403 SignatureDoesNotMatch）"问题。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    if not file_name or file_name != os.path.basename(file_name):
        raise HTTPException(status_code=400, detail="file_name 不合法")

    # 精确生成该文件的上传 URL（避免路径拼接导致签名失效）
    file_key = f"{_output_prefix(task)}{file_name}"
    upload_url = await get_presigned_upload_url(
        "sliced",
        file_key,
        expires_seconds=7200,
    )
    if not upload_url:
        raise HTTPException(status_code=500, detail="生成上传 URL 失败")

    return {"upload_url": upload_url, "file_key": file_key}


@router.post("/slice-tasks/{task_id}/callback")
async def slice_task_callback(
    task_id: str,
    data: SliceTaskCallback,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 完成任务后的回调。

    Worker 在处理完切片任务后，调用此接口通知后端结果。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权：防止伪造任务完成/失败回调
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    now = datetime.utcnow()

    if data.status == "completed":
        # ── 幂等保护 ──
        # 任务可能因 PEL 重新认领 / 回调重发被重复上报 completed。
        # 若任务已处于终态且输出已落库，直接返回，避免切片输出重复添加。
        if task.status == "completed":
            return {"ok": True, "duplicate": True}
        if task.status in ("failed", "cancelled") and task.output_count and task.output_count > 0:
            return {"ok": True, "duplicate": True}

        # 记录执行该任务的节点（用于切片任务列表展示"由哪个节点完成"）
        if data.node_id:
            task.node_id = data.node_id

        # 按接受的候选片段顺序映射 clip_id（文件名 clip_XX.mp4 对应片段顺序）
        clip_result = await db.execute(
            select(ClipCandidate)
            .where(
                ClipCandidate.episode_id == task.episode_id,
                ClipCandidate.status == "accepted",
            )
            .order_by(ClipCandidate.clip_index.asc())
        )
        accepted_clips = clip_result.scalars().all()

        # 按文件名中的序号或输出顺序关联 clip_id
        clip_index = 0
        for out in data.outputs:
            fname = out.get("file_name", "")
            file_key = out.get("file_key", "")
            clip_id = None
            matched = False
            # 尝试从文件名 clip_{index}.mp4 解析
            base = os.path.splitext(os.path.basename(fname))[0]
            if base.startswith("clip_"):
                try:
                    idx = int(base.split("_")[1])
                    if 1 <= idx <= len(accepted_clips):
                        clip_id = accepted_clips[idx - 1].id
                        matched = True
                except (ValueError, IndexError):
                    pass
            if not matched:
                # 兜底：按输出顺序关联
                if clip_index < len(accepted_clips):
                    clip_id = accepted_clips[clip_index].id
                clip_index += 1

            # 同一 file_key 已存在则跳过，避免重复回调/重跑时输出记录叠加
            if file_key:
                existing_out = await db.execute(
                    select(SliceOutput).where(
                        SliceOutput.task_id == tid,
                        SliceOutput.file_key == file_key,
                    )
                )
                if existing_out.scalar_one_or_none():
                    continue

            db_output = SliceOutput(
                task_id=tid,
                clip_id=clip_id,
                file_key=file_key,
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

        # 推进剧集状态：所有切片任务完成后置为 completed（而非仅依赖最近一条）
        await _refresh_episode_status(db, task.episode_id)

    elif data.status == "progress":
        # 进度更新（真实 ffmpeg 进度）
        if data.progress is not None:
            task.progress = max(task.progress or 0, data.progress)

    else:  # failed
        task.status = "failed"
        if data.node_id:
            task.node_id = data.node_id
        task.error_message = (data.error or "Worker 报告错误")[:2000]
        task.completed_at = now
        logger.warning("Slice task %s failed: %s", task_id, task.error_message)

        # 任务失败也刷新剧集状态（保证不是"最近一条未完成就永远切片中"）
        await _refresh_episode_status(db, task.episode_id)

    await db.flush()
    return {"ok": True}


@router.post("/slice-tasks/{task_id}/progress")
async def update_slice_progress(
    task_id: str,
    data: dict,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 实时进度上报端点。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

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

    engine = _resolve_engine(None)  # 沿用默认引擎

    new_task = SliceTask(
        episode_id=task.episode_id,
        mode=task.mode,
        cutlist=task.cutlist,
        intervals=task.intervals,
        dedupe_config=task.dedupe_config,
        status="pending",
        progress=0.0,
    )

    # 全局并发闸门：重试同样受 max_concurrent_tasks 限制，避免堆积
    await _acquire_concurrency_slot(db)

    db.add(new_task)
    await db.flush()
    await db.refresh(new_task)

    if engine == "worker":
        await ensure_bucket(settings.MINIO_BUCKET_SLICED)
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
    else:
        try:
            await _dispatch_celery(
                new_task,
                ep,
                task.cutlist or "",
                task.intervals or "",
                source_file_key,
                task.dedupe_config,
                None,
            )
        except Exception as e:
            new_task.status = "failed"
            new_task.error_message = f"Celery 分发失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"Celery 分发切片任务失败: {e}")

    new_task.status = "running"
    new_task.started_at = datetime.utcnow()
    if ep.status not in ("slicing", "completed"):
        ep.status = "slicing"
    await db.flush()

    return SliceRunResponse(
        task_id=str(new_task.id),
        engine=engine,
        message="切片任务已重新发布到 Worker 队列",
    )


@router.post("/slice-tasks/{task_id}/cancel", response_model=dict)
async def cancel_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running slice task.

    Worker 模式下，取消操作会同时更新数据库状态并写入 Redis 任务 Hash，
    Worker 端通过轮询任务 Hash 感知取消并强杀 ffmpeg 进程。
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

    # 写入 Redis，通知 Worker 端强杀任务
    await mark_task_cancelled(task_id)

    return {"message": "任务已取消（Worker 端将收到取消信号并终止 ffmpeg）", "task_id": task_id}


@router.delete("/slice-tasks/{task_id}", status_code=200)
async def delete_slice_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除切片任务，同时删除其输出文件（MinIO 临时资源）。

    - 若任务正在运行/排队，先取消（写入 Redis 取消标记，Worker 端会强杀 ffmpeg）
    - 删除该任务在 MinIO sliced 桶中的全部输出对象
    - 级联删除数据库中的 SliceOutput / Publication 等关联记录
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 正在运行/排队中的任务先取消，避免 Worker 还在写入
    if task.status in ("pending", "running"):
        task.status = "cancelled"
        await mark_task_cancelled(task_id)
        await db.flush()

    # 删除该任务在 MinIO 中的输出文件（slices/{episode}/{task}/ 前缀）
    prefix = _output_prefix(task)
    try:
        objs = await list_files(settings.MINIO_BUCKET_SLICED, prefix=prefix)
        for obj in objs:
            await delete_file(settings.MINIO_BUCKET_SLICED, obj["key"])
        if objs:
            logger.info("Deleted %d output files for slice task %s from MinIO", len(objs), task_id)
    except Exception as e:
        logger.warning("Failed to delete MinIO outputs for task %s: %s", task_id, e)

    # 删除数据库记录（级联删除 SliceOutput / Publication / PublishTask）
    episode_id_for_refresh = task.episode_id
    await db.delete(task)
    await db.flush()

    # 删除后刷新剧集状态（避免删除了任务仍停留在 slicing）
    await _refresh_episode_status(db, episode_id_for_refresh)
    await db.flush()

    return {"message": "任务已删除，相关输出文件已清理", "task_id": task_id}
