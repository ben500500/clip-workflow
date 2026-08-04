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
        "default": {"exchange": "default"},
    },
    task_routes={
        "app.celery.tasks.autoclip_task": {"queue": "video_processing"},
        "app.celery.tasks.detect_task": {"queue": "video_processing"},
        "app.celery.tasks.slice_task": {"queue": "video_processing"},
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