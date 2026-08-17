"""视频号登记台账 API（Issue #93）。

- /channel-accounts          台账 CRUD（列表支持筛选，可关联现有发布账号）
- /channel-accounts/{id}/operators  运营者多对多增删

登记信息与现有发布账号矩阵（video_accounts）通过 video_account_id 关联，
打通「登记台账」与「发布/矩阵」流程。
"""
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import ChannelAccount, ChannelOperator, User, user_can_access_all_materials
from app.utils.helpers import utc_iso

router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────
class ChannelOperatorIn(BaseModel):
    """运营者输入：可从系统用户选（operator_id），或手填外部姓名（operator_name）。"""
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None


class ChannelAccountCreate(BaseModel):
    channel_name: str
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None      # personal / enterprise
    verify_name: Optional[str] = None
    register_date: Optional[str] = None    # YYYY-MM-DD
    cooperation_mode: Optional[str] = None # IAA / IAP
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None # 关联现有发布账号
    remark: Optional[str] = None
    enabled: bool = True
    operators: List[ChannelOperatorIn] = []


class ChannelAccountUpdate(BaseModel):
    channel_name: Optional[str] = None
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_mode: Optional[str] = None
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None
    remark: Optional[str] = None
    enabled: Optional[bool] = None
    operators: Optional[List[ChannelOperatorIn]] = None


class ChannelOperatorResponse(BaseModel):
    id: str
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None
    created_at: str


class ChannelAccountResponse(BaseModel):
    id: str
    channel_name: str
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_mode: Optional[str] = None
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None
    video_account_name: Optional[str] = None
    remark: Optional[str] = None
    enabled: bool = True
    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    operators: List[ChannelOperatorResponse] = []


# ── 序列化 ─────────────────────────────────────────────────────
def _serialize_operator(op: ChannelOperator) -> dict:
    return {
        "id": str(op.id),
        "operator_id": str(op.operator_id) if op.operator_id else None,
        "operator_name": op.operator_name,
        "created_at": utc_iso(op.created_at) if op.created_at else "",
    }


def _parse_date(s: Optional[str]):
    """将 'YYYY-MM-DD' 字符串转为 date 对象，容错空值。"""
    if not s:
        return None
    from datetime import date
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {s}")


def _parse_uuid(s: Optional[str]):
    if not s:
        return None
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {s}")


def _serialize_channel(channel: ChannelAccount, video_account_name: Optional[str] = None) -> dict:
    return {
        "id": str(channel.id),
        "channel_name": channel.channel_name,
        "wechat_id": channel.wechat_id,
        "verify_type": channel.verify_type,
        "verify_name": channel.verify_name,
        "register_date": channel.register_date.isoformat() if channel.register_date else None,
        "cooperation_mode": channel.cooperation_mode,
        "coop_company": channel.coop_company,
        "video_account_id": str(channel.video_account_id) if channel.video_account_id else None,
        "video_account_name": video_account_name,
        "remark": channel.remark,
        "enabled": channel.enabled if channel.enabled is not None else True,
        "created_by": str(channel.created_by) if channel.created_by else None,
        "created_at": utc_iso(channel.created_at) if channel.created_at else "",
        "updated_at": utc_iso(channel.updated_at) if channel.updated_at else "",
        "operators": [_serialize_operator(op) for op in channel.operators],
    }


async def _load_video_account_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict:
    """批量查询发布账号名（video_accounts），用于列表展示关联账号名。"""
    if not ids:
        return {}
    from app.models.models import VideoAccount
    rows = await db.execute(select(VideoAccount).where(VideoAccount.id.in_(ids)))
    return {str(acc.id): acc.account_name for acc in rows.scalars().all()}


