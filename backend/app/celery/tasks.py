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
    },
    beat_schedule={
        "collect-metrics-daily": {
            "task": "app.celery.tasks.task_collect_metrics",
            "schedule": crontab(hour=0, minute=30),
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


async def _ensure_source_video(source_path: Optional[str], source_file_key: Optional[str]) -> Optional[str]:
    """Return a local path for the source video, downloading from MinIO if needed."""
    if source_path and os.path.isfile(source_path):
        return source_path
    if not source_file_key:
        return source_path
    from app.services.minio_service import download_to_file

    local_path = f"/tmp/source_videos/{uuid.uuid4().hex}_{os.path.basename(source_file_key)}"
    ok = await download_to_file(settings.MINIO_BUCKET_RAW, source_file_key, local_path)
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

        clips = run_async(get_clips(autoclip_project_id))
        run_async(_save_autoclip_results(episode_id, autoclip_project_id, clips, completed))

        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "AutoClip pipeline completed", "clips": clips},
        )
        return {"episode_id": episode_id, "clips_count": len(clips), "clips": clips}

    except Exception as e:
        logger.error(f"AutoClip task failed: {e}")
        run_async(_mark_autoclip_failed(episode_id, str(e)))
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
def detect_task(self, episode_id: str, video_path: str, mode: str, config: dict, source_file_key: Optional[str] = None):
    """Execute interval detection as a Celery task."""
    from app.services.interval_service import detect_intervals

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动区间检测任务…"})

    downloaded_video_path = None
    try:
        video_path = run_async(_ensure_source_video(video_path, source_file_key))
        if not video_path:
            raise FileNotFoundError(f"Source video not found: {video_path}")
        downloaded_video_path = video_path

        self.update_state(
            state="PROGRESS",
            meta={"progress": 50, "message": f"Running {mode} detection..."},
        )

        intervals = run_async(detect_intervals(video_path, mode, config))

        run_async(_save_detected_intervals(episode_id, intervals, mode, config))
        run_async(_update_episode_status(episode_id, "intervals_detected"))

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
        raise
    finally:
        # Clean up downloaded source video
        if downloaded_video_path and os.path.isfile(downloaded_video_path):
            try:
                os.unlink(downloaded_video_path)
            except OSError:
                pass


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
):
    """Execute video slicing, upload outputs to MinIO and persist SliceOutput rows."""
    from app.services.slice_service import run_slice_scrub, run_slice_fast
    from app.services.minio_service import upload_file_from_path
    from app.utils.helpers import write_temp_file, ensure_dir

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动切片任务…"})

    downloaded_source_path = None
    output_dir = None
    cutlist_path = None
    intervals_path = None
    try:
        source_path = run_async(_ensure_source_video(source_path, source_file_key))
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
            await session.commit()


async def _save_detected_intervals(
    episode_id: str, intervals: list[dict], mode: str, config: dict
):
    """Save detected intervals to the database."""
    from sqlalchemy import delete
    from app.models.models import DetectedInterval

    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)
        # 同一 episode 同类型检测只保留最新一轮结果
        await session.execute(
            delete(DetectedInterval).where(
                DetectedInterval.episode_id == eid,
                DetectedInterval.source == "auto",
            )
        )
        for interval_data in intervals:
            interval = DetectedInterval(
                episode_id=eid,
                interval_type=interval_data.get("interval_type", mode),
                start_time=interval_data.get("start_time"),
                end_time=interval_data.get("end_time"),
                confidence=interval_data.get("confidence"),
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
    from app.models.models import SliceTask, SliceOutput, ClipCandidate

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
