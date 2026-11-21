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
import os

from sqlalchemy import select

from app.celery.tasks import celery_app, run_async
from app.config import settings
from app.database import async_session_factory
from app.services.minio_service import ensure_bucket, upload_file_from_path

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_remotion_mix_task(self, slice_task_id: str, lock_token: str = None):
    """对指定切片任务执行 Remotion 高光混剪增强渲染，并回写渲染结果状态。

    成功：更新 SliceTask.remotion_output_file_key + remotion_status="done"；
    失败：更新 remotion_status="failed" + error_message，并按重试策略 retry。

    lock_token：手动触发入口（/v1/remotion/render）持有的互斥锁令牌，收尾时释放；
    自动触发路径（切片完成后派发）不传 token，不涉及锁。
    """
    # 实体开关：系统设置页「Remotion 渲染」开关（system_configs.remotion_enabled）驱动，
    # 不再读取 env REMOTION_ENABLED（2026-11-20 弃用）
    from app.services.remotion_renderer import is_remotion_enabled
    from app.database import async_session_factory

    async def _check_enabled():
        async with async_session_factory() as db:
            return await is_remotion_enabled(db)

    if not run_async(_check_enabled()):
        logger.info("Remotion 渲染开关（系统设置）关闭，跳过 Remotion 渲染 slice_task=%s", slice_task_id)
        return {"skipped": True, "reason": "remotion disabled"}

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
    finally:
        # 释放入口互斥锁（仅手动触发路径持有；token 不匹配时 Lua 不会误删）
        if lock_token:
            try:
                from app.services.distributed_lock import release_lock
                run_async(release_lock(f"remotion:lock:{slice_task_id}", lock_token))
            except Exception:
                logger.warning("释放 Remotion 互斥锁失败 slice_task=%s", slice_task_id)


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
        task.status = "processing"  # Remotion 模式：拼接由 Remotion 完成，不派发 ffmpeg
        task.error_message = None
        await db.flush()

    # 渲染（独立子进程，耗时；在会话外执行，避免长事务）。
    # 返回 outputs 为「每个混剪成品文件」的本地路径列表（mix_output_count>1 时多文件）。
    # 进度回写：渲染中按 progress_cb 节流（≥2% 或阶段切换）更新 slice_tasks.progress，
    # 让前端能看到多文件渲染的实时推进（下载 5% → 渲染 5~92% → 上传 92~99%）。
    progress_state = {"last": 0.0}

    async def _progress_cb(pct: float, message: str = "") -> None:
        if pct - progress_state["last"] < 2.0 and pct < 91.0:
            return  # 节流：进度变化不足 2% 不写库（渲染末段与阶段切换强制写入）
        progress_state["last"] = pct
        try:
            async with async_session_factory() as db:
                t = (
                    await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
                ).scalar_one_or_none()
                if t and t.status == "processing":
                    t.progress = float(min(92.0, max(1.0, pct)))
                    if message:
                        t.error_message = None  # 渲染中清除历史错误，message 走日志
                    await db.commit()
        except Exception as e:
            logger.warning("回写渲染进度失败 slice_task=%s pct=%s: %s", slice_task_id, pct, e)

    ok, out = await render_highlight_mix(task, config, progress_cb=_progress_cb)
    if not ok:
        # 回写失败：任务无 ffmpeg 产物（Remotion 即拼接者），整体置 failed 供手动重试
        async with async_session_factory() as db:
            t = (
                await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
            ).scalar_one_or_none()
            if t:
                t.remotion_status = "failed"
                t.status = "failed"
                t.error_message = str(out)[:2000]
                await db.commit()
        return {"ok": False, "error": out}

    # 上传渲染产物到 MinIO sliced 桶（多文件：_001..N 序号 key）
    await ensure_bucket(settings.MINIO_BUCKET_SLICED)
    async with async_session_factory() as db:
        t = (
            await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
        ).scalar_one_or_none()
        if t and t.status == "processing":
            t.remotion_status = "uploading"
            await db.commit()
    outputs = out if isinstance(out, list) else [out]

    # 文件名沿用 cutlist 组名（与 ffmpeg 混剪命名一致：剧名_MMDD_NNN.mp4）
    from app.services.remotion_renderer import parse_mix_groups

    group_names = [
        g["name"] for g in parse_mix_groups(getattr(task, "cutlist", "") or "")
    ]
    keys: list[str] = []
    for i, local_path in enumerate(outputs, start=1):
        if len(outputs) == 1:
            key = f"{settings.REMOTION_OUTPUT_PREFIX}/{slice_task_id}.mp4"
        else:
            key = f"{settings.REMOTION_OUTPUT_PREFIX}/{slice_task_id}_{i:03d}.mp4"
        uploaded = await upload_file_from_path(settings.MINIO_BUCKET_SLICED, key, local_path)
        if not uploaded:
            return {"ok": False, "error": f"上传 Remotion 渲染产物到 MinIO 失败: {key}"}
        keys.append(key)
        # 上传进度：92% → 99% 按文件数均分
        await _progress_cb(92.0 + 7.0 * i / len(outputs), f"上传第 {i}/{len(outputs)} 个文件")

    # 回写最终状态 + 落 slice_outputs（前端输出列表的数据源，与 ffmpeg 收尾同表同规范；
    # 2026-11-20 修复：Remotion 产物此前只写 remotion_output_file_key，界面看不到任何输出）
    async with async_session_factory() as db:
        task = (
            await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
        ).scalar_one_or_none()
        if task:
            # 终态守卫（2026-11-20 评审 SRE P1-1）：用户已取消的任务不允许被迟到的
            # 渲染完成回调复活（cancelled 意图优先；迟到产物留 MinIO 不入库）。
            if task.status == "cancelled":
                logger.warning("Remotion 渲染完成但任务 %s 已取消，跳过回写", slice_task_id)
                return {"ok": True, "suppressed": True}
            # 幂等：重试路径可能已落过输出，避免重复插记录
            from app.models.material import SliceOutput

            existing = (
                await db.execute(
                    select(SliceOutput).where(SliceOutput.task_id == task.id)
                )
            ).scalars().first()
            if existing is None:
                for i, key in enumerate(keys, start=1):
                    local_path = outputs[i - 1] if i - 1 < len(outputs) else None
                    base_name = (
                        group_names[i - 1] if i - 1 < len(group_names) else f"{slice_task_id}_{i:03d}"
                    )
                    db.add(SliceOutput(
                        task_id=task.id,
                        clip_id=None,  # 混剪成品是组合产物，不对应单个候选段
                        file_key=key,
                        # 防御：组名可能极长，截断防 file_name varchar(255) 溢出（0071 迁移教训同族）
                        file_name=f"{base_name[:200]}.mp4",
                        file_size=(
                            os.path.getsize(local_path)
                            if local_path and os.path.isfile(local_path)
                            else None
                        ),
                    ))
            task.remotion_output_file_key = ",".join(keys)
            task.remotion_status = "done"
            # Remotion 即拼接者：渲染完成 = 切片任务完成
            task.status = "completed"
            task.output_count = len(keys)
            task.progress = 100.0
            task.error_message = None
            await db.commit()

    return {"ok": True, "output_file_key": keys[0], "output_file_keys": keys}