# ── 路由 ──────────────────────────────────────────────────────
@router.get("/channel-accounts", response_model=List[ChannelAccountResponse])
async def list_channel_accounts(
    verify_type: Optional[str] = Query(None),
    cooperation_mode: Optional[str] = Query(None),
    video_account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """视频号台账列表（可按实名类型/合作模式/关联账号筛选）。"""
    filters = []
    if verify_type:
        filters.append(ChannelAccount.verify_type == verify_type)
    if cooperation_mode:
        filters.append(ChannelAccount.cooperation_mode == cooperation_mode)
    if video_account_id:
        filters.append(ChannelAccount.video_account_id == uuid.UUID(video_account_id))

    query = (
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .order_by(ChannelAccount.channel_name)
    )
    if filters:
        query = query.where(and_(*filters))
    result = await db.execute(query)
    channels = result.scalars().all()

    # 批量补充关联发布账号名
    va_ids = {c.video_account_id for c in channels if c.video_account_id}
    va_names = await _load_video_account_names(db, va_ids)

    return [
        _serialize_channel(c, va_names.get(str(c.video_account_id)) if c.video_account_id else None)
        for c in channels
    ]


@router.get("/channel-accounts/{channel_id}", response_model=ChannelAccountResponse)
async def get_channel_account(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """单条台账详情（含运营者）。"""
    cid = _parse_uuid(channel_id)
    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == cid)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel account not found")

    va_name = None
    if channel.video_account_id:
        names = await _load_video_account_names(db, {channel.video_account_id})
        va_name = names.get(str(channel.video_account_id))
    return _serialize_channel(channel, va_name)


@router.post("/channel-accounts", response_model=ChannelAccountResponse, status_code=201)
async def create_channel_account(
    data: ChannelAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增视频号台账（可带运营者，可关联现有发布账号）。"""
    channel = ChannelAccount(
        channel_name=data.channel_name,
        wechat_id=data.wechat_id,
        verify_type=data.verify_type,
        verify_name=data.verify_name,
        register_date=_parse_date(data.register_date),
        cooperation_mode=data.cooperation_mode,
        coop_company=data.coop_company,
        video_account_id=_parse_uuid(data.video_account_id),
        remark=data.remark,
        enabled=data.enabled,
        created_by=current_user.id if current_user else None,
    )
    db.add(channel)
    await db.flush()

    for op in data.operators:
        db.add(ChannelOperator(
            channel_account_id=channel.id,
            operator_id=_parse_uuid(op.operator_id),
            operator_name=op.operator_name or (str(op.operator_id) if op.operator_id else None),
        ))
    await db.flush()
    # 重载关联运营者
    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == channel.id)
    )
    channel = result.scalar_one()
    va_name = None
    if channel.video_account_id:
        names = await _load_video_account_names(db, {channel.video_account_id})
        va_name = names.get(str(channel.video_account_id))
    return _serialize_channel(channel, va_name)


@router.put("/channel-accounts/{channel_id}", response_model=ChannelAccountResponse)
async def update_channel_account(
    channel_id: str,
    data: ChannelAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新台账。operators 若传入则整体替换运营者列表。"""
    cid = _parse_uuid(channel_id)
    result = await db.execute(select(ChannelAccount).where(ChannelAccount.id == cid))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel account not found")

    payload = data.model_dump(exclude_unset=True)
    operators = payload.pop("operators", None)

    for field, value in payload.items():
        if field == "register_date":
            setattr(channel, field, _parse_date(value))
        elif field == "video_account_id":
            setattr(channel, field, _parse_uuid(value))
        else:
            setattr(channel, field, value)

    # 整体替换运营者
    if operators is not None:
        await db.execute(delete(ChannelOperator).where(ChannelOperator.channel_account_id == channel.id))
        for op in operators:
            db.add(ChannelOperator(
                channel_account_id=channel.id,
                operator_id=_parse_uuid(op.get("operator_id")),
                operator_name=op.get("operator_name") or (op.get("operator_id") if op.get("operator_id") else None),
            ))

    await db.flush()
    result = await db.execute(
        select(ChannelAccount)
        .options(selectinload(ChannelAccount.operators))
        .where(ChannelAccount.id == channel.id)
    )
    channel = result.scalar_one()
    va_name = None
    if channel.video_account_id:
        names = await _load_video_account_names(db, {channel.video_account_id})
        va_name = names.get(str(channel.video_account_id))
    return _serialize_channel(channel, va_name)


@router.delete("/channel-accounts/{channel_id}", status_code=204)
async def delete_channel_account(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除台账（级联删除运营者）。"""
    cid = _parse_uuid(channel_id)
    result = await db.execute(select(ChannelAccount).where(ChannelAccount.id == cid))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel account not found")
    await db.delete(channel)
    await db.flush()
    return None
