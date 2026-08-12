"""批量切片工作流服务（三期方案）。

一次请求 = 一份 JSON（剧名 + 剧集地址列表）+ 一套一键切片配置。
系统按剧名查找/创建 Project，再按列表顺序逐集完成：
    upload（上传源视频并建 Episode）→ autoclip（AI 选点）→ review（自动审核全部候选）
    → slice（一键切片）→ delete（删除源视频，节约空间）。

编排逻辑复用现有 API 端点的核心实现：
    - run_autoclip / run_slice（backend/app/api/autoclip.py、slice.py）
    通过直接调用端点函数（传入 DB 会话与操作人）复用完整的分发/调度/配置逻辑。
"""

import logging
import os
import time
import uuid
from datetime import datetime

from sqlalchemy import select, update

from app.config import settings
from app.database import async_session_factory
from app.models.models import (
    BatchSlice,
    BatchSliceItem,
    Project,
    Episode,
    AutoClipRun,
    ClipCandidate,
    SliceTask,
    User,
)

logger = logging.getLogger(__name__)

# 阶段常量
PHASE_UPLOAD = "upload"
PHASE_AUTOCLIP = "autoclip"
PHASE_REVIEW = "review"
PHASE_SLICE = "slice"
PHASE_DELETE = "source_delete"

# 轮询间隔（秒）与超时
POLL_INTERVAL = 5
AUTOCLIP_TIMEOUT = 60 * 60      # 1 小时
SLICE_TIMEOUT = 2 * 60 * 60     # 2 小时


async def _get_batch(batch_id: str):
    async with async_session_factory() as session:
        result = await session.execute(select(BatchSlice).where(BatchSlice.id == uuid.UUID(batch_id)))
        batch = result.scalar_one_or_none()
        return batch


async def _load_items(batch_id: str) -> list[BatchSliceItem]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(BatchSliceItem)
            .where(BatchSliceItem.batch_id == uuid.UUID(batch_id))
            .order_by(BatchSliceItem.seq.asc())
        )
        return result.scalars().all()


async def _update_item(item_id, **fields):
    async with async_session_factory() as session:
        await session.execute(
            update(BatchSliceItem).where(BatchSliceItem.id == item_id).values(**fields)
        )
        await session.commit()


async def _update_batch(batch_id, **fields):
    async with async_session_factory() as session:
        await session.execute(
            update(BatchSlice).where(BatchSlice.id == uuid.UUID(batch_id)).values(**fields)
        )
        await session.commit()


async def _set_phase(item, phase: str, status: str = None, progress: float = None):
    fields = {"phase": phase}
    if status:
        fields["status"] = status
    if progress is not None:
        fields["progress"] = progress
    await _update_item(item.id, **fields)
    item.phase = phase
    if status:
        item.status = status
    if progress is not None:
        item.progress = progress


