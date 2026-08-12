"""批量切片工作流编排服务（三期）。

核心流程：上传 JSON（剧名 + 剧集列表）→ 按剧名找/建 Project → 在项目内按顺序
对每个剧集执行「AI 选点 → 自动审核 → 一键切片 → 删除源视频」，最终汇总输出列表。

切片输出完全复用现有 `Episode → SliceTask → SliceOutput` 链路，本模块只做批量编排，
不修改切片引擎逻辑。

会话约定：本模块所有函数自建独立 AsyncSession 提交状态，避免跨会话传递 ORM 对象
导致的 detached 问题。函数统一接收 item_id/batch_id 等标量，内部按需重查。
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update

from app.config import settings
from app.database import async_session_factory
from app.models.models import (
    Project,
    Episode,
    AutoClipRun,
    ClipCandidate,
    DetectedInterval,
    SliceTask,
    SliceOutput,
    BatchSlice,
    BatchSliceItem,
)
from app.services.minio_service import (
    upload_file_from_path,
    ensure_bucket,
    delete_file,
    get_presigned_url,
)
from app.utils.helpers import utc_iso

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 序列化
# ──────────────────────────────────────────────

def serialize_batch(batch: BatchSlice) -> dict:
    return {
        "id": str(batch.id),
        "name": batch.name,
        "drama_name": batch.drama_name,
        "project_id": str(batch.project_id),
        "status": batch.status or "pending",
        "total": batch.total or 0,
        "done": batch.done or 0,
        "failed": batch.failed or 0,
        "output_count": batch.output_count or 0,
        "delete_source": batch.delete_source,
        "error_message": batch.error_message,
        "started_at": utc_iso(batch.started_at) if batch.started_at else None,
        "completed_at": utc_iso(batch.completed_at) if batch.completed_at else None,
        "created_at": utc_iso(batch.created_at) if batch.created_at else "",
    }


def serialize_item(item: BatchSliceItem) -> dict:
    return {
        "id": str(item.id),
        "batch_id": str(item.batch_id),
        "seq": item.seq,
        "title": item.title,
        "source_path": item.source_path,
        "source_file_key": item.source_file_key,
        "episode_id": str(item.episode_id) if item.episode_id else None,
        "status": item.status or "pending",
        "progress": item.progress or 0.0,
        "message": item.message,
        "error_message": item.error_message,
        "output_count": item.output_count or 0,
        "processed_at": utc_iso(item.processed_at) if item.processed_at else None,
        "created_at": utc_iso(item.created_at) if item.created_at else "",
    }


# ──────────────────────────────────────────────
# 数据访问辅助
# ──────────────────────────────────────────────

async def find_or_create_project(db, drama_name: str, created_by) -> Project:
    """按剧名查找已有项目，不存在则创建（数据隔离：记录创建人）。"""
    result = await db.execute(
        select(Project).where(Project.name == drama_name).limit(1)
    )
    project = result.scalar_one_or_none()
    if project:
        return project
    project = Project(
        name=drama_name,
        description=f"批量切片自动创建（剧名：{drama_name}）",
        created_by=created_by,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _update_item(item_id, status=None, message=None, progress=None, error=None,
                       output_count=None, processed_at=None):
    """在独立会话中更新单个批次项状态。"""
    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item:
            return
        if status is not None:
            item.status = status
        if message is not None:
            item.message = message
        if progress is not None:
            item.progress = progress
        if error is not None:
            item.error_message = error
        if output_count is not None:
            item.output_count = output_count
        if processed_at is not None:
            item.processed_at = processed_at
        await session.commit()


async def _refresh_batch(batch_id):
    """重新计算批次汇总进度。"""
    async with async_session_factory() as session:
        batch = await session.get(BatchSlice, uuid.UUID(str(batch_id)))
        if not batch:
            return
        items = (
            await session.execute(
                select(BatchSliceItem).where(BatchSliceItem.batch_id == batch.id)
            )
        ).scalars().all()
        done = sum(1 for it in items if it.status in ("completed", "skipped"))
        failed = sum(1 for it in items if it.status == "failed")
        batch.total = len(items)
        batch.done = done
        batch.failed = failed
        batch.output_count = sum(it.output_count or 0 for it in items)
        if failed > 0 and done + failed == len(items):
            batch.status = "partial_failed" if done > 0 else "failed"
            batch.completed_at = datetime.utcnow()
        elif done == len(items) and items:
            batch.status = "completed"
            batch.completed_at = datetime.utcnow()
        await session.commit()


# ──────────────────────────────────────────────
# 源视频处理
# ──────────────────────────────────────────────

async def upload_source_video(item_id) -> Optional[str]:
    """把源视频路径上传到 MinIO（raw-footage 桶），返回 file_key。

    局域网地址/本地路径在 Celery worker 或 backend 容器内需可访问。
    """
    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item:
            return None
        path = item.source_path
        if not path:
            await _update_item(item_id, status="failed", error="缺少源视频路径")
            return None
        if not os.path.isfile(path):
            await _update_item(item_id, status="failed", error=f"源视频路径不存在: {path}")
            return None

        await _update_item(item_id, status="uploading", message=f"正在上传源视频 {os.path.basename(path)}", progress=10.0)

        await ensure_bucket(settings.MINIO_BUCKET_RAW)
        file_name = os.path.basename(path)
        file_key = f"batch/{item.batch_id}/{item.seq}_{file_name}"
        ok = await upload_file_from_path(
            settings.MINIO_BUCKET_RAW, file_key, path,
            content_type="video/mp4",
        )
        if not ok:
            await _update_item(item_id, status="failed", error=f"源视频上传 MinIO 失败: {path}")
            return None

        item.source_file_key = file_key
        await session.commit()
        return file_key


async def create_episode(batch_id, item_id) -> Optional[str]:
    """为批次项创建 Episode。返回 episode_id。"""
    async with async_session_factory() as session:
        batch = await session.get(BatchSlice, uuid.UUID(str(batch_id)))
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not batch or not item:
            return None
        episode = Episode(
            project_id=batch.project_id,
            title=item.title or f"{batch.drama_name or '剧集'}_{item.seq}",
            episode_no=item.seq,
            source_file_key=item.source_file_key,
            status="uploaded",
        )
        session.add(episode)
        await session.flush()
        await session.refresh(episode)
        item.episode_id = episode.id
        await session.commit()
        return str(episode.id)


async def delete_source_video(item_id, delete_source: bool) -> None:
    """处理完成后删除源视频，节约空间。

    - MinIO 已上传对象（source_file_key）→ 删除 raw-footage 桶中的对象
    - 本地/局域网源文件（source_path）→ 删除本地文件
    """
    if not delete_source:
        return
    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item:
            return
        file_key = item.source_file_key
        source_path = item.source_path
    if file_key:
        try:
            await delete_file(settings.MINIO_BUCKET_RAW, file_key)
            logger.info("Deleted MinIO source object %s", file_key)
        except Exception as e:
            logger.warning("Failed to delete MinIO source %s: %s", file_key, e)
    if source_path and os.path.isfile(source_path):
        try:
            os.unlink(source_path)
            logger.info("Deleted local source file %s", source_path)
        except OSError as e:
            logger.warning("Failed to delete local source %s: %s", source_path, e)


# ──────────────────────────────────────────────
# AI 选点 + 自动审核
# ──────────────────────────────────────────────

async def dispatch_autoclip(item_id) -> bool:
    """触发 AI 智能选点，完整复用 autoclip API 的分发链路。

    与 `run_autoclip` 端点一致：建 AutoClip 项目 → 落库关联 + 历史记录 → 派发 Celery 任务。
    """
    from app.celery.tasks import autoclip_task as celery_autoclip_task
    from app.services.autoclip_service import (
        create_autoclip_project,
        check_autoclip_health,
        delete_autoclip_project,
    )
    from app.models.models import AutoClipProject

    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item or not item.episode_id:
            return False
        episode_id = str(item.episode_id)
        file_key = item.source_file_key
    video_path = f"/data/videos/{file_key}"

    # AutoClip 服务健康检查
    try:
        healthy = await check_autoclip_health()
    except Exception as e:
        await _update_item(item_id, status="failed", error=f"AutoClip 服务检查失败: {e}")
        return False
    if not healthy:
        await _update_item(item_id, status="failed", error="AutoClip 服务不可用")
        return False

    # 创建 AutoClip 项目
    try:
        autoclip_project_id = await create_autoclip_project(
            name=f"episode_{episode_id}", config={}
        )
    except Exception as e:
        await _update_item(item_id, status="failed", error=f"创建 AutoClip 项目失败: {e}")
        return False
    if not autoclip_project_id:
        await _update_item(item_id, status="failed", error="创建 AutoClip 项目失败")
        return False

    # 落库关联 + 历史记录
    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)
        existing = await session.execute(
            select(AutoClipProject).where(AutoClipProject.episode_id == eid)
        )
        autoclip_project = existing.scalar_one_or_none()
        if autoclip_project:
            autoclip_project.autoclip_project_id = autoclip_project_id
            autoclip_project.config = {}
            autoclip_project.pipeline_status = "pending"
        else:
            autoclip_project = AutoClipProject(
                episode_id=eid,
                autoclip_project_id=autoclip_project_id,
                config={},
                pipeline_status="pending",
            )
            session.add(autoclip_project)
        autoclip_run = AutoClipRun(
            episode_id=eid,
            autoclip_project_id=autoclip_project_id,
            status="pending",
            progress=0.0,
            message="选点任务排队中，等待处理…",
            config={},
        )
        session.add(autoclip_run)
        await session.flush()
        await session.refresh(autoclip_run)
        run_id = autoclip_run.id
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if item:
            item.autoclip_run_id = run_id
        await session.commit()

    # 派发 Celery 任务
    try:
        task = celery_autoclip_task.delay(
            episode_id=episode_id,
            autoclip_project_id=autoclip_project_id,
            video_path=video_path,
            config={},
            source_file_key=file_key,
        )
    except Exception as e:
        await delete_autoclip_project(autoclip_project_id)
        await _update_item(item_id, status="failed", error=f"选点任务调度失败: {e}")
        return False

    # 回填 celery_task_id
    async with async_session_factory() as session:
        run = await session.get(AutoClipRun, run_id)
        if run:
            run.celery_task_id = task.id
            await session.commit()
    return True


async def wait_autoclip_complete(item_id, timeout_s: int = 1800) -> bool:
    """轮询等待 AI 选点完成。返回是否成功。

    选点结果由 autoclip Celery 任务异步落库（_save_autoclip_results），
    这里轮询 AutoClipRun 的状态直到进入终态。
    """
    import asyncio

    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item or not item.episode_id:
            return False
        episode_id = str(item.episode_id)

    started = asyncio.get_event_loop().time()
    while True:
        async with async_session_factory() as session:
            runs = (
                await session.execute(
                    select(AutoClipRun)
                    .where(AutoClipRun.episode_id == uuid.UUID(episode_id))
                    .order_by(AutoClipRun.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if runs:
                status = runs.status or "pending"
                await _update_item(item_id, progress=runs.progress or 0.0,
                                   message=runs.message or "AI 智能选点中…")
                if status == "completed":
                    return True
                if status == "failed":
                    await _update_item(item_id, status="failed",
                                       error=runs.error_message or "AI 选点失败")
                    return False
        if asyncio.get_event_loop().time() - started > timeout_s:
            await _update_item(item_id, status="failed", error="AI 选点超时")
            return False
        await asyncio.sleep(5)


async def auto_review_clips(item_id) -> int:
    """自动审核：把该集所有候选片段置为 accepted。返回候选数。"""
    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item or not item.episode_id:
            return 0
        eid = item.episode_id
        await session.execute(
            update(ClipCandidate)
            .where(ClipCandidate.episode_id == eid)
            .values(status="accepted")
        )
        clips = (await session.execute(
            select(ClipCandidate).where(ClipCandidate.episode_id == eid)
        )).scalars().all()
        await session.commit()
        return len(clips)


# ──────────────────────────────────────────────
# 一键切片
# ──────────────────────────────────────────────

async def dispatch_slice(item_id, slice_config: Optional[dict]) -> bool:
    """触发一键切片（auto_accept_all=true），复用现有 slice 分发逻辑。

    复用 app.api.slice 的 _publish_to_worker / 配置构造，保证切片参数与单集切片一致。
    返回成功后，slice_task_id 已落库到批次项。
    """
    from app.api import slice as slice_api

    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item or not item.episode_id:
            return False
        episode = await session.get(Episode, item.episode_id)
        if not episode:
            await _update_item(item_id, status="failed", error="剧集不存在")
            return False

        # 构造 SliceRunRequest（复用现有字段）
        req = slice_api.SliceRunRequest(
            mode=(slice_config or {}).get("mode", "fast"),
            auto_accept_all=True,
            engine=(slice_config or {}).get("engine"),
            watermark_enabled=bool((slice_config or {}).get("watermark_enabled")),
            watermark_text=(slice_config or {}).get("watermark_text"),
            watermark_font_size=(slice_config or {}).get("watermark_font_size") or 28,
            watermark_opacity=(slice_config or {}).get("watermark_opacity") or 0.5,
            watermark_position=(slice_config or {}).get("watermark_position") or "bottom",
            encoder=(slice_config or {}).get("encoder"),
            vert2horiz_enabled=bool((slice_config or {}).get("vert2horiz_enabled")),
            vert2horiz_mode=(slice_config or {}).get("vert2horiz_mode"),
            vert2horiz_ratio=(slice_config or {}).get("vert2horiz_ratio"),
            vert2horiz_output_size=(slice_config or {}).get("vert2horiz_output_size"),
            subtitle_enabled=bool((slice_config or {}).get("subtitle_enabled")),
            badge_default_width=(slice_config or {}).get("badge_default_width") or 0,
        )

        source_file_key = item.source_file_key or episode.source_file_key
        source_bucket = settings.MINIO_BUCKET_RAW

        # 自动通过所有候选（一键切片要求至少有一个候选）
        clips_res = await session.execute(
            select(ClipCandidate).where(ClipCandidate.episode_id == item.episode_id)
        )
        clips = clips_res.scalars().all()
        if not clips:
            await _update_item(item_id, status="failed", error="没有候选片段，无法一键切片")
            return False
        for clip in clips:
            if clip.status == "pending":
                clip.status = "accepted"

        from app.utils.helpers import generate_cutlist, generate_intervals_file
        cutlist = generate_cutlist(clips)
        intervals_res = await session.execute(
            select(DetectedInterval).where(
                DetectedInterval.episode_id == item.episode_id,
                DetectedInterval.enabled == True,
            )
        )
        intervals_content = generate_intervals_file(intervals_res.scalars().all())

        # 构造各配置
        watermark_config = slice_api._build_watermark_config(req, episode)
        vert2horiz_config = slice_api._build_vert2horiz_config(req)
        badges_config = slice_api._build_badges_config(req)
        text_overlays_config = slice_api._build_text_overlays_config(req)
        # 字幕配置（优先复用选点字幕，否则 ASR 生成）
        subtitle_config = await slice_api._generate_subtitle_config(
            req, source_file_key, source_bucket, episode, session
        )

        # 创建切片任务记录
        slice_task = SliceTask(
            episode_id=item.episode_id,
            mode=req.mode,
            cutlist=cutlist,
            intervals=intervals_content,
            dedupe_config=(slice_config or {}).get("dedupe_config"),
            source_bucket=source_bucket,
            source_file_key=source_file_key,
            vert2horiz_config=vert2horiz_config,
            watermark_config=watermark_config,
            badges_config=badges_config,
            badge_default_width=req.badge_default_width or 0,
            subtitle_config=subtitle_config,
            text_overlays_config=text_overlays_config,
            status="pending",
            progress=0.0,
        )
        session.add(slice_task)
        await session.flush()
        await session.refresh(slice_task)

        engine = slice_api._resolve_engine(req.engine)
        if engine == "worker":
            await ensure_bucket(settings.MINIO_BUCKET_SLICED)
            published = await slice_api._publish_to_worker(
                slice_task, episode, cutlist, intervals_content,
                source_file_key, (slice_config or {}).get("dedupe_config"),
                watermark_config, req.encoder, vert2horiz_config, badges_config,
                req.badge_default_width or 0, source_bucket, subtitle_config,
                text_overlays_config,
            )
            if not published:
                slice_task.status = "failed"
                slice_task.error_message = "发布到 Worker 队列失败"
                item.slice_task_id = slice_task.id
                await session.commit()
                await _update_item(item_id, status="failed",
                                   error="发布到 Worker 队列失败", output_count=0)
                return False
        else:
            from app.api.slice import _dispatch_celery
            try:
                dispatched = await _dispatch_celery(
                    slice_task, episode, cutlist, intervals_content,
                    source_file_key, (slice_config or {}).get("dedupe_config"),
                    None, watermark_config, req.encoder, vert2horiz_config,
                    badges_config, req.badge_default_width or 0, source_bucket,
                    subtitle_config, text_overlays_config,
                )
            except Exception as e:
                slice_task.status = "failed"
                slice_task.error_message = f"Celery 分发失败: {e}"
                item.slice_task_id = slice_task.id
                await session.commit()
                await _update_item(item_id, status="failed", error=f"Celery 分发失败: {e}")
                return False
            if not dispatched:
                slice_task.status = "failed"
                slice_task.error_message = "Celery 分发失败"
                item.slice_task_id = slice_task.id
                await session.commit()
                await _update_item(item_id, status="failed", error="Celery 分发失败")
                return False

        slice_task.status = "running"
        slice_task.started_at = datetime.utcnow()
        item.slice_task_id = slice_task.id
        await session.commit()

    return True


async def wait_slice_complete(item_id, timeout_s: int = 3600) -> bool:
    """轮询等待切片任务完成。返回是否成功。"""
    import asyncio

    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        task_id = item.slice_task_id if item else None
    if not task_id:
        return False

    started = asyncio.get_event_loop().time()
    while True:
        async with async_session_factory() as session:
            task = await session.get(SliceTask, task_id)
            if task:
                await _update_item(item_id, progress=task.progress or 0.0)
                status = task.status or "pending"
                if status == "completed":
                    await _update_item(item_id, output_count=task.output_count or 0)
                    return True
                if status in ("failed", "cancelled"):
                    await _update_item(item_id, status="failed",
                                       error=task.error_message or f"切片任务{status}")
                    return False
        if asyncio.get_event_loop().time() - started > timeout_s:
            await _update_item(item_id, status="failed", error="切片任务超时")
            return False
        await asyncio.sleep(5)


async def collect_item_outputs(item_id) -> list[dict]:
    """汇总单个批次项的切片成品。"""
    async with async_session_factory() as session:
        item = await session.get(BatchSliceItem, uuid.UUID(str(item_id)))
        if not item or not item.slice_task_id:
            return []
        task = await session.get(SliceTask, item.slice_task_id)
        if not task:
            return []
        outputs_res = await session.execute(
            select(SliceOutput)
            .where(SliceOutput.task_id == item.slice_task_id)
            .order_by(SliceOutput.created_at.asc())
        )
        outputs = outputs_res.scalars().all()
        result = []
        for out in outputs:
            url = None
            if out.file_key:
                url = await get_presigned_url(
                    settings.MINIO_BUCKET_SLICED, out.file_key, expires_seconds=3600
                )
            result.append({
                "file_name": out.file_name,
                "file_key": out.file_key,
                "duration": out.duration,
                "file_size": out.file_size,
                "resolution": out.resolution,
                "presigned_url": url,
            })
        return result