async def _mark_remotion_failed(slice_task_id: str, error: str) -> None:
    """失败回写：更新 remotion_status=failed + error_message。"""
    from app.models.models import SliceTask

    async with async_session_factory() as db:
        task = (
            await db.execute(select(SliceTask).where(SliceTask.id == slice_task_id))
        ).scalar_one_or_none()
        if task:
            # 终态守卫：已取消任务不写失败态（保留 cancelled 语义，不覆盖用户意图）
            if task.status == "cancelled":
                return
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

    # 实体开关：系统设置驱动（同 run_remotion_mix_task）
    from app.services.remotion_renderer import is_remotion_enabled
    from app.database import async_session_factory

    async def _check_enabled():
        async with async_session_factory() as db:
            return await is_remotion_enabled(db)

    if not run_async(_check_enabled()):
        return {"skipped": True, "reason": "remotion disabled"}

    timeout = settings.REMOTION_RENDER_TIMEOUT_SECONDS
    try:
        affected = run_async(_recover_stale_remotion(timeout))
        logger.info("remotion stale recovery: %s 条超时任务已回写 failed", affected)
        return {"ok": True, "affected": affected}
    except Exception as e:
        logger.exception("remotion stale recovery failed: %s", e)
        return {"ok": False, "error": str(e)}


async def _recover_stale_remotion(timeout_seconds: int) -> int:
    """回写卡死的 Remotion 任务（remotion_status=failed）。

    两类卡死形态：
    1. rendering 超时：worker 已领取但渲染挂死（Celery retry 仍在链路上，只改
       remotion_status，主 status 交给任务自身的失败回写收敛）；
    2. 孤儿：remotion_status 仍为 NULL 但主任务已 processing 超时——渲染消息
       丢失或（2026-11-20 前）仅开「Remotion 增强」未开「高光混剪」时短路创建
       而从未投递。此类任务无任何 Celery 链路在跑，必须连主 status 一起置 failed，
       否则前端永远显示 processing 且无法重试。
    """
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
        # 孤儿回收：状态从未进入 rendering（消息未投递/未消费），主任务一并置 failed
        orphan = await db.execute(
            text(
                """
                UPDATE slice_tasks
                SET remotion_status='failed',
                    status='failed',
                    error_message=COALESCE(error_message, '') || '; Remotion 渲染任务未投递成功（孤儿任务），由守护任务回写失败'
                WHERE remotion_status IS NULL
                  AND remotion_mix_config IS NOT NULL
                  AND status='processing'
                  AND created_at < now() - make_interval(secs => :to)
                """
            ),
            {"to": timeout_seconds},
        )
        await db.commit()
        return (result.rowcount or 0) + (orphan.rowcount or 0)
