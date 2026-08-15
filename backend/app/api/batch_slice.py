"""批量切片工作流 API（三期方案）。

开放接口：接收 JSON（剧名 + 剧集地址列表）+ 一键切片配置，
按剧名查找/创建项目，再按列表顺序逐集完成「AI 选点 → 自动审核 → 一键切片 → 删除源视频」，
最后汇总生成一份输出列表（含每个切片成品的下载地址）。
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import (
    User,
    BatchSlice,
    BatchSliceItem,
    SliceTask,
    SliceOutput,
)
from app.services.data_scope import check_project_access_by_id
from app.services.minio_service import get_presigned_url
from app.config import settings
from app.utils.helpers import utc_iso

logger = logging.getLogger(__name__)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class BatchEpisodeItem(BaseModel):
    """列表中的一集。"""
    title: Optional[str] = None   # 剧集标题（可选，缺省用文件名）
    path: str = Field(..., description="视频文件路径（局域网/本地可访问路径）")


class BatchSliceRunRequest(BaseModel):
    """批量切片请求体。"""
    drama: str = Field(..., description="剧名（按此查找/创建项目）")
    episodes: List[BatchEpisodeItem] = Field(..., description="剧集列表，按顺序处理")
    slice_config: Optional[dict] = Field(
        default_factory=dict,
        description="一键切片配置（复用剧集详情页的配置项，整批统一生效）："
                    "含切片配置、AI 智能选点配置(autoclip_config/autoclip_enabled)、"
                    "通用区间检测配置(interval_config/interval_enabled)、"
                    "流水线模式 pipeline_mode(serial|decoupled，默认 serial 串行)等",
    )
    auto_delete_source: bool = Field(True, description="是否处理完成后删除源视频（节约空间）")


class BatchSliceRunResponse(BaseModel):
    batch_id: str
    total: int
    message: str


class BatchSliceItemResponse(BaseModel):
    id: str
    seq: int
    title: Optional[str] = None
    source_path: Optional[str] = None
    file_name: Optional[str] = None
    episode_id: Optional[str] = None
    slice_task_id: Optional[str] = None
    autoclip_run_id: Optional[str] = None
    detect_task_id: Optional[str] = None
    status: str
    phase: Optional[str] = None
    progress: float
    output_count: int
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

    model_config = {"from_attributes": True}


class BatchSliceResponse(BaseModel):
    id: str
    name: Optional[str] = None
    project_id: Optional[str] = None
    slice_config: Optional[dict] = None
    status: str
    total: int
    done: int
    failed: int
    output_count: int
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    model_config = {"from_attributes": True}


class BatchSliceOutputItem(BaseModel):
    """输出列表中的一项（一个切片成品）。"""
    seq: int
    title: Optional[str] = None
    episode_id: Optional[str] = None
    slice_task_id: Optional[str] = None
    item_status: str
    output: Optional[dict] = None


class BatchSliceOutputResponse(BaseModel):
    batch_id: str
    items: List[BatchSliceOutputItem]


# ──────────────────────────────────────────────
# 序列化辅助
# ──────────────────────────────────────────────


def _serialize_batch(batch: BatchSlice) -> dict:
    return {
        "id": str(batch.id),
        "name": batch.name,
        "project_id": str(batch.project_id) if batch.project_id else None,
        "slice_config": batch.slice_config or {},
        "status": batch.status,
        "total": batch.total or 0,
        "done": batch.done or 0,
        "failed": batch.failed or 0,
        "output_count": batch.output_count or 0,
        "error_message": batch.error_message,
        "created_at": utc_iso(batch.created_at) if batch.created_at else "",
        "started_at": utc_iso(batch.started_at) if batch.started_at else None,
        "completed_at": utc_iso(batch.completed_at) if batch.completed_at else None,
    }


def _serialize_item(item: BatchSliceItem) -> dict:
    return {
        "id": str(item.id),
        "seq": item.seq,
        "title": item.title,
        "source_path": item.source_path,
        "file_name": item.file_name,
        "episode_id": str(item.episode_id) if item.episode_id else None,
        "slice_task_id": str(item.slice_task_id) if item.slice_task_id else None,
        "autoclip_run_id": str(item.autoclip_run_id) if item.autoclip_run_id else None,
        "detect_task_id": str(item.detect_task_id) if item.detect_task_id else None,
        "status": item.status,
        "phase": item.phase,
        "progress": item.progress or 0.0,
        "output_count": item.output_count or 0,
        "error_message": item.error_message,
        "created_at": utc_iso(item.created_at) if item.created_at else "",
        "completed_at": utc_iso(item.completed_at) if item.completed_at else None,
    }


async def _load_batch_owned(db: AsyncSession, batch_id: str, current_user: User) -> BatchSlice:
    """加载批次并校验数据隔离权限。"""
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="batch_id 格式不合法")
    result = await db.execute(select(BatchSlice).where(BatchSlice.id == bid))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    # 数据隔离：项目归属校验
    if batch.project_id:
        await check_project_access_by_id(db, batch.project_id, current_user)
    return batch


# ──────────────────────────────────────────────
# API
# ──────────────────────────────────────────────


@router.post("/batch-slice/run", response_model=BatchSliceRunResponse, status_code=201)
async def run_batch_slice(
    data: BatchSliceRunRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """开放接口：接收 JSON（剧名+剧集地址列表）+ 一键切片配置，创建批次并异步按序处理。"""
    if not data.drama or not data.drama.strip():
        raise HTTPException(status_code=400, detail="剧名不能为空")
    if not data.episodes:
        raise HTTPException(status_code=400, detail="剧集列表不能为空")

    # 创建批次记录（先不绑定项目，由后台任务按剧名查找/创建）
    batch = BatchSlice(
        name=data.drama.strip(),
        slice_config=data.slice_config or {},
        status="pending",
        total=len(data.episodes),
        created_by=current_user.id,
    )
    db.add(batch)
    await db.flush()

    # 创建批次项
    for idx, ep in enumerate(data.episodes, start=1):
        file_name = ep.path.split("/")[-1] if ep.path else ""
        item = BatchSliceItem(
            batch_id=batch.id,
            seq=idx,
            title=ep.title or file_name,
            source_path=ep.path,
            file_name=file_name,
            status="pending",
        )
        db.add(item)
    await db.commit()
    await db.refresh(batch)

    # 派发后台处理任务（default 队列）
    try:
        from app.celery.tasks import batch_slice_task
        batch_slice_task.delay(str(batch.id))
    except Exception as e:
        logger.error("派发批量切片任务失败: %s", e)
        batch.status = "failed"
        batch.error_message = f"派发后台任务失败: {e}"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"派发后台任务失败: {e}")

    return BatchSliceRunResponse(
        batch_id=str(batch.id),
        total=len(data.episodes),
        message=f"已创建批次 {data.drama}（{len(data.episodes)} 集），正在按序处理…",
    )


@router.get("/batch-slice", response_model=List[BatchSliceResponse])
async def list_batch_slices(
    page: int = 1,
    page_size: int = 20,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """批量切片批次历史列表。"""
    query = select(BatchSlice).order_by(BatchSlice.created_at.desc())
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    batches = result.scalars().all()
    return [_serialize_batch(b) for b in batches]


@router.get("/batch-slice/{batch_id}", response_model=BatchSliceResponse)
async def get_batch_slice(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """批次整体进度/状态。"""
    batch = await _load_batch_owned(db, batch_id, current_user)
    return _serialize_batch(batch)


@router.get("/batch-slice/{batch_id}/items", response_model=List[BatchSliceItemResponse])
async def get_batch_items(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """批次项列表（每集处理状态）。"""
    await _load_batch_owned(db, batch_id, current_user)
    result = await db.execute(
        select(BatchSliceItem)
        .where(BatchSliceItem.batch_id == uuid.UUID(batch_id))
        .order_by(BatchSliceItem.seq.asc())
    )
    items = result.scalars().all()
    return [_serialize_item(i) for i in items]


@router.get("/batch-slice/{batch_id}/outputs", response_model=BatchSliceOutputResponse)
async def get_batch_outputs(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """输出列表：汇总整批所有切片成品（含下载地址）。"""
    batch = await _load_batch_owned(db, batch_id, current_user)
    result = await db.execute(
        select(BatchSliceItem)
        .where(BatchSliceItem.batch_id == uuid.UUID(batch_id))
        .order_by(BatchSliceItem.seq.asc())
    )
    items = result.scalars().all()

    out_items: List[BatchSliceOutputItem] = []
    for item in items:
        # 每个批次项最多关联一个 SliceTask，取其 outputs
        outputs: list[dict] = []
        if item.slice_task_id:
            res = await db.execute(
                select(SliceOutput).where(SliceOutput.task_id == item.slice_task_id)
            )
            slice_outputs = res.scalars().all()
            for so in slice_outputs:
                url = None
                if so.file_key:
                    url = await get_presigned_url(
                        settings.MINIO_BUCKET_SLICED,
                        so.file_key,
                        expires_seconds=3600,
                    )
                outputs.append({
                    "id": str(so.id),
                    "file_name": so.file_name,
                    "file_key": so.file_key,
                    "duration": so.duration,
                    "file_size": so.file_size,
                    "resolution": so.resolution,
                    "presigned_url": url,
                })
        # 若批次项直接关联了多个切片任务（历史遗留），也可兜底扫描该 episode
        if not outputs and item.episode_id:
            res = await db.execute(
                select(SliceTask).where(SliceTask.episode_id == item.episode_id)
            )
            tasks = res.scalars().all()
            for t in tasks:
                res2 = await db.execute(select(SliceOutput).where(SliceOutput.task_id == t.id))
                for so in res2.scalars().all():
                    url = None
                    if so.file_key:
                        url = await get_presigned_url(
                            settings.MINIO_BUCKET_SLICED, so.file_key, expires_seconds=3600
                        )
                    outputs.append({
                        "id": str(so.id),
                        "file_name": so.file_name,
                        "file_key": so.file_key,
                        "duration": so.duration,
                        "file_size": so.file_size,
                        "resolution": so.resolution,
                        "presigned_url": url,
                    })

        out_items.append(
            BatchSliceOutputItem(
                seq=item.seq,
                title=item.title,
                episode_id=str(item.episode_id) if item.episode_id else None,
                slice_task_id=str(item.slice_task_id) if item.slice_task_id else None,
                item_status=item.status,
                output=outputs[0] if len(outputs) == 1 else ({"outputs": outputs, "count": len(outputs)} if outputs else None),
            )
        )

    return BatchSliceOutputResponse(batch_id=str(batch.id), items=out_items)


@router.post("/batch-slice/{batch_id}/retry", response_model=BatchSliceRunResponse)
async def retry_batch_slice(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """重试批次中失败的项（成功项跳过）。"""
    batch = await _load_batch_owned(db, batch_id, current_user)
    # 重置失败项状态
    result = await db.execute(
        select(BatchSliceItem).where(
            BatchSliceItem.batch_id == batch.id,
            BatchSliceItem.status == "failed",
        )
    )
    failed_items = result.scalars().all()
    for it in failed_items:
        it.status = "pending"
        it.error_message = None
    await db.commit()
    batch.status = "pending"
    await db.commit()

    if failed_items:
        from app.celery.tasks import batch_slice_task
        batch_slice_task.delay(str(batch.id))

    return BatchSliceRunResponse(
        batch_id=str(batch.id),
        total=len(failed_items),
        message=f"已重试 {len(failed_items)} 个失败项",
    )


@router.post("/batch-slice/{batch_id}/cancel", response_model=dict)
async def cancel_batch_slice(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """取消整批（标记未开始项为 cancelled）。"""
    batch = await _load_batch_owned(db, batch_id, current_user)
    if batch.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="批次已结束，无法取消")
    result = await db.execute(
        select(BatchSliceItem).where(
            BatchSliceItem.batch_id == batch.id,
            BatchSliceItem.status.in_(["pending", "uploading", "autoclip", "reviewing", "slicing", "deleting"]),
        )
    )
    for it in result.scalars().all():
        it.status = "cancelled"
    await db.commit()
    batch.status = "cancelled"
    batch.completed_at = datetime.utcnow()
    await db.commit()
    return {"batch_id": str(batch.id), "message": "批次已取消"}
