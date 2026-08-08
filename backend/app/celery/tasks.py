import asyncio
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Optional

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.database import async_session_factory
from app.models.models import SliceTask

# Celery application
celery_app = Celery(
    "clip_workflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=7200,          # 2 hours hard limit
    task_soft_time_limit=6600,     # 1h50m soft limit (graceful shutdown)
    result_expires=86400,          # results expire after 24h
    broker_connection_retry_on_startup=True,
    broker_heartbeat=30,
    task_queues={
        "video_processing": {"exchange": "video_processing"},
        "publish": {"exchange": "publish"},
        "metrics": {"exchange": "metrics"},
        "default": {"exchange": "default"},
    },
    task_routes={
        "app.celery.tasks.autoclip_task": {"queue": "video_processing"},
        "app.celery.tasks.detect_task": {"queue": "video_processing"},
        "app.celery.tasks.slice_task": {"queue": "video_processing"},
        "app.celery.tasks.task_publish_video": {"queue": "publish"},
        "app.celery.tasks.confirm_publish_worker": {"queue": "publish"},
        "app.celery.tasks.task_collect_metrics": {"queue": "metrics"},
        "app.celery.tasks.watermark_task": {"queue": "video_processing"},
    },
    beat_schedule={
        "collect-metrics-daily": {
            "task": "app.celery.tasks.task_collect_metrics",
            "schedule": crontab(hour=0, minute=30),
        },
        # 三期监控告警：周期检查告警规则并推送钉钉
        "alert-check-periodic": {
            "task": "app.celery.tasks.run_alert_check_task",
            "schedule": settings.ALERT_CHECK_INTERVAL_SECONDS,
        },
        # 三期性能优化：每日归档过期看板数据 + 清理临时文件
        "maintenance-daily": {
            "task": "app.celery.tasks.maintenance_daily_task",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

logger = logging.getLogger(__name__)


_async_local = threading.local()


def run_async(coro):
    """Run an async coroutine in a sync context.

    Reuses a per-thread event loop instead of creating a new one per call:
    the global SQLAlchemy/asyncpg engine binds its connection pool to the
    first loop it sees, so switching loops between calls raises
    "attached to a different loop". Celery worker threads run tasks serially,
    so a single persistent loop per thread is safe.
    """
    loop = getattr(_async_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _async_local.loop = loop
    return loop.run_until_complete(coro)


async def _ensure_source_video(source_path: Optional[str], source_file_key: Optional[str], source_bucket: Optional[str] = None) -> Optional[str]:
    """Return a local path for the source video, downloading from MinIO if needed."""
    if source_path and os.path.isfile(source_path):
        return source_path
    if not source_file_key:
        return source_path
    from app.services.minio_service import download_to_file

    bucket = source_bucket or settings.MINIO_BUCKET_RAW
    local_path = f"/tmp/source_videos/{uuid.uuid4().hex}_{os.path.basename(source_file_key)}"
    ok = await download_to_file(bucket, source_file_key, local_path)
    if ok:
        return local_path
    return None


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def autoclip_task(self, episode_id: str, autoclip_project_id: str, video_path: str, config: dict, source_file_key: Optional[str] = None):
    """Execute the AutoClip pipeline as a Celery task.

    Downloads the source video (if needed), uploads it to the AutoClip service,
    triggers the remote pipeline, polls progress, then persists the returned
    clip candidates into the database.
    """
    from app.services.autoclip_service import (
        upload_video,
        trigger_pipeline,
        get_pipeline_progress,
        get_clips,
    )

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动 AutoClip 选点任务…"})
    run_async(_update_autoclip_run(episode_id, autoclip_project_id, "running", 5, "选点任务运行中，正在分析视频…"))

    downloaded_video_path = None
    try:
        video_path = run_async(_ensure_source_video(video_path, source_file_key))
        if not video_path:
            raise FileNotFoundError(f"Source video not found: {video_path}")
        downloaded_video_path = video_path

        # Upload the source video to the AutoClip service before running.
        uploaded = run_async(
            upload_video(autoclip_project_id, video_path, os.path.basename(video_path))
        )
        if not uploaded:
            raise RuntimeError("Failed to upload video to AutoClip service")

        success = run_async(trigger_pipeline(autoclip_project_id))
        if not success:
            raise RuntimeError("Failed to trigger AutoClip pipeline")

        # Poll for progress
        max_polls = 120  # 10 minutes at 5-second intervals
        consecutive_failures = 0
        completed = False
        for i in range(max_polls):
            progress = run_async(get_pipeline_progress(autoclip_project_id))
            if progress:
                consecutive_failures = 0
                pct = progress.get("progress", 0)
                msg = progress.get("message", "Processing...")
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": pct, "message": msg},
                )
                run_async(_update_autoclip_run(episode_id, autoclip_project_id, "running", pct, msg))
                if progress.get("status") == "completed":
                    completed = True
                    break
            else:
                # AutoClip 服务重启会丢失内存态项目，连续失败则提前失败，
                # 避免占用单 worker 空转 10 分钟。
                consecutive_failures += 1
                if consecutive_failures >= 6:
                    raise RuntimeError(
                        "AutoClip 项目状态连续查询失败（服务可能已重启导致项目丢失），请重新触发选点"
                    )
                pct = min(int((i / max_polls) * 100), 99)
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": pct, "message": f"Pipeline step {i + 1}/{max_polls}"},
                )
            import time
            time.sleep(5)

        clips = run_async(get_clips(
            autoclip_project_id,
            min_score=float(config.get("min_score_threshold") or 60),
            min_duration=float(config.get("min_duration") or 0),
            max_duration=float(config.get("max_duration") or 0),
        ))
        run_async(_save_autoclip_results(episode_id, autoclip_project_id, clips, completed))
        run_async(_update_autoclip_run(
            episode_id, autoclip_project_id,
            "completed" if completed else "failed",
            100.0 if completed else 0.0,
            f"选点完成，共生成 {len(clips)} 个候选片段" if completed else "选点未完成，请检查 AutoClip 服务",
        ))

        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "AutoClip pipeline completed", "clips": clips},
        )
        return {"episode_id": episode_id, "clips_count": len(clips), "clips": clips}

    except Exception as e:
        logger.error(f"AutoClip task failed: {e}")
        run_async(_mark_autoclip_failed(episode_id, str(e)))
        run_async(_update_autoclip_run(episode_id, autoclip_project_id, "failed", 0.0, str(e)))
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        raise
    finally:
        # Clean up downloaded source video
        if downloaded_video_path and os.path.isfile(downloaded_video_path):
            try:
                os.unlink(downloaded_video_path)
            except OSError:
                pass


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def detect_task(self, episode_id: str, video_path: str, mode: str, config: dict, source_file_key: Optional[str] = None, task_id: Optional[str] = None):
    """Execute interval detection as a Celery task."""
    from app.services.interval_service import detect_intervals

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动区间检测任务…"})

    # 检测任务记录到 slice_tasks 表（mode 前缀 detect_），供 /intervals/progress 接口查询进度。
    # 优先使用 API 层预创建的记录，避免提交后轮询窗口内查不到进度。
    detect_task_id: Optional[str] = task_id
    if not detect_task_id:
        try:
            detect_task_id = run_async(
                _create_detect_task(episode_id, mode, config, self.request.id)
            )
        except Exception as e:
            logger.warning(f"Failed to persist detect task record: {e}")

    downloaded_video_path = None
    try:
        video_path = run_async(_ensure_source_video(video_path, source_file_key))
        if not video_path:
            raise FileNotFoundError(f"Source video not found: {video_path}")
        downloaded_video_path = video_path

        self.update_state(
            state="PROGRESS",
            meta={"progress": 20, "message": f"正在分析视频（{mode} 模式）…"},
        )
        if detect_task_id:
            run_async(_update_detect_task_progress(detect_task_id, 20, "running"))

        async def _run():
            return await detect_intervals(video_path, mode, config)

        intervals = run_async(_run())

        run_async(_save_detected_intervals(episode_id, intervals, mode, config))
        run_async(_update_episode_status(episode_id, "intervals_detected"))

        # 数据落库后再标记完成，避免前端提前看到 completed 但结果尚未保存
        if detect_task_id:
            run_async(_update_detect_task_progress(detect_task_id, 100, "completed"))

        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "Detection completed", "intervals": intervals},
        )
        return {"episode_id": episode_id, "intervals_count": len(intervals), "intervals": intervals}

    except Exception as e:
        logger.error(f"Detect task failed: {e}")
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        if detect_task_id:
            try:
                run_async(_fail_detect_task(detect_task_id, str(e)))
            except Exception:
                pass
        raise
    finally:
        # Clean up downloaded source video
        if downloaded_video_path and os.path.isfile(downloaded_video_path):
            try:
                os.unlink(downloaded_video_path)
            except OSError:
                pass


