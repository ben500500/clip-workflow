"""批量切片工作流 Celery 编排任务（三期）。

入口：POST /api/batch-slice/run 创建批次后，异步派发本任务。
流程：按剧名找/建项目 → 逐集（严格按序）执行
     上传源视频 → 创建 Episode → AI 选点 → 自动审核 → 一键切片 → 删除源视频
→ 汇总输出列表。
"""

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from app.database import async_session_factory
from app.models.models import (
    BatchSlice,
    BatchSliceItem,
)
from app.services import batch_slice_service as bsvc
from app.celery.tasks import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在同步 Celery 任务里执行异步编排。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_batch(self, batch_id: str):
    """批量切片主编排：按剧名建项目 + 逐集处理。"""
    try:
        _run_async(_process_batch_async(batch_id))
    except Exception as e:
        logger.exception("批量切片批次处理失败 batch=%s", batch_id)

        async def _mark_batch_failed():
            async with async_session_factory() as session:
                try:
                    b = await session.get(BatchSlice, uuid.UUID(batch_id))
                    if b:
                        b.status = "failed"
                        b.error_message = str(e)[:2000]
                        await session.commit()
                except Exception:
                    pass
        _run_async(_mark_batch_failed())
        raise


async def _process_batch_async(batch_id: str):
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        logger.error("Invalid batch id: %s", batch_id)
        return

    async with async_session_factory() as session:
        batch = await session.get(BatchSlice, bid)
        if not batch:
            logger.error("Batch not found: %s", batch_id)
            return
        items = (
            await session.execute(
                select(BatchSliceItem)
                .where(BatchSliceItem.batch_id == bid)
                .order_by(BatchSliceItem.seq.asc().nullslast())
            )
        ).scalars().all()
        item_ids = [str(it.id) for it in items]
        batch.status = "running"
        batch.started_at = datetime.utcnow()
        await session.commit()

    # 逐集严格按序处理
    for item_id in item_ids:
        try:
            await _process_item_async(bid, item_id)
        except Exception as e:
            logger.exception("批次项处理异常 batch=%s item=%s", batch_id, item_id)
            await bsvc._update_item(item_id, status="failed", error=str(e)[:2000])
        finally:
            await bsvc._refresh_batch(bid)

    # 批次收尾
    async with async_session_factory() as session:
        batch = await session.get(BatchSlice, bid)
        if batch:
            if batch.status not in ("partial_failed", "failed"):
                batch.status = "completed"
                batch.completed_at = datetime.utcnow()
            await session.commit()
    logger.info("Batch %s finished", batch_id)


async def _process_item_async(batch_id, item_id):
    """处理单个剧集：上传→建Episode→选点→审核→切片→删源。"""
    # ① 上传源视频到 MinIO
    await bsvc._update_item(item_id, status="uploading", message="开始处理", progress=5.0)
    file_key = await bsvc.upload_source_video(item_id)
    if not file_key:
        return False

    # ② 创建 Episode
    episode_id = await bsvc.create_episode(batch_id, item_id)
    if not episode_id:
        return False

    # ③ AI 选点
    await bsvc._update_item(item_id, status="autoclip", message="正在 AI 智能选点…", progress=0.0)
    ok = await bsvc.dispatch_autoclip(item_id)
    if not ok:
        return False
    ok = await bsvc.wait_autoclip_complete(item_id)
    if not ok:
        return False

    # ④ 自动审核
    await bsvc._update_item(item_id, status="review", message="正在自动审核候选片段…")
    count = await bsvc.auto_review_clips(item_id)
    if count == 0:
        await bsvc._update_item(item_id, status="failed", error="AI 选点未生成候选片段")
        return False
    await bsvc._update_item(item_id, status="review", message=f"自动审核通过 {count} 个候选片段")

    # ⑤ 一键切片
    slice_config, delete_source = await _get_batch_params(batch_id)
    await bsvc._update_item(item_id, status="slicing", message="正在一键切片…")
    ok = await bsvc.dispatch_slice(item_id, slice_config)
    if not ok:
        return False
    ok = await bsvc.wait_slice_complete(item_id)
    if not ok:
        return False

    # ⑥ 删除源视频（节约空间）
    await bsvc.delete_source_video(item_id, delete_source)
    await bsvc._update_item(item_id, status="completed", message="处理完成",
                            progress=100.0, processed_at=datetime.utcnow())
    return True


async def _get_batch_params(batch_id):
    """返回 (slice_config, delete_source)。"""
    async with async_session_factory() as session:
        batch = await session.get(BatchSlice, uuid.UUID(str(batch_id)))
        if not batch:
            return {}, True
        return (batch.slice_config or {}), bool(batch.delete_source)