async def _find_or_create_project(name: str, created_by: str) -> Project:
    """按剧名查找项目；不存在则创建（归属创建人，用于数据隔离）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Project).where(Project.name == name).order_by(Project.created_at.asc())
        )
        project = result.scalars().first()
        if project:
            return project
        project = Project(
            name=name,
            description="批量切片工作流自动创建",
            config={"source": "batch_slice"},
            created_by=uuid.UUID(created_by),
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project


async def _upload_and_create_episode(item: BatchSliceItem, project_id) -> str:
    """上传源视频到 MinIO（raw-footage）并创建 Episode，返回 episode_id。"""
    from app.services.minio_service import upload_file_from_path, ensure_bucket

    path = item.source_path
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"源视频文件不存在: {path}")

    file_name = os.path.basename(path)
    file_size = os.path.getsize(path)
    # MinIO 对象 key：batch_{batch_id}/seq_{seq}/{file_name}
    object_key = f"batch/{item.batch_id}/seq_{item.seq}/{file_name}"

    await ensure_bucket(settings.MINIO_BUCKET_RAW)
    ok = await upload_file_from_path(settings.MINIO_BUCKET_RAW, object_key, path)
    if not ok:
        raise RuntimeError(f"上传源视频到 MinIO 失败: {file_name}")

    async with async_session_factory() as session:
        episode = Episode(
            project_id=project_id,
            title=item.title or file_name,
            episode_no=item.seq,
            source_file_key=object_key,
            file_size=file_size,
            status="uploaded",
        )
        session.add(episode)
        await session.commit()
        await session.refresh(episode)
        return str(episode.id)


async def _trigger_autoclip(episode_id: str, item: BatchSliceItem, user: User, config: dict) -> str:
    """触发 AI 选点，返回 AutoClipRun id。"""
    from app.api.autoclip import run_autoclip, AutoClipRunRequest

    data = AutoClipRunRequest(
        config=config or {},
        video_path=item.source_path,
    )
    async with async_session_factory() as session:
        resp = await run_autoclip(episode_id, data, current_user=user, db=session)
        await session.commit()
    # 找到最近一条 AutoClipRun
    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)
        result = await session.execute(
            select(AutoClipRun)
            .where(AutoClipRun.episode_id == eid)
            .order_by(AutoClipRun.created_at.desc())
            .limit(1)
        )
        run = result.scalar_one_or_none()
    return str(run.id) if run else ""


async def _wait_autoclip(episode_id: str, timeout: float = AUTOCLIP_TIMEOUT):
    """轮询 AutoClipRun 直至终态，返回 (成功?, 最新状态)。"""
    eid = uuid.UUID(episode_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        async with async_session_factory() as session:
            result = await session.execute(
                select(AutoClipRun)
                .where(AutoClipRun.episode_id == eid)
                .order_by(AutoClipRun.created_at.desc())
                .limit(1)
            )
            run = result.scalar_one_or_none()
        if run is None:
            time.sleep(POLL_INTERVAL)
            continue
        if run.status == "completed":
            return True, run.status
        if run.status == "failed":
            return False, run.status
        time.sleep(POLL_INTERVAL)
    return False, "timeout"


async def _accept_all_candidates(episode_id: str) -> int:
    """自动审核：将该剧集所有候选片段置为 accepted。返回数量。"""
    eid = uuid.UUID(episode_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(ClipCandidate).where(ClipCandidate.episode_id == eid)
        )
        clips = result.scalars().all()
        for clip in clips:
            if clip.status == "pending":
                clip.status = "accepted"
        await session.commit()
        return len(clips)


async def _trigger_slice(episode_id: str, item: BatchSliceItem, user: User, slice_config: dict) -> str:
    """触发一键切片（auto_accept_all），返回 SliceTask id。"""
    from app.api.slice import run_slice, SliceRunRequest

    cfg = slice_config or {}
    # 仅透传 SliceRunRequest 已知字段，避免前端预设里的额外键导致 pydantic 报错
    known_fields = {
        "mode", "dedupe_config", "engine", "auto_accept_all",
        "watermark_enabled", "watermark_text", "watermark_font_size",
        "watermark_opacity", "watermark_position", "badges", "badge_default_width",
        "vert2horiz_enabled", "vert2horiz_mode", "vert2horiz_ratio",
        "vert2horiz_output_size", "vert2horiz_detect_interval",
        "vert2horiz_smooth_window", "vert2horiz_min_step", "vert2horiz_face_margin",
        "subtitle_enabled", "subtitle_font_ratio", "subtitle_style",
        "subtitle_color", "subtitle_border_color", "text_overlays",
        "output_id", "cut_start", "cut_end",
    }
    payload = {k: v for k, v in cfg.items() if k in known_fields and v is not None}
    payload["mode"] = cfg.get("mode") or "fast"
    payload["auto_accept_all"] = True
    payload["video_path"] = item.source_path
    data = SliceRunRequest(**payload)
    async with async_session_factory() as session:
        resp = await run_slice(episode_id, data, current_user=user, db=session)
        # run_slice 内部仅 flush 未 commit，这里显式提交以便后续轮询可见
        await session.commit()
    return resp.task_id


async def _wait_slice(episode_id: str, timeout: float = SLICE_TIMEOUT) -> tuple[bool, str, int]:
    """轮询 SliceTask 直至终态，返回 (成功?, 最新状态, output_count)。"""
    eid = uuid.UUID(episode_id)
    deadline = time.time() + timeout
    last_output_count = 0
    while time.time() < deadline:
        async with async_session_factory() as session:
            result = await session.execute(
                select(SliceTask)
                .where(SliceTask.episode_id == eid)
                .order_by(SliceTask.created_at.desc())
                .limit(1)
            )
            task = result.scalar_one_or_none()
        if task is None:
            time.sleep(POLL_INTERVAL)
            continue
        if task.output_count is not None:
            last_output_count = task.output_count
        if task.status == "completed":
            return True, task.status, task.output_count or 0
        if task.status == "failed":
            return False, task.status, task.output_count or 0
        if task.status == "cancelled":
            return False, task.status, task.output_count or 0
        time.sleep(POLL_INTERVAL)
    return False, "timeout", last_output_count


async def _delete_source(item: BatchSliceItem):
    """删除源视频：本地文件 + MinIO 对象（节约空间）。"""
    from app.services.minio_service import delete_file

    # 删除本地源文件
    if item.source_path and os.path.isfile(item.source_path):
        try:
            os.remove(item.source_path)
            logger.info("已删除本地源视频: %s", item.source_path)
        except OSError as e:
            logger.warning("删除本地源视频失败 %s: %s", item.source_path, e)
    # 删除 MinIO 对象
    if item.episode_id:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Episode).where(Episode.id == uuid.UUID(str(item.episode_id)))
            )
            episode = result.scalar_one_or_none()
            if episode and episode.source_file_key:
                await delete_file(settings.MINIO_BUCKET_RAW, episode.source_file_key)
                episode.source_file_key = None
                await session.commit()


async def run_batch(batch_id: str):
    """按序执行整批。"""
    batch = await _get_batch(batch_id)
    if batch is None:
        logger.error("Batch %s 不存在", batch_id)
        return

    # 找到操作人（用于 run_autoclip / run_slice 的数据隔离校验）
    operator = None
    if batch.created_by:
        async with async_session_factory() as session:
            result = await session.execute(select(User).where(User.id == batch.created_by))
            operator = result.scalar_one_or_none()
    if operator is None:
        await _update_batch(batch_id, status="failed", error_message="无法确定批次操作人")
        return

    # 确保项目存在（按剧名，或使用批次已绑定的项目）
    project = None
    if batch.project_id:
        async with async_session_factory() as session:
            result = await session.execute(select(Project).where(Project.id == batch.project_id))
            project = result.scalar_one_or_none()
    if project is None and batch.created_by:
        project = await _find_or_create_project(batch.name or "批量切片", str(batch.created_by))
        await _update_batch(batch_id, project_id=project.id)
    if project is None:
        await _update_batch(batch_id, status="failed", error_message="无法确定目标项目")
        return

    await _update_batch(batch_id, status="running", started_at=datetime.utcnow())
    items = await _load_items(batch_id)

    done = 0
    failed = 0
    output_count = 0

    for item in items:
        if item.status in ("completed", "cancelled"):
            continue

        # ── 上传源视频并建 Episode（重试时若已有 episode 则复用）──
        episode_id = str(item.episode_id) if item.episode_id else None
        if not episode_id:
            await _set_phase(item, PHASE_UPLOAD, "uploading", 5)
            try:
                episode_id = await _upload_and_create_episode(item, project.id)
                await _update_item(item.id, episode_id=uuid.UUID(episode_id))
                item.episode_id = uuid.UUID(episode_id)
            except Exception as e:
                logger.exception("上传源视频失败: %s", e)
                await _set_phase(item, PHASE_UPLOAD, "failed", 0)
                await _update_item(item.id, error_message=f"上传源视频失败: {e}")
                failed += 1
                continue

        # ── AI 选点 ──
        await _set_phase(item, PHASE_AUTOCLIP, "autoclip", 20)
        try:
            await _trigger_autoclip(episode_id, item, operator, {})
            ok, _status = await _wait_autoclip(episode_id)
            if not ok:
                raise RuntimeError(f"AI 选点未完成（{_status}）")
        except Exception as e:
            logger.exception("AI 选点失败: %s", e)
            await _set_phase(item, PHASE_AUTOCLIP, "failed", 0)
            await _update_item(item.id, error_message=f"AI 选点失败: {e}")
            failed += 1
            continue

        # ── 自动审核全部候选 ──
        await _set_phase(item, PHASE_REVIEW, "reviewing", 50)
        try:
            n = await _accept_all_candidates(episode_id)
            if n == 0:
                raise RuntimeError("选点未生成任何候选片段")
        except Exception as e:
            logger.exception("自动审核失败: %s", e)
            await _set_phase(item, PHASE_REVIEW, "failed", 0)
            await _update_item(item.id, error_message=f"自动审核失败: {e}")
            failed += 1
            continue

        # ── 一键切片 ──
        await _set_phase(item, PHASE_SLICE, "slicing", 60)
        try:
            task_id = await _trigger_slice(episode_id, item, operator, batch.slice_config or {})
            if task_id:
                await _update_item(item.id, slice_task_id=uuid.UUID(task_id))
                item.slice_task_id = uuid.UUID(task_id)
            ok, _status, ocount = await _wait_slice(episode_id)
            if not ok:
                raise RuntimeError(f"切片未完成（{_status}）")
        except Exception as e:
            logger.exception("一键切片失败: %s", e)
            await _set_phase(item, PHASE_SLICE, "failed", 0)
            await _update_item(item.id, error_message=f"一键切片失败: {e}")
            failed += 1
            continue

        # ── 删除源视频 ──
        await _set_phase(item, PHASE_DELETE, "deleting", 90)
        try:
            await _delete_source(item)
        except Exception as e:
            logger.warning("删除源视频失败: %s", e)

        output_count += ocount
        await _set_phase(item, PHASE_DELETE, "completed", 100)
        await _update_item(item.id, output_count=ocount, completed_at=datetime.utcnow())
        done += 1

    # 汇总批次状态
    total = len(items)
    await _update_batch(
        batch_id,
        done=done,
        failed=failed,
        output_count=output_count,
        status="completed" if failed == 0 else "partial_failed",
        completed_at=datetime.utcnow(),
    )
    logger.info("Batch %s 处理完成：done=%s failed=%s outputs=%s", batch_id, done, failed, output_count)