async def _create_detect_task(episode_id: str, mode: str, config: dict, celery_task_id: Optional[str]) -> Optional[str]:
    """Persist a detect task record so /intervals/progress can track it."""
    from sqlalchemy import select
    from app.models.models import Episode

    async with async_session_factory() as session:
        try:
            eid = uuid.UUID(episode_id)
        except ValueError:
            return None
        episode_result = await session.execute(select(Episode).where(Episode.id == eid))
        if not episode_result.scalar_one_or_none():
            return None
        record = SliceTask(
            episode_id=eid,
            celery_task_id=celery_task_id,
            mode=f"detect_{mode}",
            status="pending",
            progress=0.0,
        )
        session.add(record)
        await session.commit()
        return str(record.id)


async def _update_detect_task_progress(detect_task_id: str, progress: float, status: str):
    """Update the progress/status of a detect task record."""
    from sqlalchemy import select

    async with async_session_factory() as session:
        try:
            tid = uuid.UUID(detect_task_id)
        except ValueError:
            return
        result = await session.execute(select(SliceTask).where(SliceTask.id == tid))
        record = result.scalar_one_or_none()
        if record:
            record.progress = progress
            record.status = status
            await session.commit()


async def _fail_detect_task(detect_task_id: str, error: str):
    """Mark a detect task record as failed."""
    from sqlalchemy import select

    async with async_session_factory() as session:
        try:
            tid = uuid.UUID(detect_task_id)
        except ValueError:
            return
        result = await session.execute(select(SliceTask).where(SliceTask.id == tid))
        record = result.scalar_one_or_none()
        if record:
            record.status = "failed"
            record.error_message = error[:2000]
            record.completed_at = datetime.utcnow()
            await session.commit()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def slice_task(
    self,
    episode_id: str,
    source_path: str,
    cutlist: str,
    intervals: str,
    mode: str,
    dedupe_config: Optional[dict] = None,
    task_id: Optional[str] = None,
    source_file_key: Optional[str] = None,
    source_bucket: Optional[str] = None,
    watermark_config: Optional[dict] = None,
    encoder: Optional[str] = None,
    vert2horiz_config: Optional[dict] = None,
):
    """Execute video slicing, upload outputs to MinIO and persist SliceOutput rows.

    encoder: 三期 GPU 加速编码，可选 h264_nvenc/hevc_nvenc/\
        h264_videotoolbox/hevc_videotoolbox/libx264；不传则引擎自动探测。
    source_bucket: 源视频所在桶；普通切片为 raw-footage，成品重新剪辑为 sliced。
    vert2horiz_config: 竖屏转横屏预处理配置（切片前把竖屏素材转成横屏）。
    """
    from app.services.slice_service import run_slice_scrub, run_slice_fast
    from app.services.minio_service import upload_file_from_path
    from app.utils.helpers import write_temp_file, ensure_dir

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动切片任务…"})

    downloaded_source_path = None
    output_dir = None
    cutlist_path = None
    intervals_path = None
    try:
        source_path = run_async(_ensure_source_video(source_path, source_file_key, source_bucket))
        if not source_path:
            raise FileNotFoundError(f"Source video not found: {source_path}")
        downloaded_source_path = source_path

        cutlist_path = write_temp_file(cutlist, suffix=".txt")
        intervals_path = write_temp_file(intervals, suffix=".txt")
        output_dir = ensure_dir(f"/tmp/slice_outputs/{episode_id}/{self.request.id}")

        # 引擎进度回调会在 async 循环内被同步调用，不能在这里 run_async
        # （会嵌套事件循环报错）。只收集进度，引擎结束后统一写库。
        progress_values: list[int] = []

        def progress_cb(pct: int, message: str = ""):
            self.update_state(
                state="PROGRESS",
                meta={"progress": pct, "message": message},
            )
            progress_values.append(pct)

        if mode == "scrub":
            returncode, stdout, stderr = run_async(
                run_slice_scrub(
                    source_path,
                    cutlist_path,
                    intervals_path,
                    output_dir,
                    progress_cb=progress_cb,
                    watermark_config=watermark_config,
                    encoder=encoder,
                    vert2horiz_config=vert2horiz_config,
                )
            )
        else:
            returncode, stdout, stderr = run_async(
                run_slice_fast(
                    source_path,
                    cutlist_path,
                    output_dir,
                    mode,
                    progress_cb=progress_cb,
                    watermark_config=watermark_config,
                    encoder=encoder,
                    vert2horiz_config=vert2horiz_config,
                )
            )

        if returncode != 0:
            raise RuntimeError(stderr or "Slice script failed")

        if progress_values:
            run_async(_update_slice_task_progress(task_id, progress_values[-1]))

        manifest = _parse_engine_manifest(stdout, output_dir)
        output_files = []
        for entry in manifest:
            file_path = entry["path"]
            if not os.path.isfile(file_path):
                continue
            file_key = f"slices/{episode_id}/{self.request.id}/{entry['name']}"
            ok = run_async(upload_file_from_path("sliced", file_key, file_path))
            if not ok:
                raise RuntimeError(f"Failed to upload slice output to MinIO: {entry['name']}")
            output_files.append({
                "file_key": file_key,
                "file_name": entry["name"],
                "file_size": os.path.getsize(file_path),
                "duration": entry.get("duration"),
            })

        run_async(_save_slice_outputs(task_id, episode_id, output_files, mode))

        self.update_state(
            state="SUCCESS",
            meta={
                "progress": 100,
                "message": f"Slice completed: {len(output_files)} files",
                "output_files": output_files,
            },
        )

        return {
            "episode_id": episode_id,
            "output_count": len(output_files),
            "output_files": output_files,
        }

    except Exception as e:
        logger.error(f"Slice task failed: {e}")
        run_async(_fail_slice_task(task_id, str(e)))
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        raise
    finally:
        # Clean up temp files
        for p in (cutlist_path, intervals_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        # Clean up output directory
        if output_dir and os.path.isdir(output_dir):
            import shutil
            try:
                shutil.rmtree(output_dir)
            except OSError:
                pass
        # Clean up downloaded source video
        if downloaded_source_path and os.path.isfile(downloaded_source_path):
            try:
                os.unlink(downloaded_source_path)
            except OSError:
                pass


def _parse_engine_manifest(stdout: str, output_dir: str) -> list[dict]:
    """Parse OUTPUT:<name>:<duration> lines emitted by engine scripts."""
    entries = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("OUTPUT:"):
            continue
        parts = line.split(":", 3)
        if len(parts) < 3:
            continue
        name = parts[1]
        duration = float(parts[2]) if parts[2] else 0.0
        entries.append({
            "name": name,
            "duration": duration,
            "path": os.path.join(output_dir, name),
        })
    return entries


async def _save_autoclip_results(
    episode_id: str,
    autoclip_project_id: str,
    clips: list[dict],
    completed: bool,
):
    """Replace clip candidates for an episode with AutoClip results."""
    from sqlalchemy import select, delete
    from app.models.models import ClipCandidate, AutoClipProject, Episode

    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)

        await session.execute(
            delete(ClipCandidate).where(ClipCandidate.episode_id == eid)
        )
        for i, clip in enumerate(clips):
            start = clip.get("start_time")
            end = clip.get("end_time")
            if start is None or end is None:
                continue
            candidate = ClipCandidate(
                episode_id=eid,
                clip_index=clip.get("clip_index", i + 1),
                start_time=start,
                end_time=end,
                duration=clip.get("duration", max(0.0, float(end) - float(start))),
                title=clip.get("title"),
                content=clip.get("content"),
                outline=clip.get("outline"),
                score=clip.get("score"),
                recommend_reason=clip.get("recommend_reason"),
                status="pending",
            )
            session.add(candidate)

        proj_result = await session.execute(
            select(AutoClipProject).where(AutoClipProject.episode_id == eid)
        )
        proj = proj_result.scalar_one_or_none()
        if proj:
            proj.pipeline_status = "completed" if completed else "failed"
            proj.error_message = None
            proj.autoclip_project_id = autoclip_project_id

        episode_result = await session.execute(
            select(Episode).where(Episode.id == eid)
        )
        episode = episode_result.scalar_one_or_none()
        if episode:
            episode.status = "clips_detected"

        await session.commit()


