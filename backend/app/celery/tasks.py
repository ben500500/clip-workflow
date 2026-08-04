import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

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
        "app.celery.tasks.task_collect_metrics": {"queue": "metrics"},
    },
)

logger = logging.getLogger(__name__)


def run_async(coro):
    """Run an async function in a sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def autoclip_task(self, episode_id: str, autoclip_project_id: str, video_path: str, config: dict):
    """Execute the AutoClip pipeline as a Celery task.

    This task communicates with the AutoClip service and updates
    the database with progress and results.
    """
    from app.services.autoclip_service import (
        trigger_pipeline,
        get_pipeline_progress,
        get_clips,
    )

    self.update_state(state="STARTED", meta={"progress": 0, "message": "Starting AutoClip pipeline"})

    try:
        # Trigger the pipeline
        success = run_async(trigger_pipeline(autoclip_project_id))
        if not success:
            raise Exception("Failed to trigger AutoClip pipeline")

        # Poll for progress
        max_polls = 120  # 10 minutes at 5-second intervals
        for i in range(max_polls):
            progress = run_async(get_pipeline_progress(autoclip_project_id))
            if progress:
                pct = progress.get("progress", 0)
                msg = progress.get("message", "Processing...")
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": pct, "message": msg},
                )
                if progress.get("status") == "completed":
                    break
            else:
                # Estimate progress
                pct = min(int((i / max_polls) * 100), 99)
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": pct, "message": f"Pipeline step {i + 1}/{max_polls}"},
                )

            import time
            time.sleep(5)

        # Fetch results
        clips = run_async(get_clips(autoclip_project_id))
        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "AutoClip pipeline completed", "clips": clips},
        )
        return {"episode_id": episode_id, "clips_count": len(clips), "clips": clips}

    except Exception as e:
        logger.error(f"AutoClip task failed: {e}")
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        raise


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def detect_task(self, episode_id: str, video_path: str, mode: str, config: dict):
    """Execute interval detection as a Celery task."""
    from app.services.interval_service import detect_intervals

    self.update_state(state="STARTED", meta={"progress": 0, "message": "Starting interval detection"})

    try:
        self.update_state(
            state="PROGRESS",
            meta={"progress": 50, "message": f"Running {mode} detection..."},
        )

        intervals = run_async(detect_intervals(video_path, mode, config))

        # Save intervals to database
        run_async(_save_detected_intervals(episode_id, intervals, mode, config))

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


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def slice_task(
    self,
    episode_id: str,
    source_path: str,
    cutlist: str,
    intervals: str,
    mode: str,
    dedupe_config: Optional[dict] = None,
    task_id: Optional[str] = None,
):
    """Execute video slicing as a Celery task."""
    from app.services.slice_service import run_slice_scrub, run_slice_fast
    from app.utils.helpers import write_temp_file, ensure_dir

    self.update_state(state="STARTED", meta={"progress": 0, "message": "Starting slice task"})

    try:
        # Write cutlist and intervals to temp files
        cutlist_path = write_temp_file(cutlist, suffix=".txt")
        intervals_path = write_temp_file(intervals, suffix=".txt")

        # Create output directory
        output_dir = ensure_dir(f"/tmp/slice_outputs/{episode_id}/{self.request.id}")

        # Run the appropriate slice script
        for progress_pct in range(0, 100, 10):
            self.update_state(
                state="PROGRESS",
                meta={"progress": progress_pct, "message": f"Slicing... {progress_pct}%"},
            )
            import time
            time.sleep(1)  # Simulate progress (in production, parse ffmpeg output)

        if mode == "scrub":
            returncode, stdout, stderr = run_async(
                run_slice_scrub(source_path, cutlist_path, intervals_path, output_dir)
            )
        else:
            returncode, stdout, stderr = run_async(
                run_slice_fast(source_path, cutlist_path, output_dir, mode)
            )

        if returncode != 0:
            raise Exception(f"Slice script failed: {stderr}")

        # List output files
        output_files = []
        if os.path.isdir(output_dir):
            for f in os.listdir(output_dir):
                file_path = os.path.join(output_dir, f)
                if os.path.isfile(file_path):
                    output_files.append({
                        "file_name": f,
                        "file_path": file_path,
                        "file_size": os.path.getsize(file_path),
                    })

        self.update_state(
            state="SUCCESS",
            meta={
                "progress": 100,
                "message": f"Slice completed: {len(output_files)} files",
                "output_files": output_files,
            },
        )

        # Clean up temp files
        try:
            os.unlink(cutlist_path)
            os.unlink(intervals_path)
        except OSError:
            pass

        return {
            "episode_id": episode_id,
            "output_count": len(output_files),
            "output_files": output_files,
        }

    except Exception as e:
        logger.error(f"Slice task failed: {e}")
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        raise


async def _save_detected_intervals(
    episode_id: str, intervals: list[dict], mode: str, config: dict
):
    """Save detected intervals to the database."""
    from app.database import async_session_factory
    from app.models.models import DetectedInterval

    async with async_session_factory() as session:
        for interval_data in intervals:
            interval = DetectedInterval(
                episode_id=episode_id,
                interval_type=interval_data.get("interval_type", mode),
                start_time=interval_data.get("start_time"),
                end_time=interval_data.get("end_time"),
                confidence=interval_data.get("confidence"),
                label=interval_data.get("label"),
                enabled=interval_data.get("enabled", True),
                source=interval_data.get("source", "auto"),
                detection_config=config,
            )
            session.add(interval)
        await session.commit()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def task_publish_video(self, publish_task_id: str):
    """
    Execute video publishing as an async Celery task.

    Uses Playwright-based RPA to upload video to the target platform.
    Supports screenshot-based manual confirmation workflow.
    """
    from app.services.publish_service import get_publisher

    self.update_state(state="STARTED", meta={"progress": 0, "message": "Starting publish task"})

    try:
        # Fetch publish task from database
        publish_task_data = run_async(_get_publish_task(publish_task_id))
        if not publish_task_data:
            raise Exception(f"Publish task {publish_task_id} not found")

        # Get the appropriate publisher
        platform = publish_task_data["platform"]
        publisher = get_publisher(
            platform,
            chrome_debug_port=publish_task_data.get("chrome_debug_port", 9222),
            require_manual_confirm=publish_task_data.get("require_manual_confirm", True),
        )

        self.update_state(
            state="PROGRESS",
            meta={"progress": 20, "message": f"Publishing to {platform}..."},
        )

        # Download video from MinIO
        video_path = run_async(_download_video_for_publish(publish_task_data["output_id"]))
        if not video_path:
            raise Exception("Failed to download video for publishing")

        # Execute publish
        result = run_async(publisher.publish(
            video_path=video_path,
            title=publish_task_data.get("title", ""),
            description=publish_task_data.get("description", ""),
            tags=publish_task_data.get("tags"),
            cover_file_key=publish_task_data.get("cover_file_key"),
            mini_program_link=publish_task_data.get("mini_program_link"),
        ))

        # Update task status in database
        run_async(_update_publish_task_status(
            publish_task_id,
            status="pending_confirm" if result.get("status") == "pending_confirm" else "published",
            published_url=result.get("published_url"),
            published_id=result.get("published_id"),
            screenshot_key=result.get("screenshot_path"),
            error_message=result.get("error"),
        ))

        if result.get("success"):
            self.update_state(
                state="SUCCESS",
                meta={
                    "progress": 100,
                    "message": "Publish completed",
                    "result": result,
                },
            )
            return result
        else:
            raise Exception(result.get("error", "Unknown publish error"))

    except Exception as e:
        logger.error(f"Publish task failed: {e}")
        run_async(_update_publish_task_status(
            publish_task_id,
            status="failed",
            error_message=str(e),
        ))
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=300)
def task_collect_metrics(self, account_id: Optional[str] = None, target_date: Optional[str] = None):
    """
    Periodic task for collecting and aggregating metrics data.

    Computes funnel snapshots, aggregates daily metrics, and updates
    the dashboard data.
    """
    from datetime import date as date_type
    from app.models.models import (
        VideoMetric, MiniProgramMetric, AdMetric, FunnelSnapshot,
    )
    from sqlalchemy import func, and_

    self.update_state(state="STARTED", meta={"progress": 0, "message": "Starting metrics collection"})

    try:
        if target_date:
            collect_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        else:
            collect_date = date_type.today()

        account_uuid = uuid.UUID(account_id) if account_id else None

        # Compute funnel snapshot
        funnel_data = run_async(_compute_funnel_snapshot(collect_date, account_uuid))

        self.update_state(
            state="SUCCESS",
            meta={
                "progress": 100,
                "message": "Metrics collection completed",
                "funnel_data": funnel_data,
            },
        )
        return {
            "date": collect_date.isoformat(),
            "account_id": account_id,
            "funnel_data": funnel_data,
        }

    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        self.update_state(
            state="FAILURE",
            meta={"progress": 0, "message": str(e)},
        )
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

        # Try to get profile settings
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
    """Download video file from MinIO for publishing."""
    from app.models.models import SliceOutput
    from sqlalchemy import select

    async with async_session_factory() as session:
        out_uuid = uuid.UUID(output_id)
        result = await session.execute(
            select(SliceOutput).where(SliceOutput.id == out_uuid)
        )
        output = result.scalar_one_or_none()
        if not output or not output.file_key:
            return None

        # In production, download from MinIO
        # For now, return a placeholder path
        temp_path = f"/tmp/publish_videos/{output.file_key}"
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        return temp_path


async def _update_publish_task_status(
    publish_task_id: str,
    status: str = None,
    published_url: str = None,
    published_id: str = None,
    screenshot_key: str = None,
    error_message: str = None,
    celery_task_id: str = None,
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
        task.updated_at = datetime.utcnow()

        await session.commit()


async def _compute_funnel_snapshot(collect_date, account_uuid) -> dict:
    """Compute and save a funnel snapshot for the given date."""
    from app.models.models import (
        VideoMetric, MiniProgramMetric, AdMetric, FunnelSnapshot,
    )
    from sqlalchemy import func, and_, select

    async with async_session_factory() as session:
        # Aggregate video metrics
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

        # Aggregate mini program metrics
        mp_filters = [MiniProgramMetric.date == collect_date]
        if account_uuid:
            mp_filters.append(MiniProgramMetric.account_id == account_uuid)

        mp_result = await session.execute(
            select(func.coalesce(func.sum(MiniProgramMetric.uv), 0)).where(and_(*mp_filters))
        )
        mini_program_uv = int(mp_result.scalar() or 0)

        # Aggregate ad metrics
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

        # Compute rates
        jump_rate = (jump_click / total_play * 100) if total_play > 0 else 0
        exposure_rate = (ad_impression / mini_program_uv * 100) if mini_program_uv > 0 else 0
        revenue_per_1000 = (revenue / total_play * 1000) if total_play > 0 else 0

        # Save snapshot
        snapshot = FunnelSnapshot(
            date=collect_date,
            account_id=account_uuid,
            total_play=total_play,
            jump_click=jump_click,
            jump_rate=round(jump_rate, 2),
            mini_program_uv=mini_program_uv,
            drama_play_uv=0,
            play_rate=0,
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
            "ad_impression": ad_impression,
            "exposure_rate": round(exposure_rate, 2),
            "revenue": round(revenue, 2),
            "revenue_per_1000_play": round(revenue_per_1000, 2),
        }