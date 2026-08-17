"""渠道台账 API 子域（视频号台账）。

视频号台账（Issue #93）：渠道侧商务登记，与发布通道账号库（/publish/video-accounts）
解耦。台账通过 `video_account_id` 软外键关联发布通道账号（先登记后关联）。
运营者子表支持多人运营（operator_user_id / operator_name 双轨 + operator_phone 兜底）。

URL 前缀统一为 `/api/channel-accounts...`，走 `_protected_routers` 统一鉴权；
数据隔离沿用 `user_can_access_all_materials` + created_by RBAC 模式。
"""
import uuid
from datetime import date
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.models import ChannelAccount, ChannelOperator, User, user_can_access_all_materials
from app.utils.helpers import utc_iso

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic 入参/出参模型
# ──────────────────────────────────────────────

class ChannelOperatorCreate(BaseModel):
    operator_user_id: Optional[str] = None   # 软外键→users
    operator_name: Optional[str] = None      # 外部手填姓名
    operator_phone: Optional[str] = None     # 外部手填电话（联系兜底）

    @model_validator(mode="after")
    def _check_identity(self):
        # 服务层校验：operator_user_id 与 operator_name 至少填一个（友好报错）
        if not self.operator_user_id and not self.operator_name:
            raise ValueError("operator_user_id 与 operator_name 至少填写一个")
        return self


class ChannelOperatorUpdate(BaseModel):
    operator_user_id: Optional[str] = None
    operator_name: Optional[str] = None
    operator_phone: Optional[str] = None


class ChannelOperatorResponse(BaseModel):
    id: str
    channel_account_id: str
    operator_user_id: Optional[str] = None
    operator_name: Optional[str] = None
    operator_phone: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class ChannelAccountCreate(BaseModel):
    channel_name: str = Field(..., min_length=1, max_length=100)
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None          # personal / enterprise
    verify_name: Optional[str] = None
    register_date: Optional[date] = None
    cooperation_modes: Optional[List[str]] = None   # ["IAA"] / ["IAP"] / ["IAA","IAP"]
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None     # 软外键，先登记后关联，可空
    remark: Optional[str] = None
    enabled: bool = True
    operators: Optional[List[ChannelOperatorCreate]] = None


class ChannelAccountUpdate(BaseModel):
    channel_name: Optional[str] = Field(None, min_length=1, max_length=100)
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None
    verify_name: Optional[str] = None
    register_date: Optional[date] = None
    cooperation_modes: Optional[List[str]] = None
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None
    remark: Optional[str] = None
    enabled: Optional[bool] = None


class ChannelAccountResponse(BaseModel):
    id: str
    channel_name: str
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_modes: Optional[List[str]] = None
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None
    remark: Optional[str] = None
    enabled: bool = True
    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    operators: List[ChannelOperatorResponse] = []

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# 序列化工具
# ──────────────────────────────────────────────

def _serialize_operator(op: ChannelOperator) -> dict:
    return {
        "id": str(op.id),
        "channel_account_id": str(op.channel_account_id),
        "operator_user_id": str(op.operator_user_id) if op.operator_user_id else None,
        "operator_name": op.operator_name,
        "operator_phone": op.operator_phone,
        "created_at": utc_iso(op.created_at) if op.created_at else "",
    }


def _serialize_channel(acc: ChannelAccount) -> dict:
    return {
        "id": str(acc.id),
        "channel_name": acc.channel_name,
        "wechat_id": acc.wechat_id,
        "verify_type": acc.verify_type,
        "verify_name": acc.verify_name,
        "register_date": acc.register_date.isoformat() if acc.register_date else None,
        "cooperation_modes": acc.cooperation_modes or [],
        "coop_company": acc.coop_company,
        "video_account_id": str(acc.video_account_id) if acc.video_account_id else None,
        "remark": acc.remark,
        "enabled": acc.enabled if acc.enabled is not None else True,
        "created_by": str(acc.created_by) if acc.created_by else None,
        "created_at": utc_iso(acc.created_at) if acc.created_at else "",
        "updated_at": utc_iso(acc.updated_at) if acc.updated_at else "",
        "operators": [_serialize_operator(op) for op in (acc.operators or [])],
    }


def _rbac_filter(uid: uuid.UUID) -> "tuple":
    """非管理员的数据隔离过滤：本人创建 OR 本人是运营者之一。"""
    return (ChannelAccount.created_by == uid) | (
        ChannelAccount.operators.any(ChannelOperator.operator_user_id == uid)
    )


# ──────────────────────────────────────────────
# 台账 CRUD
# ──────────────────────────────────────────────