async def _mark_autoclip_failed(episode_id: str, error: str):
    from sqlalchemy import select
    from app.models.models import AutoClipProject

    async with async_session_factory() as session:
        try:
            eid = uuid.UUID(episode_id)
        except ValueError:
            return
        result = await session.execute(
            select(AutoClipProject).where(AutoClipProject.episode_id == eid)
        )
        proj = result.scalar_one_or_none()
        if proj:
            proj.pipeline_status = "failed"
            proj.error_message = error[:2000]
            await session.commit()


async def _update_autoclip_run(
    episode_id: str,
    autoclip_project_id: Optional[str],
    status: str,
    progress: float,
    message: Optional[str] = None,
):
    """更新最近一条 AI 选点执行历史的状态/进度（供工作台历史展示）。"""
    from sqlalchemy import select
    from app.models.models import AutoClipRun

    async with async_session_factory() as session:
        try:
            eid = uuid.UUID(episode_id)
        except ValueError:
            return
        try:
            if autoclip_project_id:
                # 优先按项目 ID 精确匹配本次运行记录
                result = await session.execute(
                    select(AutoClipRun)
                    .where(
                        AutoClipRun.episode_id == eid,
                        AutoClipRun.autoclip_project_id == autoclip_project_id,
                    )
                    .order_by(AutoClipRun.created_at.desc())
                    .limit(1)
                )
                run = result.scalar_one_or_none()
            else:
                run = None
            if run is None:
                result = await session.execute(
                    select(AutoClipRun)
                    .where(AutoClipRun.episode_id == eid)
                    .order_by(AutoClipRun.created_at.desc())
                    .limit(1)
                )
                run = result.scalar_one_or_none()
        except Exception:
            run = None
        if run is None:
            # 兼容旧数据：没有历史记录时尝试补建一条
            run = AutoClipRun(
                episode_id=eid,
                autoclip_project_id=autoclip_project_id,
                status=status,
                progress=progress,
                message=message,
            )
            session.add(run)
        else:
            run.status = status
            run.progress = progress
            if message:
                run.message = message[:500]
            if status == "running" and run.started_at is None:
                run.started_at = datetime.utcnow()
            if status in ("completed", "failed"):
                run.completed_at = datetime.utcnow()
        await session.commit()


