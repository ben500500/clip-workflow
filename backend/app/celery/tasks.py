import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import List, Optional

from celery import Celery
from celery.schedules import crontab

from sqlalchemy import select

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
    result_expires=43200,          # results expire after 12h（收紧防 Redis celery-task-meta 堆积）
    broker_connection_retry_on_startup=True,
    broker_heartbeat=30,
    task_queues={
        "video_processing": {"exchange": "video_processing"},
        "publish": {"exchange": "publish"},
        "metrics": {"exchange": "metrics"},
        "wechat_dl": {"exchange": "wechat_dl"},
        "lan_source": {"exchange": "lan_source"},
        # 解耦模式 AI 选点消费者独立队列：重计算 + 长轮询，避免与串行批处理抢占 default
        "selection": {"exchange": "selection"},
        # 变体生成独立队列：ffmpeg 重计算 + 撞车重试，避免被 batch 任务挤占 default 8 小时（#274 A2）
        "variant": {"exchange": "variant"},
        "default": {"exchange": "default"},
    },
    task_routes={
        "app.celery.tasks.autoclip_task": {"queue": "selection"},
        "app.celery.tasks.detect_task": {"queue": "video_processing"},
        "app.celery.tasks.slice_task": {"queue": "video_processing"},
        "app.celery.tasks.task_publish_video": {"queue": "publish"},
        "app.celery.tasks.confirm_publish_worker": {"queue": "publish"},
        "app.celery.tasks.task_collect_metrics": {"queue": "metrics"},
        "app.celery.tasks.watermark_task": {"queue": "video_processing"},
        "app.celery.tasks.check_cookie_status": {"queue": "publish"},
        # 解耦模式选点消费者：独立 selection 队列（重计算 + 长轮询，避免抢占 default）
        "app.celery.tasks.batch_selection_consumer": {"queue": "selection"},
        "app.celery.tasks.doubao_generate_task": {"queue": "publish"},
        # Seedance 官方 API 直连出片(HTTP 直连,无浏览器;复用 publish 队列即可,
        # 不依赖 rpa_worker,普通 worker 即可消费)
        "app.celery.tasks.seedance_generate_task": {"queue": "publish"},
        # 视频号素材导入下载（wechat_download）：独立 wechat_dl 队列（可剥离形态 B 单独拉起）
        "wechat_dl.download": {"queue": "wechat_dl"},
        # 局域网获取剧集导入（lan_source）：独立 lan_source 队列
        "lan_source.import_episodes": {"queue": "lan_source"},
        # 变体生成/指纹复核（#274 A2）：独立 variant 队列，独占 worker-variant 消费，
        # 不再与 batch/slice 抢 default/video_processing，杜绝排队 8 小时 + 超时被杀。
        "app.celery.variant_tasks.generate_variants_task": {"queue": "variant"},
        "app.celery.variant_tasks.verify_variant_fingerprint_task": {"queue": "variant"},
    },
    beat_schedule={
        "collect-metrics-daily": {
            "task": "app.celery.tasks.task_collect_metrics",
            "schedule": crontab(hour=0, minute=30),
        },
        # 三期监控告警:周期检查告警规则并推送钉钉
        "alert-check-periodic": {
            "task": "app.celery.tasks.run_alert_check_task",
            "schedule": settings.ALERT_CHECK_INTERVAL_SECONDS,
        },
        # 三期性能优化:每日归档过期看板数据 + 清理临时文件
        "maintenance-daily": {
            "task": "app.celery.tasks.maintenance_daily_task",
            "schedule": crontab(hour=3, minute=0),
        },
        # 发布登录态巡检:定期检查视频号/抖音/快手登录态是否失效,
        # 失效时记录到日志并保留任务记录,供运维/发布专员发现后重新扫码
        "publish-cookie-check": {
            "task": "app.celery.tasks.check_cookie_status",
            "schedule": settings.COOKIE_CHECK_INTERVAL_SECONDS,
        },
        # 多运营者(R15/R12):周期同步启用 profile 到 Redis 路由表 + 秒级探活失效闭环
        "multi-operator-profile-sync": {
            "task": "app.celery.tasks.sync_multi_operator_profiles",
            "schedule": 60.0,
        },
        "multi-operator-route-watch": {
            "task": "app.celery.tasks.watch_multi_operator_routes",
            "schedule": 10.0,
        },
        # 解耦模式（AI 选点 × 切片解耦）：切片投递守护轮询已选点池
        "batch-slice-dispatch-periodic": {
            "task": "app.celery.tasks.batch_slice_dispatch",
            "schedule": settings.BATCH_DISPATCH_INTERVAL_SECONDS,
        },
        # 解耦模式：批次状态聚合器
        "batch-aggregate-periodic": {
            "task": "app.celery.tasks.batch_aggregate",
            "schedule": settings.BATCH_AGGREGATE_INTERVAL_SECONDS,
        },
        # 解耦模式：终态回收器（切片终态回填 + 成功才删源视频，复用聚合节奏）
        "batch-finalize-periodic": {
            "task": "app.celery.tasks.batch_slice_finalize",
            "schedule": settings.BATCH_AGGREGATE_INTERVAL_SECONDS,
        },
        # 定时发布（R99）：每分钟扫描到期的预约发布任务并投递 publish 队列
        "publish-schedule-dispatcher": {
            "task": "app.celery.tasks.publish_schedule_dispatcher",
            "schedule": 60.0,
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

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动 AutoClip 选点任务..."})
    run_async(_update_autoclip_run(episode_id, autoclip_project_id, "running", 5, "选点任务运行中,正在分析视频..."))

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

        success = run_async(trigger_pipeline(autoclip_project_id, config=config))
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
                # AutoClip 服务重启会丢失内存态项目,连续失败则提前失败,
                # 避免占用单 worker 空转 10 分钟。
                consecutive_failures += 1
                if consecutive_failures >= 6:
                    raise RuntimeError(
                        "AutoClip 项目状态连续查询失败(服务可能已重启导致项目丢失),请重新触发选点"
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
            # P1-5 修复：用 is not None 判断而非 `or`（falsy 陷阱）。
            # 显式传 0 表示"最低分不限/时长不限"，不再被 `or 60` / `or 0` 回退吞掉。
            min_score=float(config.get("min_score_threshold")) if config.get("min_score_threshold") is not None else 50.0,
            # P1 修复（#228）：min_duration/max_duration 不再作为硬过滤传给引擎 /api/v1/clips。
            # 引擎产出的高光片段天然 50~145s，若把用户配置的 max_duration=30 作为硬过滤，
            # 会把全部候选砍成 0。duration 仅作引擎 step2 定位参考（经 trigger_pipeline 的 config 下发），
            # 此处统一传 0（不限），保证引擎把候选高光片段全部返回。
            min_duration=0.0,
            max_duration=0.0,
        ))
        run_async(_save_autoclip_results(episode_id, autoclip_project_id, clips, completed, config))
        run_async(_update_autoclip_run(
            episode_id, autoclip_project_id,
            "completed" if completed else "failed",
            100.0 if completed else 0.0,
            f"选点完成,共生成 {len(clips)} 个候选片段" if completed else "选点未完成,请检查 AutoClip 服务",
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
        raise
    finally:
        # Clean up downloaded source video
        if downloaded_video_path and os.path.isfile(downloaded_video_path):
            try:
                os.unlink(downloaded_video_path)
            except OSError:
                pass


@celery_app.task(bind=True, max_retries=0)
def batch_slice_task(self, batch_id: str):
    """批量切片工作流入口：按 pipeline_mode 分流（serial 串行 / decoupled 解耦）。

    编排逻辑见 app.services.batch_slice_service.run_batch。
    由于该任务会长时间阻塞并轮询 autoclip/slice 子任务,放到 default 队列执行。
    """
    from app.services.batch_slice_service import run_batch
    self.update_state(state="STARTED", meta={"batch_id": batch_id})
    try:
        run_async(run_batch(batch_id))
    except Exception as e:
        logger.error("批量切片任务异常 batch=%s: %s", batch_id, e)
        from app.services.batch_slice_service import _update_batch
        run_async(_update_batch(batch_id, status="failed", error_message=str(e)))
        raise


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def batch_selection_consumer(self, batch_id: str, item_id: str, episode_id: str):
    """解耦模式选点消费者：对单个剧集执行 AI 选点 + 自动审核，完成后标记为「已选点待切片」。

    处理完成后写入「已选点池」（item.phase=autoclip_done），供切片投递守护消费。
    失败时不置 item 终态、由 process_selection 向上抛出，这里经 self.retry() 交由
    Celery 重试接管（max_retries=3），重试耗尽才真正失败，避免 item 永久卡死。
    """
    from app.services.batch_decoupled_service import process_selection
    try:
        run_async(process_selection(batch_id, item_id, episode_id))
    except Exception as e:
        logger.error("选点消费者异常 batch=%s item=%s: %s", batch_id, item_id, e)
        # 让 Celery 重试接管（默认延时 10s，最多重试 3 次），而非直接失败。
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=0)
def batch_slice_dispatch(self):
    """解耦模式切片投递守护：扫描已选点池（autoclip_done）并投递切片任务。

    复用 run_slice → publish_slice_task 入 Redis Stream，由 Go slice-worker 消费。
    切片终态由独立 beat 任务 batch_slice_finalize 扫描回收，不阻塞本投递守护。
    """
    from app.services.batch_decoupled_service import dispatch_ready_slices
    try:
        run_async(dispatch_ready_slices())
    except Exception as e:
        logger.error("切片投递守护异常: %s", e)
        raise


@celery_app.task(bind=True, max_retries=0)
def batch_slice_finalize(self):
    """解耦模式终态回收器：扫描 phase='slicing' 的 item，按 slice_task_id 查 SliceTask 终态回填。

    成功回填 completed 并仅在成功时删除源视频（_delete_source）；失败回填 failed。
    与 batch_slice_dispatch 解耦，独立 beat 周期轮询，不阻塞切片投递、完全幂等。
    """
    from app.services.batch_decoupled_service import finalize_slices
    try:
        run_async(finalize_slices())
    except Exception as e:
        logger.error("终态回收器异常: %s", e)
        raise


@celery_app.task(bind=True, max_retries=0)
def batch_aggregate(self):
    """解耦模式状态聚合器：按批次维度聚合各剧集终态，回填 BatchSlice 汇总。
    """
    from app.services.batch_decoupled_service import aggregate_batches
    try:
        run_async(aggregate_batches())
    except Exception as e:
        logger.error("状态聚合器异常: %s", e)
        raise


@celery_app.task(bind=True, max_retries=0)
def publish_schedule_dispatcher(self):
    """定时发布（R99）调度守护：扫描已到期（scheduled_at <= now）的预约发布任务并投递。

    每分钟由 beat 触发一次：
    - 命中 scheduled_at <= now 且 status='scheduled' 的任务；
    - 置为 pending 并触发 task_publish_video.delay()（与立即发布同一入口，复用完整链路）。
    - 加行锁防并发（同一任务不会被多次投递）。
    """
    from datetime import datetime as _dt
    from app.models.models import PublishTask

    async def _dispatch_due():
        from sqlalchemy import select as _sel
        from app.api.publish_common import _serialize_publish_task  # noqa: F401  (仅为确保路由表加载)
        async with async_session_factory() as session:
            now = _dt.utcnow()
            due = (
                await session.execute(
                    _sel(PublishTask)
                    .where(
                        PublishTask.scheduled_at <= now,
                        PublishTask.status == "scheduled",
                    )
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            ).scalars().all()
            dispatched = 0
            for task in due:
                task.status = "pending"
                task.scheduled_at = None  # 已投递，清除预约时间避免重复命中
                await session.flush()
            await session.commit()
            return [(str(t.id), str(t.output_id)) for t in due], len(due)

    try:
        due_tasks, count = run_async(_dispatch_due())
        for tid, _ in due_tasks:
            try:
                from app.celery.tasks import task_publish_video
                celery_result = task_publish_video.delay(tid)
                # 回写 celery_task_id（不覆盖 status，worker 可能已开始更新）
                async def _write_ckid(task_id: str, ckid: str):
                    async with async_session_factory() as session:
                        from app.models.models import PublishTask as _PT
                        t = (
                            await session.execute(_sel(_PT).where(_PT.id == task_id))
                        ).scalar_one_or_none()
                        if t:
                            t.celery_task_id = ckid
                            await session.commit()
                run_async(_write_ckid(tid, celery_result.id))
            except Exception as e:
                logger.error(f"定时发布投递失败 task={tid}: {e}", exc_info=True)
        if count:
            logger.info("定时发布调度：本周期投递 %d 个到点任务", count)
    except Exception as e:
        logger.error("定时发布调度守护异常: %s", e)
        raise


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def detect_task(self, episode_id: str, video_path: str, mode: str, config: dict, source_file_key: Optional[str] = None, task_id: Optional[str] = None):
    """Execute interval detection as a Celery task."""
    from app.services.interval_service import detect_intervals

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动区间检测任务..."})

    # 检测任务记录到 slice_tasks 表(mode 前缀 detect_),供 /intervals/progress 接口查询进度。
    # 优先使用 API 层预创建的记录,避免提交后轮询窗口内查不到进度。
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
            meta={"progress": 20, "message": f"正在分析视频({mode} 模式)..."},
        )
        if detect_task_id:
            run_async(_update_detect_task_progress(detect_task_id, 20, "running"))

        async def _run():
            return await detect_intervals(video_path, mode, config)

        intervals = run_async(_run())

        run_async(_save_detected_intervals(episode_id, intervals, mode, config))
        run_async(_update_episode_status(episode_id, "intervals_detected"))

        # 数据落库后再标记完成,避免前端提前看到 completed 但结果尚未保存
        if detect_task_id:
            run_async(_update_detect_task_progress(detect_task_id, 100, "completed"))

        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "Detection completed", "intervals": intervals},
        )
        return {"episode_id": episode_id, "intervals_count": len(intervals), "intervals": intervals}

    except Exception as e:
        logger.error(f"Detect task failed: {e}")
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
    badges_config: Optional[list] = None,
    badge_default_width: int = 0,
    subtitle_config: Optional[dict] = None,
    text_overlays_config: Optional[list] = None,
    subtitle_mask_config: Optional[dict] = None,
    watermark_mask_config: Optional[dict] = None,
    subtitle_align_mask: bool = True,
    cover_image_key: Optional[str] = None,
    output_tier: Optional[str] = None,
    hook_video_key: Optional[str] = None,
    hook_video_keys: Optional[List[str]] = None,
):
    """Execute video slicing, upload outputs to MinIO and persist SliceOutput rows.

    encoder: 三期 GPU 加速编码,可选 h264_nvenc/hevc_nvenc/\
        h264_videotoolbox/hevc_videotoolbox/libx264;不传则引擎自动探测。
    source_bucket: 源视频所在桶;普通切片为 raw-footage,成品重新剪辑为 sliced。
    vert2horiz_config: 竖屏转横屏预处理配置(切片前把竖屏素材转成横屏)。
    badges_config: 图片角标配置(切片后在成品上叠加角标)。
    badge_default_width: 角标默认宽度(px,0=保持原图尺寸;角标未单独设 width 时生效)。
    subtitle_config: 字幕烧录配置({"enabled": True, "srt": str},切片时烧录到成品)。
    cover_image_key: 视频封面图片 MinIO key(可选,作为成品视频首帧叠加)。
    hook_video_key: 钩子视频 MinIO key(可选,作为片头拼接在封面与本体之间)。
    """
    from app.services.slice_service import run_slice_scrub, run_slice_fast
    from app.services.minio_service import upload_file_from_path, download_to_file
    from app.config import settings
    from app.utils.helpers import write_temp_file, ensure_dir

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动切片任务..."})

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

        # 图片角标:下载每个角标图片到本地,构造引擎期望的 badge 配置(含 path)
        badge_items = None
        if badges_config:
            badge_items = []
            badge_dir = ensure_dir(f"/tmp/slice_outputs/{episode_id}/{self.request.id}/badges")
            for bi in badges_config:
                fk = bi.get("file_key") or ""
                if not fk:
                    continue
                local = os.path.join(badge_dir, os.path.basename(fk))
                ok = run_async(
                    download_to_file(settings.MINIO_BUCKET_RAW, fk, local)
                )
                if not ok or not os.path.isfile(local):
                    logger.warning("角标图片下载失败,跳过: %s", fk)
                    continue
                item = {"path": local, "position": bi.get("position", "top-left")}
                if bi.get("width"):
                    item["width"] = int(bi["width"])
                if bi.get("offset") is not None:
                    item["offset"] = int(bi["offset"])
                if bi.get("opacity") is not None:
                    item["opacity"] = float(bi["opacity"])
                badge_items.append(item)

        # 视频封面:下载封面图片到本地,作为视频首帧叠加
        cover_path = None
        if cover_image_key:
            cover_local = os.path.join(
                output_dir, f"cover_{os.path.basename(cover_image_key)}"
            )
            ok = run_async(
                download_to_file(settings.MINIO_BUCKET_RAW, cover_image_key, cover_local)
            )
            if ok and os.path.isfile(cover_local):
                cover_path = cover_local
                logger.info("视频封面已下载到本地: %s", cover_local)
            else:
                logger.warning("视频封面下载失败,忽略: %s", cover_image_key)

        # 钩子视频:下载到本地,作为片头拼接([封面][钩子][本体])。
        # 文件夹方式(多个)优先,否则回退到单钩子;引擎每个成品按顺序循环取一个。
        hook_paths: list = []
        hook_keys = list(hook_video_keys or [])
        if not hook_keys and hook_video_key:
            hook_keys = [hook_video_key]
        for i, hk in enumerate(hook_keys):
            hook_local = os.path.join(output_dir, f"hook_{i}_{os.path.basename(hk)}")
            ok = run_async(download_to_file(settings.MINIO_BUCKET_RAW, hk, hook_local))
            if ok and os.path.isfile(hook_local):
                hook_paths.append(hook_local)
                logger.info("钩子视频已下载到本地: %s", hook_local)
            else:
                logger.warning("钩子视频下载失败,忽略: %s", hk)
        hook_path = hook_paths[0] if hook_paths else None

        # 字幕烧录:把 ASR 生成的 SRT 写到本地文件,供引擎 --subtitle 使用
        subtitle_srt_path = None
        subtitle_font_ratio = None
        subtitle_spacing = None
        subtitle_style = None
        subtitle_color = None
        subtitle_border_color = None
        subtitle_bold = None
        if subtitle_config and subtitle_config.get("enabled"):
            srt_content = subtitle_config.get("srt") or ""
            if srt_content.strip():
                subtitle_srt_path = write_temp_file(srt_content, suffix=".srt")
                logger.info("字幕烧录已开启,SRT 已写入本地: %s", subtitle_srt_path)
            # 字幕字号(相对高度比例),用户可调大让字幕更清晰易读
            fr = subtitle_config.get("font_ratio")
            if isinstance(fr, (int, float)) and fr > 0:
                subtitle_font_ratio = float(fr)
            # 字幕字间距(ASS Spacing 像素),让字幕文字更紧凑
            sp = subtitle_config.get("spacing")
            if isinstance(sp, (int, float)):
                subtitle_spacing = int(sp)
            # 字幕样式:default / custom(自定义字体色+边框色,无底色)
            st = subtitle_config.get("style")
            if st:
                subtitle_style = str(st)
            fc = subtitle_config.get("font_color")
            if fc:
                subtitle_color = str(fc)
            bc = subtitle_config.get("border_color")
            if bc:
                subtitle_border_color = str(bc)
            bd = subtitle_config.get("bold")
            if bd is not None:
                subtitle_bold = int(bd)

        # 源字幕打码时间轴 SRT:后端已把 SRT 内容放进 subtitle_mask_config["srt"],
        # 这里写到本地文件并替换为文件路径,供引擎 --subtitle-mask 使用。
        # 打码与字幕烧录是独立开关,即使未开启字幕烧录也照常处理。
        if subtitle_mask_config and subtitle_mask_config.get("enabled"):
            mask_srt_content = subtitle_mask_config.get("srt") or ""
            if mask_srt_content.strip():
                mask_srt_path = write_temp_file(mask_srt_content, suffix=".srt")
                subtitle_mask_config["srt"] = mask_srt_path
                logger.info("源字幕打码时间轴 SRT 已写入本地: %s", mask_srt_path)

        # 引擎进度回调会在 async 循环内被同步调用,不能在这里 run_async
        # (会嵌套事件循环报错)。只收集进度,引擎结束后统一写库。
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
                    badges_config=badge_items,
                    badge_default_width=badge_default_width,
                    subtitle_srt_path=subtitle_srt_path,
                    subtitle_font_ratio=subtitle_font_ratio,
                    subtitle_spacing=subtitle_spacing,
                    subtitle_style=subtitle_style,
                    subtitle_color=subtitle_color,
                    subtitle_border_color=subtitle_border_color,
                    subtitle_bold=subtitle_bold,
                    text_overlays_config=text_overlays_config,
                    dedupe_config=dedupe_config,
                    subtitle_mask_config=subtitle_mask_config,
                    watermark_mask_config=watermark_mask_config,
                    subtitle_align_mask=subtitle_align_mask,
                    cover_path=cover_path,
                    output_tier=output_tier,
                    hook_path=hook_path,
                    task_id=task_id,
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
                    badges_config=badge_items,
                    badge_default_width=badge_default_width,
                    subtitle_srt_path=subtitle_srt_path,
                    subtitle_font_ratio=subtitle_font_ratio,
                    subtitle_spacing=subtitle_spacing,
                    subtitle_style=subtitle_style,
                    subtitle_color=subtitle_color,
                    subtitle_border_color=subtitle_border_color,
                    subtitle_bold=subtitle_bold,
                    text_overlays_config=text_overlays_config,
                    dedupe_config=dedupe_config,
                    subtitle_mask_config=subtitle_mask_config,
                    watermark_mask_config=watermark_mask_config,
                    subtitle_align_mask=subtitle_align_mask,
                    cover_path=cover_path,
                    output_tier=output_tier,
                    hook_path=hook_path,
                    hook_paths=hook_paths,
                    task_id=task_id,
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
    config: Optional[dict] = None,
):
    """Replace clip candidates for an episode with AutoClip results.

    注意：min_duration / max_duration 不再作为落库前的硬性时长过滤（P1 修复 #228）。
    引擎产出的高光片段天然 50~145s，若把用户配置的 max_duration=30 作为硬过滤，
    会把全部候选砍成 0。duration 仅作引擎 step2 定位参考，候选片段一律原样保存，
    由下游切片/剪辑按需处理，避免"选点 0 候选"问题。
    """
    from sqlalchemy import select, delete, update
    from app.models.models import ClipCandidate, SliceOutput, AutoClipProject, Episode

    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)

        # 旧候选可能被 slice_outputs.clip_id 外键引用(切片输出已生成),
        # 直接 DELETE 会触发 ForeignKeyViolation 导致选点任务失败。
        # 先解除引用(成品切片输出保留,仅断开与旧候选的关联),再删除候选。
        await session.execute(
            update(SliceOutput)
            .where(SliceOutput.clip_id.in_(
                select(ClipCandidate.id).where(ClipCandidate.episode_id == eid)
            ))
            .values(clip_id=None)
        )
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
                clip_type=clip.get("clip_type"),
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
        else:
            # 无匹配记录：事务内只读，显式结束事务避免连接以 idle in transaction 回池
            await session.rollback()


