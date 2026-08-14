"""批量切片解耦工作流（生产-消费模式）。

与 batch_slice_service.run_batch 的「逐集串行编排」不同，本模块将
「AI 选点」与「切片」解耦为两条独立流水线并行推进：

    选点流水线（Celery 任务 batch_selection_consumer）
        batch_slice_task（decoupled 模式）只负责：上传建 Episode + 投递选点队列
        → 选点消费者逐个 item：_trigger_autoclip → _wait_autoclip → _accept_all_candidates
        → item.phase='autoclip_done' + item.status='ready_slice'  ←「已选点池」

    切片流水线（Celery beat 任务 batch_slice_dispatch）
        beat 每 N 秒扫描 phase='autoclip_done' 的 item
        → 复用 run_slice → publish_slice_task 入 Redis Stream（slice:tasks:*）
        → Go slice-worker 消费切片 → item.phase='slicing'（防重复投递）→ 终态回填

    状态聚合（Celery beat 任务 batch_aggregate）
        按 batch 维度 COUNT 各终态，幂等回填 BatchSlice.done/failed/output_count

开关：BatchSlice.slice_config.pipeline_mode = "serial" | "decoupled"（默认 serial）。
decoupled 模式仅处理开启了该模式的批次，串行模式（batch_slice_service.run_batch）零改动。

注意：本模块所有入口函数均为 async，由 Celery 任务通过 run_async 调用，
以复用 per-thread event loop，避免 SQLAlchemy async engine 的 loop 绑定问题。
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update, func

from app.database import async_session_factory
from app.models.models import (
    BatchSlice,
    BatchSliceItem,
    Project,
    Episode,
    User,
)
from app.services import batch_slice_service as serial  # 复用串行模块的辅助函数

logger = logging.getLogger(__name__)

# 解耦模式阶段常量（扩展自串行模块，语义对齐）
PHASE_SELECT_DONE = "autoclip_done"   # 已选点待切片（「已选点池」状态位）
STATUS_READY_SLICE = "ready_slice"    # 选点完成、待切片
PHASE_SLICING = "slicing"


async def _get_batch(batch_id: str):
    async with async_session_factory() as session:
        result = await session.execute(
            select(BatchSlice).where(BatchSlice.id == uuid.UUID(batch_id))
        )
        return result.scalar_one_or_none()


async def _load_items(batch_id: str) -> list:
    async with async_session_factory() as session:
        result = await session.execute(
            select(BatchSliceItem)
            .where(BatchSliceItem.batch_id == uuid.UUID(batch_id))
            .order_by(BatchSliceItem.seq.asc())
        )
        return result.scalars().all()


async def _load_item(item_id: str) -> BatchSliceItem:
    async with async_session_factory() as session:
        result = await session.execute(
            select(BatchSliceItem).where(BatchSliceItem.id == uuid.UUID(str(item_id)))
        )
        return result.scalar_one_or_none()


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


async def _get_operator(batch: BatchSlice):
    """解析批次操作人（用于数据隔离校验）。返回 User 或 None。"""
    if not batch.created_by:
        return None
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == batch.created_by))
        return result.scalar_one_or_none()


async def _resolve_project(batch: BatchSlice):
    """确保目标 Project 存在，返回 project（batch 若无 project 则自动创建并回填）。"""
    # 优先复用批次已绑定项目
    if batch.project_id:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.id == batch.project_id)
            )
            proj = result.scalar_one_or_none()
            if proj:
                return proj
    # 否则按剧名查找/创建
    project = await serial._find_or_create_project(
        batch.name or "批量切片", str(batch.created_by)
    )
    await _update_batch(str(batch.id), project_id=project.id)
    return project


# ─────────────────────────────────────────────────────────────────────
# 一、解耦模式批次入口（batch_slice_task 在 decoupled 模式下调用）
# ─────────────────────────────────────────────────────────────────────
async def run_batch_decoupled(batch_id: str):
    """解耦模式批次入口：仅负责「上传建 Episode + 投递选点队列」，随即返回。

    真正的选点 / 切片由两条独立流水线异步推进，互不阻塞。
    各 item 的选点任务通过 celery task batch_selection_consumer 触发。
    """
    batch = await _get_batch(batch_id)
    if batch is None:
        logger.error("Batch %s 不存在", batch_id)
        return
    if batch.status in ("completed", "cancelled", "failed"):
        return

    operator = await _get_operator(batch)
    if operator is None:
        await _update_batch(batch_id, status="failed", error_message="无法确定批次操作人")
        return

    # 确保项目存在
    project = await _resolve_project(batch)
    if project is None:
        await _update_batch(batch_id, status="failed", error_message="无法确定目标项目")
        return

    await _update_batch(batch_id, status="running", started_at=datetime.utcnow())
    items = await _load_items(batch_id)

    # 逐集：上传建 Episode（复用串行辅助函数），然后投递选点任务
    from app.celery.tasks import batch_selection_consumer

    for item in items:
        if item.status in ("completed", "cancelled"):
            continue
        # 已在上传/选点/切片流程中的跳过
        if item.phase in (
            serial.PHASE_UPLOAD, serial.PHASE_AUTOCLIP, serial.PHASE_REVIEW,
            serial.PHASE_INTERVAL, PHASE_SELECT_DONE, PHASE_SLICING,
        ):
            continue

        episode_id = str(item.episode_id) if item.episode_id else None
        if not episode_id:
            try:
                episode_id = await serial._upload_and_create_episode(item, project.id)
                await _update_item(item.id, episode_id=uuid.UUID(episode_id))
            except Exception as e:
                logger.exception("上传源视频失败 batch=%s item=%s: %s", batch_id, item.id, e)
                await serial._set_phase(item, serial.PHASE_UPLOAD, "failed", 0)
                await _update_item(item.id, error_message=f"上传源视频失败: {e}")
                continue

        # 投递选点消费者（异步处理选点 + 自动审核）
        try:
            batch_selection_consumer.delay(str(batch_id), str(item.id), str(episode_id))
        except Exception as e:
            logger.exception("投递选点任务失败 item=%s: %s", item.id, e)
            await serial._set_phase(item, serial.PHASE_AUTOCLIP, "failed", 0)
            await _update_item(item.id, error_message=f"投递选点任务失败: {e}")


# ─────────────────────────────────────────────────────────────────────
# 二、选点消费者（Celery task batch_selection_consumer）
# ─────────────────────────────────────────────────────────────────────
async def process_selection(batch_id: str, item_id: str, episode_id: str):
    """选点消费者：对单个 item 执行「AI 选点 + 自动审核」，完成后标记为「已选点待切片」。

    处理完成后将 item.phase 置为 PHASE_SELECT_DONE、status 置为 STATUS_READY_SLICE，
    即写入「已选点池」，供切片投递守护消费。
    """
    item = await _load_item(item_id)
    if item is None:
        logger.error("BatchSliceItem %s 不存在", item_id)
        return
    if item.status in ("completed", "cancelled", "failed"):
        return

    batch = await _get_batch(batch_id)
    if batch is None:
        logger.error("Batch %s 不存在", batch_id)
        return

    operator = await _get_operator(batch)
    if operator is None:
        await _update_item(item_id, status="failed", error_message="无法确定批次操作人")
        return

    batch_cfg = batch.slice_config or {}
    autoclip_cfg = batch_cfg.get("autoclip_config") or {}
    autoclip_enabled = batch_cfg.get("autoclip_enabled", True)

    # ── AI 选点 ──
    await serial._set_phase(item, serial.PHASE_AUTOCLIP, "autoclip", 20)
    try:
        if autoclip_enabled:
            await serial._trigger_autoclip(episode_id, item, operator, autoclip_cfg)
            ok, status = await serial._wait_autoclip(episode_id)
            if not ok:
                raise RuntimeError(f"AI 选点未完成（{status}）")

            # 自动审核全部候选
            await serial._set_phase(item, serial.PHASE_REVIEW, "reviewing", 50)
            n = await serial._accept_all_candidates(episode_id)
            if n == 0:
                logger.warning("剧集 %s 选点未生成候选片段，继续整片切片兜底", episode_id)
        else:
            # 关闭 AI 选点：直接跳过选点阶段
            logger.info("剧集 %s 已关闭 AI 智能选点，跳过选点与自动审核", episode_id)
    except Exception as e:
        logger.exception("AI 选点失败 item=%s: %s", item_id, e)
        await serial._set_phase(item, serial.PHASE_AUTOCLIP, "failed", 0)
        await _update_item(item_id, error_message=f"AI 选点失败: {e}")
        return

    # ── 标记为「已选点待切片」，写入已选点池 ──
    await serial._set_phase(item, PHASE_SELECT_DONE, STATUS_READY_SLICE, 60)
    logger.info(
        "剧集 %s 选点完成，已入已选点池（batch=%s item=%s）", episode_id, batch_id, item_id
    )


# ─────────────────────────────────────────────────────────────────────
# 三、切片投递守护（Celery beat task batch_slice_dispatch）
# ─────────────────────────────────────────────────────────────────────
async def dispatch_ready_slices():
    """切片投递守护：扫描所有「已选点待切片」的 item，逐个投递切片任务。

    复用 run_slice → publish_slice_task 入 Redis Stream（slice:tasks:*），
    由 Go slice-worker 消费。投递后立即标记 item.phase='slicing' 防止重复投递（幂等）。
    支持 interval 通用区间检测（若开启）。
    """
    # 扫描已选点待切片的 item
    async with async_session_factory() as session:
        result = await session.execute(
            select(BatchSliceItem)
            .where(BatchSliceItem.phase == PHASE_SELECT_DONE)
            .where(BatchSliceItem.status == STATUS_READY_SLICE)
            .limit(100)
        )
        items = result.scalars().all()

    for item in items:
        batch = await _get_batch(str(item.batch_id))
        if batch is None:
            continue
        operator = await _get_operator(batch)
        if operator is None:
            await _update_item(item.id, status="failed", error_message="无法确定批次操作人")
            continue

        episode_id = str(item.episode_id) if item.episode_id else None
        if not episode_id:
            await _update_item(item.id, status="failed", error_message="缺少 episode_id")
            continue

        batch_cfg = batch.slice_config or {}
        interval_cfg = batch_cfg.get("interval_config") or {}
        interval_enabled = batch_cfg.get("interval_enabled", True)

        # ── 通用区间检测（可选，配置开启才执行）──
        if interval_enabled:
            await serial._set_phase(item, serial.PHASE_INTERVAL, "detecting", 55)
            try:
                detect_task_id = await serial._trigger_detect(
                    episode_id, item, operator, interval_cfg
                )
                if detect_task_id:
                    await _update_item(item.id, detect_task_id=uuid.UUID(detect_task_id))
                ok, dstatus = await serial._wait_detect(episode_id)
                if not ok:
                    raise RuntimeError(f"区间检测未完成（{dstatus}）")
            except Exception as e:
                logger.exception("区间检测失败 item=%s: %s", item.id, e)
                await serial._set_phase(item, serial.PHASE_INTERVAL, "failed", 0)
                await _update_item(item.id, error_message=f"区间检测失败: {e}")
                continue

        # ── 一键切片：标记 slicing 防止重复投递，再投递 ──
        await serial._set_phase(item, PHASE_SLICING, "slicing", 60)
        try:
            task_id = await serial._trigger_slice(
                episode_id, item, operator, batch.slice_config or {}
            )
            if task_id:
                await _update_item(item.id, slice_task_id=uuid.UUID(task_id))
            logger.info(
                "已投递切片任务 episode=%s item=%s slice_task=%s",
                episode_id, item.id, task_id,
            )
        except Exception as e:
            logger.exception("一键切片失败 item=%s: %s", item.id, e)
            # 投递失败：回退到 ready_slice，供下次轮询重试
            await serial._set_phase(item, PHASE_SELECT_DONE, STATUS_READY_SLICE, 60)
            await _update_item(item.id, error_message=f"一键切片失败: {e}")


# ─────────────────────────────────────────────────────────────────────
# 四、状态聚合（Celery beat task batch_aggregate）
# ─────────────────────────────────────────────────────────────────────
async def aggregate_batches():
    """状态聚合器：按 batch 维度聚合各 item 终态，幂等回填 BatchSlice 汇总。

    解耦模式下各剧集异步推进，done/failed/output_count 由本聚合器统一汇总。
    采用「终态优先 + 幂等」策略：completed_at 只写一次，输出数按完成项累计。
    """
    # 找出所有 running 状态的批次
    async with async_session_factory() as session:
        result = await session.execute(
            select(BatchSlice).where(BatchSlice.status == "running")
        )
        batches = result.scalars().all()

    for batch in batches:
        async with async_session_factory() as session:
            # 聚合各终态数量
            total = await session.execute(
                select(func.count()).select_from(BatchSliceItem).where(
                    BatchSliceItem.batch_id == batch.id
                )
            )
            total_count = total.scalar() or 0

            done_res = await session.execute(
                select(func.count()).select_from(BatchSliceItem).where(
                    BatchSliceItem.batch_id == batch.id,
                    BatchSliceItem.status == "completed",
                )
            )
            done_count = done_res.scalar() or 0

            failed_res = await session.execute(
                select(func.count()).select_from(BatchSliceItem).where(
                    BatchSliceItem.batch_id == batch.id,
                    BatchSliceItem.status.in_(["failed", "cancelled"]),
                )
            )
            failed_count = failed_res.scalar() or 0

            output_res = await session.execute(
                select(func.coalesce(func.sum(BatchSliceItem.output_count), 0)).where(
                    BatchSliceItem.batch_id == batch.id,
                    BatchSliceItem.status == "completed",
                )
            )
            output_count = output_res.scalar() or 0

        # 回填批次汇总
        fields = {
            "total": total_count,
            "done": done_count,
            "failed": failed_count,
            "output_count": output_count,
        }
        # 终态判定：全部项进入终态（completed/failed/cancelled）即批次完成
        terminal = done_count + failed_count
        if total_count > 0 and terminal == total_count:
            fields["status"] = "completed" if failed_count == 0 else "partial_failed"
            fields["completed_at"] = datetime.utcnow()
        await _update_batch(str(batch.id), **fields)

        logger.info(
            "聚合批次 %s：total=%s done=%s failed=%s outputs=%s",
            batch.id, total_count, done_count, failed_count, output_count,
        )