async def _save_detected_intervals(
    episode_id: str, intervals: list[dict], mode: str, config: dict
):
    """Save detected intervals to the database.

    只替换与本次检测同类型（interval_type）的旧结果，避免“水印”等无自动检测器
    的模式返回空列表时，把已保存的片尾字幕/静止画面结果一并清空。
    """
    from sqlalchemy import delete
    from app.models.models import DetectedInterval

    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)
        # 收集本次结果中出现的区间类型；若结果为空则不做删除（不覆盖其它类型）
        types_in_result = list({
            (interval_data.get("interval_type") or mode)
            for interval_data in intervals
            if interval_data.get("interval_type") or mode
        })
        if types_in_result:
            await session.execute(
                delete(DetectedInterval).where(
                    DetectedInterval.episode_id == eid,
                    DetectedInterval.source == "auto",
                    DetectedInterval.interval_type.in_(types_in_result),
                )
            )
        for interval_data in intervals:
            # 确保整型时间也写入（表字段为 Float，int 直接赋值在部分驱动下会丢精度/报错）
            try:
                start_time = (
                    float(interval_data.get("start_time"))
                    if interval_data.get("start_time") is not None
                    else None
                )
            except (TypeError, ValueError):
                start_time = None
            try:
                end_time = (
                    float(interval_data.get("end_time"))
                    if interval_data.get("end_time") is not None
                    else None
                )
            except (TypeError, ValueError):
                end_time = None
            try:
                confidence = (
                    float(interval_data.get("confidence"))
                    if interval_data.get("confidence") is not None
                    else None
                )
            except (TypeError, ValueError):
                confidence = None

            interval = DetectedInterval(
                episode_id=eid,
                interval_type=interval_data.get("interval_type") or mode,
                start_time=start_time,
                end_time=end_time,
                confidence=confidence,
                label=interval_data.get("label"),
                enabled=interval_data.get("enabled", True),
                source="auto",
                detection_config=config,
            )
            session.add(interval)
        await session.commit()


async def _update_episode_status(episode_id: str, status: str):
    from sqlalchemy import select
    from app.models.models import Episode

    async with async_session_factory() as session:
        try:
            eid = uuid.UUID(episode_id)
        except ValueError:
            return
        result = await session.execute(select(Episode).where(Episode.id == eid))
        episode = result.scalar_one_or_none()
        if episode:
            episode.status = status
            await session.commit()


async def _update_slice_task_progress(task_id: Optional[str], progress: float):
    if not task_id:
        return
    from sqlalchemy import select
    from app.models.models import SliceTask

    async with async_session_factory() as session:
        try:
            tid = uuid.UUID(task_id)
        except ValueError:
            return
        result = await session.execute(select(SliceTask).where(SliceTask.id == tid))
        task = result.scalar_one_or_none()
        if task:
            task.progress = progress
            task.status = "running"
            await session.commit()


async def _save_slice_outputs(
    task_id: Optional[str],
    episode_id: str,
    output_files: list[dict],
    mode: str,
):
    from sqlalchemy import select
    from app.models.models import SliceTask, SliceOutput, ClipCandidate, Episode

    async with async_session_factory() as session:
        tid = uuid.UUID(task_id) if task_id else None

        # Map outputs to accepted clip candidates by order.
        clips = []
        if tid is not None:
            clip_result = await session.execute(
                select(ClipCandidate)
                .where(
                    ClipCandidate.episode_id == uuid.UUID(episode_id),
                    ClipCandidate.status == "accepted",
                )
                .order_by(ClipCandidate.clip_index.asc())
            )
            clips = clip_result.scalars().all()

        # 幂等：任务已落库过输出则直接跳过，避免 Celery 重试导致重复输出
        if tid is not None:
            existing_result = await session.execute(
                select(SliceOutput).where(SliceOutput.task_id == tid)
            )
            if existing_result.scalars().first() is not None:
                task_result = await session.execute(
                    select(SliceTask).where(SliceTask.id == tid)
                )
                task = task_result.scalar_one_or_none()
                if task and task.status != "completed":
                    task.status = "completed"
                    task.progress = 100.0
                    task.output_count = len(output_files)
                    task.completed_at = datetime.utcnow()
                    task.error_message = None
                    await session.commit()
                return

        for i, out in enumerate(output_files):
            clip_id = clips[i].id if i < len(clips) else None
            session.add(SliceOutput(
                task_id=tid,
                clip_id=clip_id,
                file_key=out["file_key"],
                file_name=out["file_name"],
                file_size=out["file_size"],
                duration=out.get("duration"),
            ))

        if tid is not None:
            task_result = await session.execute(
                select(SliceTask).where(SliceTask.id == tid)
            )
            task = task_result.scalar_one_or_none()
            if task:
                task.status = "completed"
                task.progress = 100.0
                task.output_count = len(output_files)
                task.completed_at = datetime.utcnow()
                task.error_message = None

            # 切片输出落库后把剧集状态推进到 completed，让工作流步骤条走到“成品预览”
            episode_result = await session.execute(
                select(Episode).where(Episode.id == uuid.UUID(episode_id))
            )
            episode = episode_result.scalar_one_or_none()
            if episode and episode.status != "completed":
                episode.status = "completed"

        await session.commit()


