"""publish API 子域：发布批次（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持 `/publish/batches...` 不变。
本模块负责多运营者发布批次（R14）列表 / 详情 / 进度统计 / 创建（分配）。
"""
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import (
    PublishTask,
    PublishBatch,
    SliceOutput,
    User,
    user_can_access_all_materials,
)
from app.api.publish_common import _serialize_publish_task
from app.utils.helpers import utc_iso

router = APIRouter()


class PublishTaskAssignRequest(BaseModel):
    """多运营者发布批次：指定 视频号 + 运营者集合 + 策略（R14）。"""
    output_id: str
    platform: str
    account_id: Optional[str] = None
    operator_ids: Optional[List[str]] = None
    strategy: str = "even"  # even(均分) / round_robin(轮询) / assigned(指定)
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list] = None
    cover_file_key: Optional[str] = None
    mini_program_link: Optional[str] = None


class PublishBatchResponse(BaseModel):
    id: str
    created_by: Optional[str] = None
    strategy: Optional[str] = None
    account_id: Optional[str] = None
    total_items: int = 0
    status: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_publish_batch(batch: PublishBatch) -> dict:
    return {
        "id": str(batch.id),
        "created_by": str(batch.created_by) if batch.created_by else None,
        "strategy": batch.strategy,
        "account_id": str(batch.account_id) if batch.account_id else None,
        "total_items": batch.total_items or 0,
        "status": batch.status,
        "created_at": utc_iso(batch.created_at) if batch.created_at else "",
    }


@router.get("/publish/batches", response_model=List[PublishBatchResponse])
async def list_publish_batches(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """发布批次列表（operator 仅见自己发起的批次）."""
    query = select(PublishBatch).order_by(PublishBatch.created_at.desc())
    if current_user and not user_can_access_all_materials(current_user):
        query = query.where(PublishBatch.created_by == current_user.id)
    result = await db.execute(query)
    batches = result.scalars().all()
    return [_serialize_publish_batch(b) for b in batches]


@router.get("/publish/batches/{batch_id}", response_model=dict)
async def get_publish_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """批次详情（含其下任务列表，多运营者 R14）。"""
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")
    result = await db.execute(select(PublishBatch).where(PublishBatch.id == bid))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Publish batch not found")
    if current_user and not user_can_access_all_materials(current_user) and batch.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to view this batch")
    tasks = (
        await db.execute(
            select(PublishTask).where(PublishTask.batch_id == bid).order_by(PublishTask.created_at)
        )
    ).scalars().all()
    return {
        **_serialize_publish_batch(batch),
        "tasks": [_serialize_publish_task(t) for t in tasks],
    }


@router.get("/publish/batches/{batch_id}/stats", response_model=dict)
async def get_publish_batch_stats(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """批次进度统计（方向② 批量发布体验：pending/running/succeeded/failed/dead_letter 计数）。"""
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch ID format")
    result = await db.execute(select(PublishBatch).where(PublishBatch.id == bid))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Publish batch not found")
    if current_user and not user_can_access_all_materials(current_user) and batch.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to view this batch")

    rows = (
        await db.execute(
            select(PublishTask.status, func.count(PublishTask.id))
            .where(PublishTask.batch_id == bid)
            .group_by(PublishTask.status)
        )
    ).all()
    status_count = {status: cnt for status, cnt in rows}

    dead_letter_count = (
        await db.execute(
            select(func.count(PublishTask.id))
            .where(PublishTask.batch_id == bid, PublishTask.dead_letter == True)  # noqa: E712
        )
    ).scalar_one_or_none() or 0

    total = sum(status_count.values())
    return {
        "batch_id": str(batch.id),
        "total": total,
        "status": {
            "pending": status_count.get("pending", 0),
            "running": status_count.get("running", 0),
            "pending_confirm": status_count.get("pending_confirm", 0),
            "published": status_count.get("published", 0),
            "failed": status_count.get("failed", 0),
        },
        "dead_letter": dead_letter_count,
    }


@router.post("/publish/batches/assign", response_model=dict, status_code=201)
async def create_publish_batch(
    data: PublishTaskAssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """创建多运营者发布批次：按策略(均分/轮询/指定)把任务分配到运营者（R14）。

    单任务创建即绑定单一 operator，全程不迁移；重试/死信均在原 task 内。
    """
    # 解析目标账号
    account_id = uuid.UUID(data.account_id) if data.account_id else None
    # 解析运营者集合
    operator_ids = [uuid.UUID(oid) for oid in (data.operator_ids or [])]
    if not operator_ids:
        raise HTTPException(status_code=400, detail="operator_ids is required for multi-operator publish")

    # 校验视频源存在
    try:
        output_uuid = uuid.UUID(data.output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output_id format")
    output = (
        await db.execute(select(SliceOutput).where(SliceOutput.id == output_uuid))
    ).scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Slice output not found")

    # 发布护栏（多视频号素材去重）：一个账号只允许绑定一个变体，防止同素材原样发多号。
    # 若该账号已绑定同变体组（同素材）的其它变体，则拒绝创建发布批次。
    if account_id:
        from app.services.variant_service import guard_account_variant_unique
        guard = await guard_account_variant_unique(account_id, output_id=str(output_uuid))
        if not guard["allowed"]:
            raise HTTPException(status_code=409, detail=guard["reason"])

    # 创建批次
    batch = PublishBatch(
        created_by=current_user.id if current_user else None,
        strategy=data.strategy,
        account_id=account_id,
        status="pending",
    )
    db.add(batch)
    await db.flush()

    # 按策略分配运营者：每个 operator 一条（均分/轮询在当前批次粒度下等值；指定则用 operator_ids）
    strategy = data.strategy or "even"
    if strategy == "assigned":
        assignees = operator_ids
    else:  # even / round_robin
        assignees = operator_ids

    created_tasks = []
    for idx, op_id in enumerate(assignees):
        task = PublishTask(
            output_id=output_uuid,
            platform=data.platform,
            account_name=output.title,
            status="pending",
            title=data.title or output.title,
            description=data.description,
            tags=data.tags,
            cover_file_key=data.cover_file_key,
            mini_program_link=data.mini_program_link,
            require_manual_confirm=True,
            video_account_id=account_id,
            batch_id=batch.id,
            operator_id=op_id,
        )
        db.add(task)
        created_tasks.append(task)
        await db.flush()

    batch.total_items = len(created_tasks)
    await db.flush()
    await db.refresh(batch)
    return {
        **_serialize_publish_batch(batch),
        "tasks": [_serialize_publish_task(t) for t in created_tasks],
    }
