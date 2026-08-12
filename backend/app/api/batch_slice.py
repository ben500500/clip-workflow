"""批量切片 API（三期）。

接收 JSON（剧名 + 剧集列表），按剧名找/建项目，逐集顺序执行
「AI 选点 → 自动审核 → 一键切片 → 删除源视频」，并提供进度与输出列表查询。
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
    BatchSlice,
    BatchSliceItem,
    User,
    user_can_access_all_materials,
)
from app.services import batch_slice_service as bsvc

logger = logging.getLogger(__name__)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────

class BatchEpisodeItem(BaseModel):
    """单个剧集：title 可选，path 为源视频地址（局域网/本地路径）。"""
    title: Optional[str] = None
    path: str


class DramaBatchRequest(BaseModel):
    """批量切片请求体：剧名 + 剧集列表 + 一键切片配置。"""
    drama: str = Field(..., description="剧名（按此找/建项目）")
    episodes: List[BatchEpisodeItem] = Field(..., min_length=1, description="剧集列表（按顺序处理）")
    # 一键切片配置快照（复用现有 SliceRunRequest 字段）
    slice_config: Optional[dict] = None
    # 是否删除源视频（默认 True 节约空间）
    delete_source: bool = True


class BatchSliceResponse(BaseModel):
    id: str
    name: Optional[str] = None
    drama_name: Optional[str] = None
    project_id: str
    status: str
    total: int
    done: int
    failed: int
    output_count: int
    delete_source: bool
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str


class BatchSliceItemResponse(BaseModel):
    id: str
    batch_id: str
    seq: Optional[int] = None
    title: Optional[str] = None
    source_path: Optional[str] = None
    source_file_key: Optional[str] = None
    episode_id: Optional[str] = None
    status: str
    progress: float
    message: Optional[str] = None
    error_message: Optional[str] = None
    output_count: int
    processed_at: Optional[str] = None
    created_at: str


class BatchOutputItem(BaseModel):
    file_name: Optional[str] = None
    file_key: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    resolution: Optional[str] = None
    presigned_url: Optional[str] = None


class BatchOutputResponse(BaseModel):
    seq: Optional[int] = None
    title: Optional[str] = None
    episode_id: Optional[str] = None
    status: str
    outputs: List[BatchOutputItem] = []


class BatchOutputsResponse(BaseModel):
    batch_id: str
    items: List[BatchOutputResponse]


# ──────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────

def _check_batch_access(batch: BatchSlice, current_user: User) -> bool:
    """数据隔离：管理员/素材专员可见全部，运营专员仅可见自己创建的批次。"""
    if user_can_access_all_materials(current_user):
        return True
    return batch.created_by == current_user.id


# ──────────────────────────────────────────────
# 端点
# ──────────────────────────────────────────────

@router.post("/batch-slice/run", response_model=BatchSliceResponse, status_code=201)
async def run_batch_slice(
    data: DramaBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """创建批量切片批次并按剧名建项目，随后异步逐集处理。

    返回批次 ID，前端通过 GET /batch-slice/{id} 轮询进度。
    """
    drama_name = (data.drama or "").strip()
    if not drama_name:
        raise HTTPException(status_code=400, detail="剧名不能为空")

    # 按剧名找/建项目
    project = await bsvc.find_or_create_project(db, drama_name, current_user.id)

    # 创建批次
    batch = BatchSlice(
        name=drama_name,
        drama_name=drama_name,
        project_id=project.id,
        slice_config=data.slice_config or {},
        status="pending",
        total=len(data.episodes),
        delete_source=data.delete_source,
        created_by=current_user.id,
    )
    db.add(batch)
    await db.flush()
    await db.refresh(batch)

    # 创建批次项（严格按 seq 顺序）
    for idx, ep in enumerate(data.episodes, start=1):
        item = BatchSliceItem(
            batch_id=batch.id,
            seq=idx,
            title=ep.title,
            source_path=ep.path,
            status="pending",
        )
        db.add(item)
    await db.commit()
    await db.refresh(batch)

    # 异步派发编排任务
    from app.celery.batch_slice_task import process_batch
    process_batch.delay(str(batch.id))

    return _to_batch_response(batch)


@router.get("/batch-slice/{batch_id}", response_model=BatchSliceResponse)
async def get_batch_slice(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询批次整体进度/状态。"""
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")

    batch = (await db.execute(select(BatchSlice).where(BatchSlice.id == bid))).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not _check_batch_access(batch, current_user):
        raise HTTPException(status_code=404, detail="Batch not found")
    return _to_batch_response(batch)