async def _fail_slice_task(task_id: Optional[str], error: str):
    if not task_id:
        return
    from sqlalchemy import select
    from app.models.models import SliceTask

    async with async_session_factory() as session:
        try:
            tid = uuid.UUID(task_id)
        except ValueError:
            return
        result = await session.execute(select(SliceTask).where(SliceTask.id == tid))
        task = result.scalar_one_or_none()
        if task:
            task.status = "failed"
            task.error_message = error[:2000]
            task.completed_at = datetime.utcnow()
            await session.commit()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def task_publish_video(self, publish_task_id: str):
    """Execute video publishing via Playwright-based RPA."""
    from app.services.publish_service import get_publisher
    from app.services.minio_service import upload_file_from_path

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动发布任务…"})

    downloaded_video_path = None
    try:
        publish_task_data = run_async(_get_publish_task(publish_task_id))
        if not publish_task_data:
            raise Exception(f"Publish task {publish_task_id} not found")

        platform = publish_task_data["platform"]
        publisher = get_publisher(
            platform,
            chrome_debug_port=publish_task_data.get("chrome_debug_port", settings.CHROME_DEBUG_PORT),
            cookie_file=publish_task_data.get("cookie_file"),
            require_manual_confirm=publish_task_data.get("require_manual_confirm", True),
        )

        self.update_state(
            state="PROGRESS",
            meta={"progress": 20, "message": f"Publishing to {platform}..."},
        )

        video_path = run_async(_download_video_for_publish(publish_task_data["output_id"]))
        if not video_path:
            raise Exception("Failed to download video for publishing")
        downloaded_video_path = video_path

        result = run_async(publisher.publish(
            video_path=video_path,
            title=publish_task_data.get("title", ""),
            description=publish_task_data.get("description", ""),
            tags=publish_task_data.get("tags"),
            cover_file_key=publish_task_data.get("cover_file_key"),
            mini_program_link=publish_task_data.get("mini_program_link"),
        ))

        if result.get("status") == "pending_confirm" and result.get("success"):
            screenshot_key = None
            screenshot_path = result.get("screenshot_path")
            if screenshot_path and os.path.isfile(screenshot_path):
                screenshot_key = (
                    f"screenshots/{publish_task_id}/{os.path.basename(screenshot_path)}"
                )
                run_async(upload_file_from_path(
                    settings.MINIO_BUCKET_SCREENSHOTS,
                    screenshot_key,
                    screenshot_path,
                ))
            run_async(_update_publish_task_status(
                publish_task_id,
                status="pending_confirm",
                screenshot_key=screenshot_key,
            ))
            self.update_state(
                state="SUCCESS",
                meta={"progress": 100, "message": "Waiting for manual confirmation", "result": result},
            )
            return result

        if result.get("success"):
            run_async(_update_publish_task_status(
                publish_task_id,
                status="published",
                published_url=result.get("published_url"),
                published_id=result.get("published_id"),
                published_at=datetime.utcnow(),
            ))
            self.update_state(
                state="SUCCESS",
                meta={"progress": 100, "message": "Publish completed", "result": result},
            )
            return result

        raise Exception(result.get("error", "Unknown publish error"))

    except Exception as e:
        logger.error(f"Publish task failed: {e}")
        run_async(_update_publish_task_status(publish_task_id, status="failed", error_message=str(e)))
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        raise
    finally:
        # Clean up downloaded video file
        if downloaded_video_path and os.path.isfile(downloaded_video_path):
            try:
                os.unlink(downloaded_video_path)
            except OSError:
                pass


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def confirm_publish_worker(self, publish_task_id: str):
    """Confirm a pending publish by clicking publish in the already-prepared Chrome tab."""
    from app.services.publish_service import get_publisher

    self.update_state(state="STARTED", meta={"progress": 50, "message": "正在确认发布操作…"})
    try:
        publish_task_data = run_async(_get_publish_task(publish_task_id))
        if not publish_task_data:
            raise Exception(f"Publish task {publish_task_id} not found")

        publisher = get_publisher(
            publish_task_data["platform"],
            chrome_debug_port=publish_task_data.get("chrome_debug_port", settings.CHROME_DEBUG_PORT),
            require_manual_confirm=True,
        )
        result = run_async(publisher.confirm_publish())
        if not result.get("success"):
            raise Exception(result.get("error", "Confirm publish failed"))

        run_async(_update_publish_task_status(
            publish_task_id,
            status="published",
            published_url=result.get("published_url"),
            published_id=result.get("published_id"),
            published_at=datetime.utcnow(),
        ))
        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "Publish confirmed", "result": result},
        )
        return result
    except Exception as e:
        logger.error(f"Confirm publish failed: {e}")
        run_async(_update_publish_task_status(publish_task_id, status="failed", error_message=str(e)))
        self.update_state(state="FAILURE", meta={"progress": 0, "message": str(e)})
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=300)
def task_collect_metrics(self, account_id: Optional[str] = None, target_date: Optional[str] = None):
    """Periodic task for collecting and aggregating metrics data."""
    from datetime import date as date_type

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动数据采集任务…"})

    try:
        if target_date:
            collect_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        else:
            collect_date = date_type.today()

        account_uuid = uuid.UUID(account_id) if account_id else None
        funnel_data = run_async(_compute_funnel_snapshot(collect_date, account_uuid))

        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "Metrics collection completed", "funnel_data": funnel_data},
        )
        return {
            "date": collect_date.isoformat(),
            "account_id": account_id,
            "funnel_data": funnel_data,
        }
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        self.update_state(state="FAILURE", meta={"progress": 0, "message": str(e)})
        raise


