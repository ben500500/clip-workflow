"""Remotion 高光混剪增强 Celery 任务。

任务：
- run_remotion_mix_task：对开启「混剪增强」的切片任务，在独立 remotion 队列由
  remotion-worker 容器消费，调用 Remotion render.js 做片头/片尾/转场/动态字幕包装，
  渲染成功后上传 MinIO 并回写 SliceTask.remotion_output_file_key + remotion_status=done。

护栏：
- 未开启（remotion_mix_config 为空）时任务直接返回（零侵入）；
- 渲染失败回写 remotion_status=failed + error_message，并按 Celery retry 机制重试；
- 生产安全开关 REMOTION_ENABLED 关闭时直接跳过（默认关闭，需显式开启）。
"""
import logging

from sqlalchemy import select

from app.celery.tasks import celery_app, run_async
from app.config import settings
from app.database import async_session_factory
from app.services.minio_service import ensure_bucket, upload_file_from_path

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_remotion_mix_task(self, slice_task_id: str):
    """对指定切片任务执行 Remotion 高光混剪增强渲染，并回写渲染结果状态。

    成功：更新 SliceTask.remotion_output_file_key + remotion_status="done"；
    失败：更新 remotion_status="failed" + error_message，并按重试策略 retry。
    """
    if not settings.REMOTION_ENABLED:
        logger.info("REMOTION_ENABLED 关闭，跳过 Remotion 渲染 slice_task=%s", slice_task_id)
        return {"skipped": True, "reason": "REMOTION_ENABLED disabled"}

    try:
        result = run_async(_run_remotion_mix_flow(slice_task_id))
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result
    except Exception as e:
        logger.exception("run_remotion_mix_task failed slice_task=%s: %s", slice_task_id, e)
        try:
            run_async(_mark_remotion_failed(slice_task_id, f"render failed: {e}"))
        except Exception as mark_e:
            logger.error("_mark_remotion_failed slice_task=%s failed: %s", slice_task_id, mark_e)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {"ok": False, "error": str(e), "retries_exhausted": True}


async def _run_remotion_mix_flow(slice_task_id: str) -> dict:
    """异步执行完整渲染流水线（读任务 → 渲染 → 上传 → 回写）。"""
    from app.models.models import SliceTask
    from app.services.remotion_renderer import render_highlight_mix

    async with async_session_factory() as db:
        task = (
            await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
        ).scalar_one_or_none()
        if not task:
            return {"ok": False, "error": f"slice_task 不存在: {slice_task_id}"}

        config = task.remotion_mix_config
        if not config:
            return {"ok": True, "skipped": True, "reason": "remotion_mix_config 为空"}

        task.remotion_status = "rendering"
        task.error_message = None
        await db.flush()

    # 渲染（独立子进程，耗时；在会话外执行，避免长事务）
    ok, out = await render_highlight_mix(
        task, config,
        source_file_key=getattr(task, "source_file_key", None),
        source_bucket=getattr(task, "source_bucket", None),
    )
    if not ok:
        return {"ok": False, "error": out}

    # 上传渲染产物到 MinIO sliced 桶
    await ensure_bucket(settings.MINIO_BUCKET_SLICED)
    output_file_key = f"{settings.REMOTION_OUTPUT_PREFIX}/{slice_task_id}.mp4"
    uploaded = await upload_file_from_path(
        settings.MINIO_BUCKET_SLICED, output_file_key, out
    )
    if not uploaded:
        return {"ok": False, "error": "上传 Remotion 渲染产物到 MinIO 失败"}

    async with async_session_factory() as db:
        task = (
            await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
        ).scalar_one_or_none()
        if task:
            task.remotion_output_file_key = output_file_key
            task.remotion_status = "done"
            task.error_message = None
            await db.commit()

    return {"ok": True, "output_file_key": output_file_key}


async def _mark_remotion_failed(slice_task_id: str, error: str) -> None:
    """失败回写：更新 remotion_status=failed + error_message。"""
    from app.models.models import SliceTask

    async with async_session_factory() as db:
        task = (
            await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
        ).scalar_one_or_none()
        if task:
            task.remotion_status = "failed"
            task.error_message = (error or "")[:1000]
            await db.commit()


@celery_app.task(bind=True)
def remotion_stale_recovery_task(self):
    """周期巡检：回写 stuck 在 rendering 的超时 Remotion 渲染任务为 failed。

    兜底场景：Remotion worker 崩溃 / 节点重启 / 渲染进程被 kill，任务卡在
    rendering 状态不收敛。此守护任务（beat 调度，参考 video_processing 队列守护）
    把超过 REMOTION_RENDER_TIMEOUT_SECONDS 仍 rendering 的任务置 failed，供人工重试。
    """
    from datetime import datetime, timezone
    from sqlalchemy import text

    if not settings.REMOTION_ENABLED:
        return {"skipped": True, "reason": "REMOTION_ENABLED disabled"}

    timeout = settings.REMOTION_RENDER_TIMEOUT_SECONDS
    try:
        affected = run_async(_recover_stale_remotion(timeout))
        logger.info("remotion stale recovery: %s 条超时任务已回写 failed", affected)
        return {"ok": True, "affected": affected}
    except Exception as e:
        logger.exception("remotion stale recovery failed: %s", e)
        return {"ok": False, "error": str(e)}


async def _recover_stale_remotion(timeout_seconds: int) -> int:
    """把 stuck 在 rendering 且超过超时阈值的 SliceTask 回写 remotion_status=failed。"""
    from sqlalchemy import text

    # 用 started_at 判定：rendering 状态且 started_at 超过超时阈值（无 started_at 时按 created_at）
    async with async_session_factory() as db:
        result = await db.execute(
            text(
                """
                UPDATE slice_tasks
                SET remotion_status='failed',
                    error_message=COALESCE(error_message, '') || '; Remotion 渲染超时，由守护任务回写失败'
                WHERE remotion_status='rendering'
                  AND (
                    (started_at IS NOT NULL AND started_at < now() - make_interval(secs => :to))
                    OR (started_at IS NULL AND created_at < now() - make_interval(secs => :to))
                  )
                """
            ),
            {"to": timeout_seconds},
        )
        await db.commit()
        return result.rowcount or 0