@router.get("/batch-slice/{batch_id}/items", response_model=List[BatchSliceItemResponse])
async def list_batch_items(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询批次项（每集处理状态）。"""
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")

    batch = (await db.execute(select(BatchSlice).where(BatchSlice.id == bid))).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not _check_batch_access(batch, current_user):
        raise HTTPException(status_code=404, detail="Batch not found")

    items = (
        await db.execute(
            select(BatchSliceItem)
            .where(BatchSliceItem.batch_id == bid)
            .order_by(BatchSliceItem.seq.asc().nullslast())
        )
    ).scalars().all()
    return [_to_item_response(it) for it in items]


@router.get("/batch-slice/{batch_id}/outputs", response_model=BatchOutputsResponse)
async def list_batch_outputs(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """输出列表：汇总整批所有切片成品（含下载地址）。"""
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")

    batch = (await db.execute(select(BatchSlice).where(BatchSlice.id == bid))).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not _check_batch_access(batch, current_user):
        raise HTTPException(status_code=404, detail="Batch not found")

    items = (
        await db.execute(
            select(BatchSliceItem)
            .where(BatchSliceItem.batch_id == bid)
            .order_by(BatchSliceItem.seq.asc().nullslast())
        )
    ).scalars().all()

    result_items = []
    for it in items:
        outputs = await bsvc.collect_item_outputs(str(it.id))
        result_items.append(BatchOutputResponse(
            seq=it.seq,
            title=it.title,
            episode_id=str(it.episode_id) if it.episode_id else None,
            status=it.status or "pending",
            outputs=[BatchOutputItem(**o) for o in outputs],
        ))
    return BatchOutputsResponse(batch_id=batch_id, items=result_items)


# ──────────────────────────────────────────────
# 序列化
# ──────────────────────────────────────────────

def _to_batch_response(batch: BatchSlice) -> BatchSliceResponse:
    return BatchSliceResponse(
        id=str(batch.id),
        name=batch.name,
        drama_name=batch.drama_name,
        project_id=str(batch.project_id),
        status=batch.status or "pending",
        total=batch.total or 0,
        done=batch.done or 0,
        failed=batch.failed or 0,
        output_count=batch.output_count or 0,
        delete_source=batch.delete_source,
        error_message=batch.error_message,
        started_at=bsvc.utc_iso(batch.started_at) if batch.started_at else None,
        completed_at=bsvc.utc_iso(batch.completed_at) if batch.completed_at else None,
        created_at=bsvc.utc_iso(batch.created_at) if batch.created_at else "",
    )


def _to_item_response(item: BatchSliceItem) -> BatchSliceItemResponse:
    return BatchSliceItemResponse(
        id=str(item.id),
        batch_id=str(item.batch_id),
        seq=item.seq,
        title=item.title,
        source_path=item.source_path,
        source_file_key=item.source_file_key,
        episode_id=str(item.episode_id) if item.episode_id else None,
        status=item.status or "pending",
        progress=item.progress or 0.0,
        message=item.message,
        error_message=item.error_message,
        output_count=item.output_count or 0,
        processed_at=bsvc.utc_iso(item.processed_at) if item.processed_at else None,
        created_at=bsvc.utc_iso(item.created_at) if item.created_at else "",
    )