async def _get_publish_task(publish_task_id: str) -> Optional[dict]:
    """Fetch publish task data from the database."""
    from app.models.models import PublishTask, PublishProfile
    from sqlalchemy import select

    async with async_session_factory() as session:
        task_uuid = uuid.UUID(publish_task_id)
        result = await session.execute(
            select(PublishTask).where(PublishTask.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None

        profile_result = await session.execute(
            select(PublishProfile).where(
                PublishProfile.platform == task.platform,
                PublishProfile.account_name == task.account_name,
            )
        )
        profile = profile_result.scalar_one_or_none()

        data = {
            "id": str(task.id),
            "output_id": str(task.output_id),
            "platform": task.platform,
            "account_name": task.account_name,
            "title": task.title,
            "description": task.description,
            "tags": task.tags,
            "cover_file_key": task.cover_file_key,
            "mini_program_link": task.mini_program_link,
            "require_manual_confirm": task.require_manual_confirm,
        }

        if profile:
            data["chrome_debug_port"] = profile.chrome_debug_port
            # RPA Cookie 解密（AES-256/Fernet 加密存储，仅在 Worker 内部使用）
            if profile.cookie_file:
                try:
                    from app.auth import decrypt_cookie
                    data["cookie_file"] = decrypt_cookie(profile.cookie_file)
                except Exception:
                    logger.warning("Failed to decrypt cookie for profile %s", profile.account_name)

        return data


async def _download_video_for_publish(output_id: str) -> Optional[str]:
    """Download the sliced video from MinIO to a local temp file for publishing."""
    from app.models.models import SliceOutput
    from app.services.minio_service import download_file
    from sqlalchemy import select

    async with async_session_factory() as session:
        out_uuid = uuid.UUID(output_id)
        result = await session.execute(
            select(SliceOutput).where(SliceOutput.id == out_uuid)
        )
        output = result.scalar_one_or_none()
        if not output or not output.file_key:
            return None

    data = await download_file(settings.MINIO_BUCKET_SLICED, output.file_key)
    if data is None:
        return None

    os.makedirs("/tmp/publish_videos", exist_ok=True)
    temp_path = f"/tmp/publish_videos/{output.id}.mp4"
    with open(temp_path, "wb") as f:
        f.write(data)
    return temp_path


async def _update_publish_task_status(
    publish_task_id: str,
    status: str = None,
    published_url: str = None,
    published_id: str = None,
    screenshot_key: str = None,
    error_message: str = None,
    celery_task_id: str = None,
    published_at: datetime = None,
):
    """Update publish task status in the database."""
    from app.models.models import PublishTask
    from sqlalchemy import select

    async with async_session_factory() as session:
        task_uuid = uuid.UUID(publish_task_id)
        result = await session.execute(
            select(PublishTask).where(PublishTask.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if not task:
            return

        if status:
            task.status = status
        if published_url:
            task.published_url = published_url
        if published_id:
            task.published_id = published_id
        if screenshot_key:
            task.screenshot_key = screenshot_key
        if error_message:
            task.error_message = error_message
        if celery_task_id:
            task.celery_task_id = celery_task_id
        if published_at:
            task.published_at = published_at
        task.updated_at = datetime.utcnow()

        await session.commit()


async def _compute_funnel_snapshot(collect_date, account_uuid) -> dict:
    """Compute and save a funnel snapshot for the given date."""
    from app.models.models import (
        VideoMetric, MiniProgramMetric, AdMetric, DramaMetric, FunnelSnapshot,
    )
    from sqlalchemy import func, and_

    async with async_session_factory() as session:
        video_filters = [VideoMetric.publish_date == collect_date]
        if account_uuid:
            video_filters.append(VideoMetric.account_id == account_uuid)

        video_result = await session.execute(
            select(
                func.coalesce(func.sum(VideoMetric.play_count), 0),
                func.coalesce(func.sum(VideoMetric.jump_click_count), 0),
            ).where(and_(*video_filters))
        )
        vrow = video_result.one()
        total_play = int(vrow[0] or 0)
        jump_click = int(vrow[1] or 0)

        mp_filters = [MiniProgramMetric.date == collect_date]
        if account_uuid:
            mp_filters.append(MiniProgramMetric.account_id == account_uuid)

        mp_result = await session.execute(
            select(func.coalesce(func.sum(MiniProgramMetric.uv), 0)).where(and_(*mp_filters))
        )
        mini_program_uv = int(mp_result.scalar() or 0)

        ad_filters = [AdMetric.date == collect_date]
        if account_uuid:
            ad_filters.append(AdMetric.account_id == account_uuid)

        ad_result = await session.execute(
            select(
                func.coalesce(func.sum(AdMetric.impression_count), 0),
                func.coalesce(func.sum(AdMetric.revenue), 0),
            ).where(and_(*ad_filters))
        )
        arow = ad_result.one()
        ad_impression = int(arow[0] or 0)
        revenue = float(arow[1] or 0)

        drama_filters = [DramaMetric.date == collect_date]
        if account_uuid:
            drama_filters.append(DramaMetric.account_id == account_uuid)
        drama_result = await session.execute(
            select(func.coalesce(func.sum(DramaMetric.uv), 0)).where(and_(*drama_filters))
        )
        drama_play_uv = int(drama_result.scalar() or 0)

        jump_rate = (jump_click / total_play * 100) if total_play > 0 else 0
        play_rate = (drama_play_uv / mini_program_uv * 100) if mini_program_uv > 0 else 0
        exposure_rate = (ad_impression / mini_program_uv * 100) if mini_program_uv > 0 else 0
        revenue_per_1000 = (revenue / total_play * 1000) if total_play > 0 else 0

        snapshot = FunnelSnapshot(
            date=collect_date,
            account_id=account_uuid,
            total_play=total_play,
            jump_click=jump_click,
            jump_rate=round(jump_rate, 2),
            mini_program_uv=mini_program_uv,
            drama_play_uv=drama_play_uv,
            play_rate=round(play_rate, 2),
            ad_exposure_uv=ad_impression,
            exposure_rate=round(exposure_rate, 2),
            revenue=round(revenue, 2),
            revenue_per_1000_play=round(revenue_per_1000, 2),
        )
        session.add(snapshot)
        await session.commit()

        return {
            "total_play": total_play,
            "jump_click": jump_click,
            "jump_rate": round(jump_rate, 2),
            "mini_program_uv": mini_program_uv,
            "drama_play_uv": drama_play_uv,
            "play_rate": round(play_rate, 2),
            "ad_impression": ad_impression,
            "exposure_rate": round(exposure_rate, 2),
            "revenue": round(revenue, 2),
            "revenue_per_1000_play": round(revenue_per_1000, 2),
        }


@celery_app.task(bind=True, max_retries=1, default_retry_delay=120)
def run_alert_check_task(self):
    """三期监控告警：周期检查告警规则并推送钉钉 Webhook."""
    from app.services.monitor_service import run_alert_checks

    try:
        result = run_async(run_alert_checks())
        logger.info("Alert check completed: %s", result)
        return result
    except Exception as e:
        logger.error(f"Alert check failed: {e}")
        self.update_state(state="FAILURE", meta={"progress": 0, "message": str(e)})
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=300)
def maintenance_daily_task(self):
    """三期性能优化：每日归档过期看板数据 + 清理临时文件 + 设置 MinIO 生命周期."""
    from app.services.maintenance_service import (
        archive_old_metrics,
        cleanup_temp_files,
        apply_minio_lifecycle,
    )

    results = {}
    try:
        results["archive"] = run_async(archive_old_metrics())
        results["cleanup"] = run_async(cleanup_temp_files())
        results["minio_lifecycle"] = run_async(apply_minio_lifecycle())
        logger.info("Maintenance daily task completed: %s", results)
        return results
    except Exception as e:
        logger.error(f"Maintenance daily task failed: {e}")
        self.update_state(state="FAILURE", meta={"progress": 0, "message": str(e)})
        raise


# ══════════════════════════════════════════════════════════════
# 去水印任务（v4）
# ══════════════════════════════════════════════════════════════

async def _update_watermark_video(
    video_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    output_file_key: Optional[str] = None,
    output_bucket: Optional[str] = None,
    output_file_size: Optional[int] = None,
    error_message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> None:
    """更新单条去水印视频的状态（供 Celery 任务在同步上下文中调用）。"""
    from sqlalchemy import select
    from app.models.models import WatermarkVideo

    async with async_session_factory() as session:
        try:
            vid = uuid.UUID(str(video_id))
        except ValueError:
            return
        result = await session.execute(
            select(WatermarkVideo).where(WatermarkVideo.id == vid)
        )
        video = result.scalar_one_or_none()
        if not video:
            return
        if status is not None:
            video.status = status
        if progress is not None:
            video.progress = progress
        if output_file_key is not None:
            video.output_file_key = output_file_key
        if output_bucket is not None:
            video.output_bucket = output_bucket
        if output_file_size is not None:
            video.output_file_size = output_file_size
        if error_message is not None:
            video.error_message = error_message
        if started_at is not None:
            video.started_at = started_at
        if completed_at is not None:
            video.completed_at = completed_at
        await session.commit()


async def _recalc_watermark_task(task_id: str) -> None:
    """根据子视频状态汇总刷新任务级进度/状态。"""
    from sqlalchemy import select
    from app.models.models import WatermarkTask, WatermarkVideo

    async with async_session_factory() as session:
        try:
            tid = uuid.UUID(str(task_id))
        except ValueError:
            return
        result = await session.execute(select(WatermarkTask).where(WatermarkTask.id == tid))
        task = result.scalar_one_or_none()
        if not task:
            return
        videos_result = await session.execute(
            select(WatermarkVideo).where(WatermarkVideo.task_id == tid)
        )
        videos = videos_result.scalars().all()
        if not videos:
            return

        total = len(videos)
        completed = sum(1 for v in videos if v.status == "completed")
        failed = sum(1 for v in videos if v.status == "failed")
        cancelled = sum(1 for v in videos if v.status == "cancelled")
        running = sum(1 for v in videos if v.status in ("pending", "running"))

        # 平均进度：完成 100、失败/取消 100、运行中取各自 progress
        avg = 0.0
        if total:
            for v in videos:
                if v.status == "completed":
                    avg += 100.0
                elif v.status in ("failed", "cancelled"):
                    avg += 100.0
                else:
                    avg += v.progress or 0.0
            avg = round(avg / total, 1)

        task.progress = avg
        task.total_count = total
        task.completed_count = completed
        task.failed_count = failed
        if running == 0:
            if cancelled == total:
                task.status = "cancelled"
                task.completed_at = task.completed_at or datetime.utcnow()
            elif failed == total or (failed > 0 and completed == 0):
                task.status = "failed"
                task.completed_at = task.completed_at or datetime.utcnow()
            else:
                task.status = "completed"
                task.completed_at = task.completed_at or datetime.utcnow()
        else:
            task.status = "running"
        await session.commit()


@celery_app.task(bind=True, max_retries=0)
def watermark_task(
    self,
    task_id: str,
    engine: str,
    options: Optional[dict] = None,
):
    """批量去水印异步任务：逐条下载源视频 → 调用引擎 → 上传结果 → 汇总进度。"""
    from app.engines.watermark_runner import run_watermark_engine, temp_video_path
    from app.models.models import WatermarkTask, WatermarkVideo
    from app.services.minio_service import (
        download_to_file,
        upload_file_from_path,
    )

    options = options or {}
    logger.info("Watermark task %s started (engine=%s)", task_id, engine)

    try:
        # 读取任务及其视频列表
        tid = uuid.UUID(str(task_id))
    except ValueError:
        logger.error("Invalid watermark task id: %s", task_id)
        return

    async def _load_videos():
        from sqlalchemy import select
        async with async_session_factory() as session:
            task_res = await session.execute(select(WatermarkTask).where(WatermarkTask.id == tid))
            task = task_res.scalar_one_or_none()
            if not task:
                return None, []
            videos_res = await session.execute(
                select(WatermarkVideo).where(WatermarkVideo.task_id == tid)
            )
            return task, videos_res.scalars().all()

    task, videos = run_async(_load_videos())
    if not task:
        logger.error("Watermark task %s not found", task_id)
        return

    if task.status == "cancelled":
        logger.info("Watermark task %s is cancelled, skip", task_id)
        return

    async def _mark_task_running():
        from sqlalchemy import select
        async with async_session_factory() as session:
            task_res = await session.execute(select(WatermarkTask).where(WatermarkTask.id == tid))
            t = task_res.scalar_one_or_none()
            if t:
                t.status = "running"
                t.started_at = t.started_at or datetime.utcnow()
                t.error_message = None
                await session.commit()

    run_async(_mark_task_running())

    tmp_dir = "/tmp/watermark"
    os.makedirs(tmp_dir, exist_ok=True)

    total = len(videos)
    for idx, video in enumerate(videos, start=1):
        vid = str(video.id)
        src_local = None
        out_local = None
        try:
            # 任务已取消/已删除 → 中断
            cur_task, _ = run_async(_load_videos())
            if not cur_task or cur_task.status == "cancelled":
                logger.info("Watermark task %s cancelled/deleted during processing", task_id)
                break

            run_async(_update_watermark_video(
                vid,
                status="running",
                progress=5.0,
                started_at=datetime.utcnow(),
                error_message=None,
            ))
            # 视频开始处理时立即刷新一次任务级汇总，让任务进度不再停留在 0%
            run_async(_recalc_watermark_task(task_id))

            src_local = temp_video_path("src")
            out_local = temp_video_path("out")

            # RAiW 要求输入文件带正确扩展名，且输出容器必须与源一致；
            # Seedance 引擎也依赖扩展名。从原始文件名提取扩展名并保持。
            src_ext = os.path.splitext(video.file_name or video.source_file_key)[1].lower()
            if not src_ext:
                src_ext = os.path.splitext(video.source_file_key)[1].lower()
            if not src_ext:
                src_ext = ".mp4"
            src_local = f"{src_local}{src_ext}"
            out_local = f"{out_local}{src_ext}"

            # 下载源视频
            ok = run_async(download_to_file(video.source_bucket or "watermark-raw", video.source_file_key, src_local))
            if not ok or not os.path.isfile(src_local):
                raise RuntimeError(f"下载源视频失败: {video.source_file_key}")

            # 引擎进度回调：同步上下文内更新数据库。
            # 注意：回调在 run_async 的事件循环内被同步调用，不能再用
            # run_async（会嵌套事件循环报错）。改为在已运行 loop 上调度协程。
            # 为避免高频写库（如逐帧修补），按进度变化节流：仅当进度提升≥5%或
            # 达到 100% 时落库。
            _last_written_progress = {"pct": 0}

            async def _persist_progress(pct: int):
                """视频进度落库后同步刷新任务级汇总，保证任务进度实时推进。"""
                await _update_watermark_video(vid, progress=pct)
                await _recalc_watermark_task(task_id)

            def _cb(pct: int, message: str = ""):
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": pct, "message": f"{video.file_name} {message}"},
                )
                if pct - _last_written_progress["pct"] < 5 and pct < 100:
                    return
                _last_written_progress["pct"] = pct
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(_persist_progress(pct))
                    else:
                        run_async(_persist_progress(pct))
                except RuntimeError:
                    pass

            # remove_mask 引擎按原始文件名匹配内置 ROI 表，这里用每条视频的真实文件名覆盖；
            # remove_ai / seedance / seedance_wm 也借 remove-mask 内置 ROI 经验库：
            # · remove_ai：RAiW 厂商检测失败时回退经验位置重试
            # · seedance / seedance_wm：自动检测基础上合并确认过的水印位置
            engine_options = options
            if engine in ("remove_mask", "remove_ai", "seedance", "seedance_wm"):
                engine_options = dict(options)
                engine_options["source_name"] = video.file_name or video.source_file_key

            returncode, stdout, stderr = run_async(
                run_watermark_engine(
                    engine,
                    src_local,
                    out_local,
                    engine_options,
                    progress_cb=_cb,
                )
            )

            if returncode != 0:
                detail = (stderr or stdout or "").strip()[-500:]
                raise RuntimeError(detail or f"去水印引擎执行失败 (exit={returncode})")

            if not os.path.isfile(out_local):
                raise RuntimeError("去水印引擎未生成输出文件")

            # 上传输出到 MinIO
            out_key = f"watermark/{task_id}/{vid}/{video.file_name}"
            uploaded = run_async(upload_file_from_path(
                settings.MINIO_BUCKET_WATERMARK,
                out_key,
                out_local,
                content_type="video/mp4",
            ))
            if not uploaded:
                raise RuntimeError("上传处理结果到 MinIO 失败")

            out_size = os.path.getsize(out_local)
            run_async(_update_watermark_video(
                vid,
                status="completed",
                progress=100.0,
                output_file_key=out_key,
                output_bucket=settings.MINIO_BUCKET_WATERMARK,
                output_file_size=out_size,
                completed_at=datetime.utcnow(),
            ))

        except Exception as e:
            logger.error("Watermark video %s failed: %s", vid, e)
            run_async(_update_watermark_video(
                vid,
                status="failed",
                error_message=str(e)[:1000],
                completed_at=datetime.utcnow(),
            ))
        finally:
            for p in (src_local, out_local):
                try:
                    if p and os.path.isfile(p):
                        os.unlink(p)
                except OSError:
                    pass

        # 每处理完一条刷新一次任务汇总
        run_async(_recalc_watermark_task(task_id))

    # 全部完成后，若仍有 pending（被取消跳过）则标记取消
    cur_task, cur_videos = run_async(_load_videos())
    pending = [v for v in cur_videos if v.status == "pending"]
    if pending and cur_task and cur_task.status == "cancelled":
        for v in pending:
            run_async(_update_watermark_video(
                str(v.id), status="cancelled", completed_at=datetime.utcnow()
            ))
        run_async(_recalc_watermark_task(task_id))

    run_async(_recalc_watermark_task(task_id))

    self.update_state(
        state="SUCCESS",
        meta={"progress": 100, "message": f"Watermark task {task_id} finished"},
    )
    logger.info("Watermark task %s finished", task_id)