@router.get("/channel-accounts", response_model=List[ChannelAccountResponse])
async def list_channel_accounts(
    verify_type: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """台账列表（可按认证类型/启用状态过滤；RBAC：operator 仅见自己创建的或参与的）."""
    query = select(ChannelAccount).options(selectinload(ChannelAccount.operators))
    filters = []
    if verify_type:
        filters.append(ChannelAccount.verify_type == verify_type)
    if enabled is not None:
        filters.append(ChannelAccount.enabled == enabled)
    if filters:
        query = query.where(and_(*filters))
    if current_user and not user_can_access_all_materials(current_user):
        query = query.where(_rbac_filter(current_user.id))
    query = query.order_by(ChannelAccount.created_at.desc())
    result = await db.execute(query)
    accounts = result.scalars().unique().all()
    return [_serialize_channel(a) for a in accounts]


@router.get("/channel-accounts/{account_id}", response_model=ChannelAccountResponse)
async def get_channel_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """台账详情（含运营者列表）。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    if current_user and not user_can_access_all_materials(current_user):
        allowed = (acc.created_by == current_user.id) or any(
            (op.operator_user_id == current_user.id) for op in (acc.operators or [])
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="No permission to view this channel account")
    return _serialize_channel(acc)


@router.post("/channel-accounts", response_model=ChannelAccountResponse, status_code=201)
async def create_channel_account(
    data: ChannelAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增台账（先登记；video_account_id 可空，后续 PUT 补绑；可携带运营者）。"""
    acc = ChannelAccount(
        channel_name=data.channel_name,
        wechat_id=data.wechat_id,
        verify_type=data.verify_type,
        verify_name=data.verify_name,
        register_date=data.register_date,
        cooperation_modes=data.cooperation_modes or [],
        coop_company=data.coop_company,
        video_account_id=uuid.UUID(data.video_account_id) if data.video_account_id else None,
        remark=data.remark,
        enabled=data.enabled,
        created_by=current_user.id if current_user else None,
    )
    if data.operators:
        for op in data.operators:
            acc.operators.append(
                ChannelOperator(
                    operator_user_id=uuid.UUID(op.operator_user_id) if op.operator_user_id else None,
                    operator_name=op.operator_name,
                    operator_phone=op.operator_phone,
                )
            )
    db.add(acc)
    await db.flush()
    await db.refresh(acc)
    return _serialize_channel(acc)


@router.put("/channel-accounts/{account_id}", response_model=ChannelAccountResponse)
async def update_channel_account(
    account_id: str,
    data: ChannelAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新台账（含补绑 video_account_id）。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    if current_user and not user_can_access_all_materials(current_user):
        allowed = (acc.created_by == current_user.id) or any(
            (op.operator_user_id == current_user.id) for op in (acc.operators or [])
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="No permission to update this channel account")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "video_account_id":
            setattr(acc, field, uuid.UUID(value) if value else None)
            continue
        setattr(acc, field, value)

    await db.flush()
    await db.refresh(acc)
    return _serialize_channel(acc)


@router.delete("/channel-accounts/{account_id}", status_code=204)
async def delete_channel_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除台账（级联删除运营者子表）。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    if current_user and not user_can_access_all_materials(current_user):
        allowed = (acc.created_by == current_user.id) or any(
            (op.operator_user_id == current_user.id) for op in (acc.operators or [])
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="No permission to delete this channel account")

    await db.delete(acc)
    await db.flush()
    return None


# ──────────────────────────────────────────────
# 运营者子资源
# ──────────────────────────────────────────────

async def _get_owned_channel(account_id: str, current_user: User, db: AsyncSession) -> ChannelAccount:
    """取台账并做 RBAC 校验（供运营者子资源复用）。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")
    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    if current_user and not user_can_access_all_materials(current_user):
        allowed = (acc.created_by == current_user.id) or any(
            (op.operator_user_id == current_user.id) for op in (acc.operators or [])
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="No permission to access this channel account")
    return acc


@router.post("/channel-accounts/{account_id}/operators", response_model=ChannelOperatorResponse, status_code=201)
async def create_channel_operator(
    account_id: str,
    data: ChannelOperatorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """为台账新增运营者（operator_user_id / operator_name 至少填一个，服务层已校验）。"""
    acc = await _get_owned_channel(account_id, current_user, db)
    op = ChannelOperator(
        channel_account_id=acc.id,
        operator_user_id=uuid.UUID(data.operator_user_id) if data.operator_user_id else None,
        operator_name=data.operator_name,
        operator_phone=data.operator_phone,
    )
    db.add(op)
    await db.flush()
    await db.refresh(op)
    return _serialize_operator(op)


@router.put("/channel-accounts/{account_id}/operators/{op_id}", response_model=ChannelOperatorResponse)
async def update_channel_operator(
    account_id: str,
    op_id: str,
    data: ChannelOperatorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新运营者。"""
    await _get_owned_channel(account_id, current_user, db)
    try:
        oid = uuid.UUID(op_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid operator ID format")

    result = await db.execute(
        select(ChannelOperator).where(
            ChannelOperator.id == oid,
            ChannelOperator.channel_account_id == uuid.UUID(account_id),
        )
    )
    op = result.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Channel operator not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "operator_user_id":
            setattr(op, field, uuid.UUID(value) if value else None)
            continue
        setattr(op, field, value)

    # 服务层校验：operator_user_id 与 operator_name 至少填一个（与 CREATE 一致）
    if not op.operator_user_id and not op.operator_name:
        raise HTTPException(
            status_code=422,
            detail="operator_user_id 与 operator_name 至少填写一个",
        )

    await db.flush()
    await db.refresh(op)
    return _serialize_operator(op)


@router.delete("/channel-accounts/{account_id}/operators/{op_id}", status_code=204)
async def delete_channel_operator(
    account_id: str,
    op_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除运营者。"""
    await _get_owned_channel(account_id, current_user, db)
    try:
        oid = uuid.UUID(op_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid operator ID format")

    result = await db.execute(
        select(ChannelOperator).where(
            ChannelOperator.id == oid,
            ChannelOperator.channel_account_id == uuid.UUID(account_id),
        )
    )
    op = result.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Channel operator not found")

    await db.delete(op)
    await db.flush()
    return None