async def _update_autoclip_run(
    episode_id: str,
    autoclip_project_id: Optional[str],
    status: str,
    progress: float,
    message: Optional[str] = None,
):
    """更新最近一条 AI 选点执行历史的状态/进度(供工作台历史展示)。"""
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
            # 兼容旧数据:没有历史记录时尝试补建一条
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

    只替换与本次检测同类型(interval_type)的旧结果,避免"水印"等无自动检测器
    的模式返回空列表时,把已保存的片尾字幕/静止画面结果一并清空。
    """
    from sqlalchemy import delete
    from app.models.models import DetectedInterval

    async with async_session_factory() as session:
        eid = uuid.UUID(episode_id)
        # 收集本次结果中出现的区间类型;若结果为空则不做删除(不覆盖其它类型)
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
            # 确保整型时间也写入(表字段为 Float,int 直接赋值在部分驱动下会丢精度/报错)
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

        # 幂等:任务已落库过输出则直接跳过,避免 Celery 重试导致重复输出
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

        created_outputs: list = []
        variant_count = 1
        base_dedupe = None
        created_by = None
        if tid is not None:
            # 收集本次新建的输出 id（变体生成需要）
            new_outs = await session.execute(
                select(SliceOutput).where(SliceOutput.task_id == tid)
            )
            created_outputs = new_outs.scalars().all()

        if tid is not None:
            task_result = await session.execute(
                select(SliceTask).where(SliceTask.id == tid)
            )
            task = task_result.scalar_one_or_none()
            variant_count = int(task.variant_count or 1) if task else 1
            base_dedupe = task.dedupe_config if task else None
            created_by = None
            if task:
                task.status = "completed"
                task.progress = 100.0
                task.output_count = len(output_files)
                task.completed_at = datetime.utcnow()
                task.error_message = None

            # 切片输出落库后把剧集状态推进到 completed,让工作流步骤条走到"成品预览"
            episode_result = await session.execute(
                select(Episode).where(Episode.id == uuid.UUID(episode_id))
            )
            episode = episode_result.scalar_one_or_none()
            if episode and episode.status != "completed":
                episode.status = "completed"

        await session.commit()

    # 多视频号素材去重：切片成功后自动派生 N 套去重变体（异步，不阻塞主链路）
    # variant_count>1 时对每个输出触发变体生成；variant_count<=1 时零侵入跳过。
    if variant_count > 1 and created_outputs:
        try:
            from app.celery.variant_tasks import generate_variants_task
            for out in created_outputs:
                generate_variants_task.delay(
                    str(out.id),
                    count=variant_count,
                    base_dedupe=base_dedupe,
                    created_by=created_by,
                )
            logger.info(
                "已投递变体生成任务: task=%s outputs=%s variant_count=%s",
                task_id, len(created_outputs), variant_count,
            )
        except Exception as e:
            logger.exception("投递变体生成任务失败 task=%s: %s", task_id, e)


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

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动发布任务..."})

    downloaded_video_path = None
    quota_acquired = False
    # PR③(inflight 防御性加固)：预声明 operator_id，finally 复用局部变量，
    # 避免跨块重复 publish_task_data.get() 的 NameError 风险。
    # 前提约束：acquire_quota 必须保持在 _get_publish_task 之后执行（quota_acquired
    # 仅在 publish_task_data 赋值后才可能为 True）；若有人前移会破坏该不变量。
    operator_id = None
    # PR②：发布失败时的风控分类（upload_limited / env_risk / 默认 publish_limited）
    _risk_type = None
    try:
        publish_task_data = run_async(_get_publish_task(publish_task_id))
        if not publish_task_data:
            raise Exception(f"Publish task {publish_task_id} not found")

        # 发布护栏（多视频号素材去重）：一个账号只允许绑定一个变体。
        # 在真正发布前二次校验，防止同素材原样发多号被平台判定搬运。
        try:
            from app.services.variant_service import guard_account_variant_unique
            _pub_account = publish_task_data.get("account_id")
            _pub_output = publish_task_data.get("output_id")
            if _pub_account and _pub_output:
                guard = run_async(guard_account_variant_unique(
                    _pub_account, output_id=_pub_output
                ))
                if not guard["allowed"]:
                    raise Exception("publish blocked by one-account-one-variant guard: " + guard["reason"])
        except Exception as e:
            run_async(_update_publish_task_status(
                publish_task_id, status="failed",
                error_message="one-account-one-variant guard: " + str(e),
            ))
            raise

        # 多运营者(R22):配额双闸门 + inflight 信号量(Lua 原子,nil 兜底)
        # 方向③ 风控/节奏可配置化:配额参数与随机延迟从 SystemConfig 热更读取
        rate_cfg = run_async(_get_publish_rate_config())
        try:
            from app.services import multi_operator
            if run_async(multi_operator.multi_operator_enabled()):
                operator_id = publish_task_data.get("operator_id")
                account_id = publish_task_data.get("account_id")
                if operator_id and account_id:
                    quota_acquired = run_async(multi_operator.acquire_quota(
                        account_id, operator_id,
                        acct_limit=rate_cfg.get("acct_limit", 20),
                        op_limit=rate_cfg.get("op_limit", 20),
                        op_inflight_limit=rate_cfg.get("op_inflight_limit", 1),
                        global_inflight_limit=rate_cfg.get("global_inflight_limit", 4),
                    ))
                    if not quota_acquired:
                        raise Exception("Quota exceeded or concurrent slot busy (Lua dual-gate)")
                    # 方向③ 错峰随机延迟(ms)可配置,降低同刻并发风控风险
                    min_delay = int(rate_cfg.get("min_delay_ms", 0) or 0)
                    max_delay = int(rate_cfg.get("max_delay_ms", 0) or 0)
                    if max_delay > 0:
                        import random as _random
                        delay = _random.randint(min_delay, max_delay)
                        if delay > 0:
                            import time as _time
                            logger.info("publish rate: sleep %sms before tab start (operator=%s)", delay, operator_id)
                            _time.sleep(delay / 1000.0)
        except Exception as e:
            # 未开启或配额异常:日志但不阻断一期旧链路(除非是明确的配额拒绝)
            if "Quota exceeded" in str(e) or "concurrent slot busy" in str(e):
                run_async(_update_publish_task_status(
                    publish_task_id, status="failed",
                    error_message=f"multi_operator quota: {e}",
                ))
                raise

        platform = publish_task_data["platform"]
        publisher = get_publisher(
            platform,
            chrome_debug_port=publish_task_data.get("chrome_debug_port", settings.CHROME_DEBUG_PORT),
            cookie_file=publish_task_data.get("cookie_file"),
            require_manual_confirm=publish_task_data.get("require_manual_confirm", True),
            cdp_url=publish_task_data.get("cdp_url"),
            cdp_token=publish_task_data.get("cdp_token"),
        )

        self.update_state(
            state="PROGRESS",
            meta={"progress": 20, "message": f"Publishing to {platform}..."},
        )

        video_path = run_async(_download_video_for_publish(
            publish_task_data["output_id"],
            publish_task_data.get("account_id") or publish_task_data.get("video_account_id"),
        ))
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
            publish_jump=publish_task_data.get("publish_jump"),
            task_id=publish_task_id,
            publish_comments=publish_task_data.get("publish_comments"),
            location=publish_task_data.get("location"),
        ))

        # 审计(P1 问题10):发布动作落 publish_audit,并生成 trace_id 贯穿确认→发布
        try:
            from app.services import audit_service
            rid = gen_publish_trace_id(publish_task_id)
            run_async(audit_service.log_publish_audit(
                task_id=publish_task_id,
                account_id=publish_task_data.get("account_id"),
                operator_id=publish_task_data.get("operator_id"),
                actor_id=publish_task_data.get("actor_id") or publish_task_data.get("operator_id"),
                profile_id=publish_task_data.get("profile_id"),
                content_hash=audit_service.content_hash(
                    f"{publish_task_data.get('title','')}|{publish_task_data.get('cover_file_key','')}"
                ),
                copy_template=publish_task_data.get("title", ""),
                port=publish_task_data.get("port"),
                action="publish",
                result="pending_confirm" if (result.get("status") == "pending_confirm" and result.get("success")) else ("success" if result.get("success") else "failed"),
                request_id=rid,
            ))
        except Exception:
            pass

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

        # PR②：publish 返回的风控分类透传给 except 分支，落 upload_limited/env_risk
        _risk_type = result.get("risk_type")
        raise Exception(result.get("error", "Unknown publish error"))

    except Exception as e:
        logger.error(f"Publish task failed: {e}")
        # 审计(P1 问题10):失败路径落 publish_audit + risk_event(驱动毕业统计)
        try:
            from app.services import audit_service
            rid = gen_publish_trace_id(publish_task_id)
            run_async(audit_service.log_publish_audit(
                task_id=publish_task_id,
                account_id=publish_task_data.get("account_id"),
                operator_id=publish_task_data.get("operator_id"),
                actor_id=publish_task_data.get("actor_id") or publish_task_data.get("operator_id"),
                profile_id=publish_task_data.get("profile_id"),
                action="fail",
                result="failed",
                risk_flag=True,
                risk_note=str(e)[:500],
                request_id=rid,
            ))
            # 风控/失败归入 risk_event(默认 publish_limited;PR②:风控拒发则落 upload_limited/env_risk),
            # 供毕业阈值统计与运维处置(风控不自动重试,走死信队列人工/定时重放)
            _final_risk_type = _risk_type or audit_service.RISK_TYPE_PUBLISH_LIMITED
            run_async(audit_service.log_risk_event(
                account_id=publish_task_data.get("account_id"),
                operator_id=publish_task_data.get("operator_id"),
                actor_id=publish_task_data.get("actor_id") or publish_task_data.get("operator_id"),
                risk_type=_final_risk_type,
                level="warning",
                message=str(e)[:1000],
                request_id=rid,
            ))
        except Exception:
            pass
        # 失败时释放可能残留的待确认 tab,避免浏览器连接泄漏
        from app.services.publish_service import release_pending_tab
        release_pending_tab(publish_task_id)
        # 方向② 批量：失败写死信标记（不再静默丢失，可回溯重发）
        run_async(_update_publish_task_status(
            publish_task_id,
            status="failed",
            error_message=str(e),
            mark_dead_letter=True,
            dead_letter_reason=str(e),
        ))
        raise
    finally:
        # Clean up downloaded video file
        if downloaded_video_path and os.path.isfile(downloaded_video_path):
            try:
                os.unlink(downloaded_video_path)
            except OSError:
                pass
        # 多运营者(R22):释放 inflight slot(成功/失败/超时均释放,跨日不误顶)
        if quota_acquired:
            try:
                from app.services import multi_operator
                # PR③：复用局部变量 operator_id（已在配额块赋值），不再重新 .get()
                if operator_id:
                    run_async(multi_operator.release_inflight(operator_id))
            except Exception:
                pass


def _release_confirm_lock(lock_key: str, acquired: bool) -> None:
    """释放 confirm 幂等锁（若已获取）。"""
    if not acquired:
        return
    try:
        from app.services.redis_stream import get_redis as _get_rd

        async def _release():
            _rd = await _get_rd()
            try:
                await _rd.delete(lock_key)
            finally:
                pass  # 共享连接池，由进程生命周期统一管理，无需 close

        run_async(_release())
    except Exception:
        logger.warning("failed to release confirm lock %s", lock_key, exc_info=True)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def confirm_publish_worker(self, publish_task_id: str):
    """Confirm a pending publish by clicking publish in the already-prepared Chrome tab."""
    from app.services.publish_service import get_publisher

    self.update_state(state="STARTED", meta={"progress": 50, "message": "正在确认发布操作..."})
    # 方向④ 稳定性：confirm 幂等锁（Redis setnx, task_id 维度, 防并发重复发布）
    lock_key = f"pub:confirm_lock:{publish_task_id}"
    lock_acquired = False
    try:
        from app.services.redis_stream import get_redis as _get_rd

        async def _acquire_lock():
            _rd = await _get_rd()
            try:
                return await _rd.set(lock_key, "1", nx=True, ex=120)
            finally:
                pass  # 共享连接池，由进程生命周期统一管理，无需 close

        got = run_async(_acquire_lock())
        if not got:
            raise Exception("Confirm already in progress (idempotent lock held)")
        lock_acquired = True
    except Exception as e:
        # 锁获取失败即视为并发冲突，直接失败不重复发布
        logger.warning("confirm idempotent lock failed: %s", e)
        run_async(_update_publish_task_status(publish_task_id, status="failed", error_message=str(e)))
        raise

    try:
        publish_task_data = run_async(_get_publish_task(publish_task_id))
        if not publish_task_data:
            raise Exception(f"Publish task {publish_task_id} not found")

        # 方向④ 二次鉴权：确认发布前重新校验 CDP token（多运营者开启时）
        try:
            from app.services import multi_operator
            if run_async(multi_operator.multi_operator_enabled()):
                account_id = publish_task_data.get("account_id")
                if account_id:
                    # 签发一次性 confirm token 并立即校验，确认该操作者对当前账号仍有发布权
                    actor = publish_task_data.get("actor_id") or publish_task_data.get("operator_id")
                    confirm_token = run_async(multi_operator.issue_cdp_token(actor or account_id, account_id, ttl=30))
                    ok = run_async(multi_operator.verify_cdp_token(confirm_token, account_id))
                    if not ok:
                        raise Exception("二次鉴权失败: CDP token 校验未通过")
        except Exception as e:
            if "二次鉴权失败" in str(e):
                raise
            logger.warning("confirm re-auth skipped: %s", e)

        publisher = get_publisher(
            publish_task_data["platform"],
            chrome_debug_port=publish_task_data.get("chrome_debug_port", settings.CHROME_DEBUG_PORT),
            require_manual_confirm=True,
            cdp_url=publish_task_data.get("cdp_url"),
            cdp_token=publish_task_data.get("cdp_token"),
        )
        result = run_async(publisher.confirm_publish(task_id=publish_task_id))
        if not result.get("success"):
            raise Exception(result.get("error", "Confirm publish failed"))

        # 审计（P1 问题10）：确认发布动作落 publish_audit（复用 task_id 稳定 trace_id）
        try:
            from app.services import audit_service
            run_async(audit_service.log_publish_audit(
                task_id=publish_task_id,
                account_id=publish_task_data.get("account_id"),
                operator_id=publish_task_data.get("operator_id"),
                actor_id=publish_task_data.get("actor_id") or publish_task_data.get("operator_id"),
                profile_id=publish_task_data.get("profile_id"),
                port=publish_task_data.get("port"),
                action="confirm",
                result="success",
                request_id=gen_publish_trace_id(publish_task_id),
            ))
        except Exception:
            pass

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
        _release_confirm_lock(lock_key, lock_acquired)
        return result
    except Exception as e:
        logger.error(f"Confirm publish failed: {e}")
        from app.services.publish_service import release_pending_tab
        release_pending_tab(publish_task_id)
        # 方向② 批量：confirm 失败写死信标记（可回溯重发）
        run_async(_update_publish_task_status(
            publish_task_id,
            status="failed",
            error_message=str(e),
            mark_dead_letter=True,
            dead_letter_reason=str(e),
        ))
        _release_confirm_lock(lock_key, lock_acquired)
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=300)
def check_cookie_status(self):
    """定时巡检各发布平台登录态是否失效(视频号/抖音/快手)。

    通过 CDP 连接 rpa_worker 的常驻 Chromium,依次打开各平台创作中心
    检查登录标识。结果写入日志;若配置了钉钉 Webhook,会追加一条告警通知。
    """
    from app.services.publish_service import get_publisher
    from app.services import audit_service

    platforms = ["wechat_channel", "douyin", "kuaishou"]
    results = {}
    try:
        for platform in platforms:
            try:
                publisher = get_publisher(platform)
                result = run_async(publisher.check_login_status())
                results[platform] = result
                # 审计（P1 问题10）：cookie 读取（登录态巡检）落 cookie_access_log
                run_async(audit_service.log_cookie_access(
                    purpose="login_check",
                    account_id=result.get("account_id") if isinstance(result, dict) else None,
                    operator_id=result.get("operator_id") if isinstance(result, dict) else None,
                    ip_address=result.get("source_ip") if isinstance(result, dict) else None,
                ))
            except Exception as e:
                logger.error(f"Cookie status check failed for {platform}: {e}")
                results[platform] = {"status": "error", "platform": platform, "error": str(e)}

        expired = [
            p for p, r in results.items()
            if r.get("status") == "expired"
        ]
        if expired:
            # 风控/失效：登录态失效入 risk_event（login_restricted），驱动毕业与扫码队列
            for p in expired:
                run_async(audit_service.log_risk_event(
                    risk_type="login_restricted",
                    level="warning",
                    message=f"登录态失效: {p}",
                    disposition="re_login",
                ))
            logger.warning("发布平台登录态已失效: %s", ", ".join(expired))
        else:
            logger.info("Cookie status check completed: %s", results)

        # 登录态失效时推送钉钉告警(若已配置)
        if expired and settings.DINGTALK_WEBHOOK:
            try:
                from app.services.monitor_service import send_dingtalk_alert
                run_async(send_dingtalk_alert(
                    settings.DINGTALK_WEBHOOK,
                    "error",
                    f"发布平台登录态失效,需要重新扫码登录: {', '.join(expired)}",
                ))
            except Exception as e:
                logger.error(f"Failed to send dingtalk alert for cookie status: {e}")

        self.update_state(
            state="SUCCESS",
            meta={"progress": 100, "message": "Cookie status check completed", "results": results},
        )
        return results
    except Exception as e:
        logger.error(f"Cookie status check failed: {e}")
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def sync_multi_operator_profiles(self):
    """多运营者(R15):把启用的 PublishProfile 同步到 Redis 路由表 + `pub:profiles`。

    仅当 MULTI_OPERATOR_ENABLED 开启时执行;为每个 profile 原子分配端口并写路由表,
    供 rpa_worker 启动/重建 Chromium 与 cdp_proxy 多实例使用。灰度关闭时零侵入跳过。
    """
    try:
        from app.services import multi_operator
        if not run_async(multi_operator.multi_operator_enabled()):
            return {"enabled": False}
        profiles = run_async(multi_operator.sync_profiles_from_db())
        logger.info("synced %d multi-operator profiles to route table", len(profiles))
        self.update_state(state="SUCCESS", meta={"progress": 100, "count": len(profiles)})
        return {"enabled": True, "count": len(profiles), "profiles": profiles}
    except Exception as e:
        logger.error(f"sync_multi_operator_profiles failed: {e}")
        raise


@celery_app.task(bind=True, max_retries=0)
def watch_multi_operator_routes(self):
    """多运营者(R12):watcher 秒级探活路由表,Chromium 崩溃/异常时置 expired。

    每 10s 探一次(beat 调度),连续 2 次失败(≈20s)置 expired,调度跳过该 operator。
    """
    try:
        from app.services import multi_operator
        if not run_async(multi_operator.multi_operator_enabled()):
            return {"enabled": False}
        summary = run_async(multi_operator.check_route_heartbeats())
        expired = [k for k, v in summary.items() if v == "expired"]
        if expired:
            logger.warning("route heartbeat expired for accounts: %s", expired)
        return {"enabled": True, "summary": summary}
    except Exception as e:
        logger.error(f"watch_multi_operator_routes failed: {e}")
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=300)
def task_collect_metrics(self, account_id: Optional[str] = None, target_date: Optional[str] = None):
    """Periodic task for collecting and aggregating metrics data."""
    from datetime import date as date_type

    self.update_state(state="STARTED", meta={"progress": 0, "message": "正在启动数据采集任务..."})

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
        raise


def gen_publish_trace_id(publish_task_id: str) -> str:
    """生成基于 task_id 的稳定 trace_id,使 发布(publish)→确认(confirm) 复用同一条链路。"""
    import hashlib
    return f"pub-{hashlib.sha256(publish_task_id.encode()).hexdigest()[:16]}"


DEFAULT_PUBLISH_RATE = {
    "acct_limit": 20,
    "op_limit": 20,
    "op_inflight_limit": 1,
    "global_inflight_limit": 4,
    "min_delay_ms": 0,
    "max_delay_ms": 0,
    "fingerprint_variant": False,
}


async def _get_publish_rate_config() -> dict:
    """从 SystemConfig 读取发布风控/节奏配置（方向③，可运行时热更）。

    返回带默认值的合并字典；未在数据库配置时回落到默认值。
    """
    from app.models.models import SystemConfig
    from sqlalchemy import select

    cfg = dict(DEFAULT_PUBLISH_RATE)
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.key == "publish_rate_config")
            )
            row = result.scalar_one_or_none()
            if row and isinstance(row.value, dict):
                cfg.update(row.value)
            # 事务内只读：显式结束事务
            await session.rollback()
    except Exception:
        logger.warning("failed to load publish_rate_config, fallback to defaults", exc_info=True)
    return cfg


async def _get_publish_task(publish_task_id: str) -> Optional[dict]:
    """Fetch publish task data from the database."""
    from app.models.models import PublishTask, PublishProfile, VideoAccount, PublishMaterial
    from sqlalchemy import select

    async with async_session_factory() as session:
        task_uuid = uuid.UUID(publish_task_id)
        result = await session.execute(
            select(PublishTask).where(PublishTask.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None

        profile = None
        # 优先按 (platform, account_name) 匹配发布配置(兼容既有逻辑)
        profile_result = await session.execute(
            select(PublishProfile).where(
                PublishProfile.platform == task.platform,
                PublishProfile.account_name == task.account_name,
            )
        )
        profile = profile_result.scalar_one_or_none()

        # 若任务关联了账号库(video_account_id),优先取账号绑定的发布配置
        if not profile and task.video_account_id:
            acc_result = await session.execute(
                select(VideoAccount).where(VideoAccount.id == task.video_account_id)
            )
            acc = acc_result.scalar_one_or_none()
            if acc and acc.profile_id:
                prof_result = await session.execute(
                    select(PublishProfile).where(PublishProfile.id == acc.profile_id)
                )
                profile = prof_result.scalar_one_or_none()

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
            "publish_jump": list(task.publish_jump) if task.publish_jump else None,
            "require_manual_confirm": task.require_manual_confirm,
            "video_account_id": str(task.video_account_id) if task.video_account_id else None,
            "mini_program_id": str(task.mini_program_id) if task.mini_program_id else None,
            "operator_id": str(task.operator_id) if task.operator_id else None,
            "account_id": str(task.video_account_id) if task.video_account_id else None,
            "profile_id": str(profile.id) if profile else None,
            "actor_id": str(task.created_by) if getattr(task, "created_by", None) else (str(task.operator_id) if task.operator_id else None),
            "port": profile.chrome_debug_port if profile else None,
        }

        # 发布后置顶神评：从发布任务关联的发布素材(PublishMaterial)读取三条互动神评，
        # 供发布成功后探活式发表+置顶（拉高互动率；失败不阻断发布）。
        try:
            if task.material_id:
                mat_res = await session.execute(
                    select(PublishMaterial).where(PublishMaterial.id == task.material_id)
                )
                mat = mat_res.scalar_one_or_none()
                if mat and mat.material_json:
                    comments = (mat.material_json or {}).get("comments") or []
                    if isinstance(comments, list):
                        data["publish_comments"] = comments
        except Exception as e:
            logger.warning(f"load publish_comments from material failed: {e}")

        # 多运营者(R14/R19/R22):flag=true 时按路由表解析端口并签发 CDP token
        try:
            from app.services import multi_operator
            if await multi_operator.multi_operator_enabled():
                account_id = data.get("account_id")
                if account_id:
                    port = await multi_operator.resolve_port(account_id)
                    if port:
                        # 路由表端口指向 cdp_proxy 鉴权口(R19)
                        data["cdp_url"] = f"http://{settings.CHROME_DEBUG_HOST}:{port}"
                        data["port"] = port
                        # 签发短期 token:actor=operator_id(号主)
                        token = await multi_operator.issue_cdp_token(
                            data.get("operator_id") or account_id, account_id
                        )
                        data["cdp_token"] = token
        except Exception as e:
            logger.warning(f"multi_operator route/token resolution failed: {e}")

        if profile:
            data["chrome_debug_port"] = profile.chrome_debug_port
            # 发布页「位置」配置（按账号注入，P2）：留空则不填
            data["location"] = profile.location
            # RPA Cookie 解密(AES-256/Fernet 加密存储,仅在 Worker 内部使用)
            if profile.cookie_file:
                try:
                    from app.auth import decrypt_cookie
                    data["cookie_file"] = decrypt_cookie(profile.cookie_file)
                except Exception:
                    logger.warning("Failed to decrypt cookie for profile %s", profile.account_name)

        # 事务内只读：显式结束事务
        await session.rollback()
        return data


async def _download_video_for_publish(output_id: str, account_id: str = None) -> Optional[str]:
    """Download the video to a local temp file for publishing.

    多视频号素材去重：若目标账号（account_id）已为该输出绑定某素材变体，
    则下载该变体的去重文件，确保每个账号发布的是各自去重版本（避免同素材原样发多号被平台判重）；
    否则回退到基准切片输出文件（未开多版本 / 未绑定时行为完全等同现状，零侵入）。
    """
    from app.models.models import SliceOutput, ClipVariant
    from app.services.minio_service import download_file
    from sqlalchemy import select

    file_key = None
    base_key = None
    async with async_session_factory() as session:
        out_uuid = uuid.UUID(output_id)
        result = await session.execute(
            select(SliceOutput).where(SliceOutput.id == out_uuid)
        )
        output = result.scalar_one_or_none()
        if not output or not output.file_key:
            # 事务内只读：显式结束事务
            await session.rollback()
            return None
        file_key = output.file_key
        base_key = output.file_key
        target_group = getattr(output, "variant_group_id", None)

        # 若该账号已绑定此素材（同变体组）的变体，改用变体文件
        if account_id:
            try:
                acc = uuid.UUID(account_id)
            except (ValueError, AttributeError):
                acc = None
            if acc:
                variant = (await session.execute(
                    select(ClipVariant).where(
                        ClipVariant.account_id == acc,
                        ClipVariant.file_key.isnot(None),
                    )
                )).scalar_one_or_none()
                # 仅当变体确属本输出所在变体组时启用（避免跨素材误用其它输出的变体）
                if variant and variant.file_key:
                    same_output = variant.output_id == out_uuid
                    same_group = bool(target_group) and bool(variant.variant_group_id) \
                        and str(variant.variant_group_id) == str(target_group)
                    if same_output or same_group:
                        file_key = variant.file_key
        # 事务内只读：显式结束事务
        await session.rollback()

    data = await download_file(settings.MINIO_BUCKET_SLICED, file_key)
    # 变体文件缺失时回退到基准切片文件（保证发布不被阻断，同时保持非变体行为兼容）
    if data is None and base_key and base_key != file_key:
        file_key = base_key
        data = await download_file(settings.MINIO_BUCKET_SLICED, base_key)
    if data is None:
        return None
    logger.info("publish download output=%s account=%s file=%s%s",
                output_id, account_id, file_key,
                " (variant)" if (base_key and file_key != base_key) else "")

    # 用文件 key 的稳定哈希拼唯一临时名，避免同素材多账号并发发布时互相覆盖
    os.makedirs("/tmp/publish_videos", exist_ok=True)
    import hashlib
    _suffix = hashlib.md5(file_key.encode("utf-8")).hexdigest()[:12]
    temp_path = f"/tmp/publish_videos/{output_id}_{_suffix}.mp4"
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
    mark_dead_letter: bool = False,
    dead_letter_reason: str = None,
    incr_retry: bool = False,
):
    """Update publish task status in the database.

    方向②/④：支持死信标记（mark_dead_letter）与重试计数（incr_retry）。
    """
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
        if mark_dead_letter:
            task.dead_letter = True
            task.dead_letter_reason = dead_letter_reason or error_message
        if incr_retry:
            task.retry_count = (task.retry_count or 0) + 1
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
    """三期监控告警:周期检查告警规则并推送钉钉 Webhook."""
    from app.services.monitor_service import run_alert_checks

    try:
        result = run_async(run_alert_checks())
        logger.info("Alert check completed: %s", result)
        return result
    except Exception as e:
        logger.error(f"Alert check failed: {e}")
        raise


@celery_app.task(bind=True, max_retries=1, default_retry_delay=300)
def maintenance_daily_task(self):
    """三期性能优化:每日归档过期看板数据 + 清理临时文件 + 设置 MinIO 生命周期."""
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
        raise


# ══════════════════════════════════════════════════════════════
# 去水印任务(v4)
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
    """更新单条去水印视频的状态(供 Celery 任务在同步上下文中调用)。"""
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

        # 平均进度:完成 100、失败/取消 100、运行中取各自 progress
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
    """批量去水印异步任务:逐条下载源视频 → 调用引擎 → 上传结果 → 汇总进度。"""
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
                await session.rollback()
                return None, []
            videos_res = await session.execute(
                select(WatermarkVideo).where(WatermarkVideo.task_id == tid)
            )
            videos = videos_res.scalars().all()
            # 只读块：async with 退出 close() 自动回滚事务并归还连接；不要显式 rollback()，
            # 否则 task/videos 被 expire，会话外访问 task.status / video.id 抛 DetachedInstanceError（#230）。
            return task, videos

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
            # 视频开始处理时立即刷新一次任务级汇总,让任务进度不再停留在 0%
            run_async(_recalc_watermark_task(task_id))

            src_local = temp_video_path("src")
            out_local = temp_video_path("out")

            # RAiW 要求输入文件带正确扩展名,且输出容器必须与源一致;
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

            # 引擎进度回调:同步上下文内更新数据库。
            # 注意:回调在 run_async 的事件循环内被同步调用,不能再用
            # run_async(会嵌套事件循环报错)。改为在已运行 loop 上调度协程。
            # 为避免高频写库(如逐帧修补),按进度变化节流:仅当进度提升≥5%或
            # 达到 100% 时落库。
            _last_written_progress = {"pct": 0}

            async def _persist_progress(pct: int):
                """视频进度落库后同步刷新任务级汇总,保证任务进度实时推进。"""
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

            # remove_mask 引擎按原始文件名匹配内置 ROI 表,这里用每条视频的真实文件名覆盖;
            # remove_ai / seedance / seedance_wm 也借 remove-mask 内置 ROI 经验库:
            # · remove_ai:RAiW 厂商检测失败时回退经验位置重试
            # · seedance / seedance_wm:自动检测基础上合并确认过的水印位置
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

    # 全部完成后,若仍有 pending(被取消跳过)则标记取消
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


# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# 短片制作任务（Phase 1 上帝类拆分）
# ──────────────────────────────────────────────
# 一键豆包生成（RPA）与 Seedance 官方 API 直连出片已拆入独立模块
# `app/celery/shortdrama_tasks.py`，此处仅 re-export，保证 Celery 任务名
# `app.celery.tasks.doubao_generate_task / seedance_generate_task` 与 API 层
# `from app.celery.tasks import doubao_generate_task / seedance_generate_task`
# 的既有引用零改动。
from app.celery.shortdrama_tasks import (  # noqa: E402,F401
    doubao_generate_task,
    seedance_generate_task,
)

# 多视频号素材去重：注册素材变体生成 / 指纹校验任务到本 Celery app。
# variant_tasks 依赖本模块的 celery_app / run_async，置于末尾避免循环导入。
from app.celery.variant_tasks import (  # noqa: E402,F401
    generate_variants_task,
    verify_variant_fingerprint_task,
)

__all__ = [
    "doubao_generate_task",
    "seedance_generate_task",
    "generate_variants_task",
    "verify_variant_fingerprint_task",
]


# 注册视频号素材导入下载（wechat_download）任务到本 Celery app。
# 置于文件末尾避免循环导入（wechat_download.tasks 依赖本模块的 celery_app）。
# 仅在并入形态需要；剥离形态 B 使用 wechat_download 独立 app 时无需此导入。
try:
    import wechat_download.tasks  # noqa: F401  # 触发任务注册
except Exception as _wechat_dl_import_err:  # pragma: no cover
    logger.warning("wechat_download.tasks 注册失败（不影响主系统其他任务）: %s", _wechat_dl_import_err)

# 注册局域网剧集导入（lan_source）任务到本 Celery app。
# 置于文件末尾避免循环导入；并入形态需要（可剥离形态可单独拉起 lan_source app）。
try:
    import lan_source.tasks  # noqa: F401  # 触发任务注册
except Exception as _lan_source_import_err:  # pragma: no cover
    logger.warning("lan_source.tasks 注册失败（不影响主系统其他任务）: %s", _lan_source_import_err)
