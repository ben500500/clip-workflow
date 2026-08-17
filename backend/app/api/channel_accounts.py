"""publish API 子域：视频号台账（ChannelAccount / ChannelOperator）。

登记视频号工商/合作信息，与发布账号库（video_accounts）解耦，仅通过
`video_account_id` 软关联。数据隔离：列表沿用 `user_can_access_all_materials`
RBAC 过滤（operator 仅见自己 created_by 的台账）。
"""
import uuid
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import (
    AdMetric,
    ChannelAccount,
    ChannelOperator,
    User,
    VideoMetric,
    user_can_access_all_materials,
)
from app.utils.helpers import utc_iso

router = APIRouter()


# ---------- 合作模式枚举（IAA / IAP） ----------
CooperationMode = Literal["IAA", "IAP"]


# ---------- Pydantic Schemas ----------

class OperatorCreate(BaseModel):
    operator_user_id: Optional[str] = None   # 现有用户 FK（软）
    operator_name: Optional[str] = None      # 外部手填姓名
    operator_phone: Optional[str] = None     # 外部手填电话


class OperatorUpdate(BaseModel):
    operator_user_id: Optional[str] = None
    operator_name: Optional[str] = None
    operator_phone: Optional[str] = None


class OperatorResponse(BaseModel):
    id: str
    channel_account_id: str
    operator_user_id: Optional[str] = None
    operator_name: Optional[str] = None
    operator_phone: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class ChannelAccountCreate(BaseModel):
    channel_name: str
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None        # personal / enterprise
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_modes: Optional[List[CooperationMode]] = None   # ["IAA","IAP"]
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None   # 可空，先登记后关联
    remark: Optional[str] = None
    enabled: bool = True


class ChannelAccountUpdate(BaseModel):
    channel_name: Optional[str] = None
    wechat_id: Optional[str] = None
    verify_type: Optional[str] = None
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_modes: Optional[List[CooperationMode]] = None
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
    operators: List[OperatorResponse] = Field(default_factory=list)
    # 与报表域关联聚合（按 video_account_id 汇总，缺省 0）
    report_play_count: int = 0
    report_attributed_revenue: float = 0
    report_ad_revenue: float = 0

    model_config = {"from_attributes": True}


# ---------- Serializers ----------

def _serialize_operator(op: ChannelOperator) -> dict:
    return {
        "id": str(op.id),
        "channel_account_id": str(op.channel_account_id),
        "operator_user_id": str(op.operator_user_id) if op.operator_user_id else None,
        "operator_name": op.operator_name,
        "operator_phone": op.operator_phone,
        "created_at": utc_iso(op.created_at) if op.created_at else "",
    }


async def _load_report_metrics(db: AsyncSession, video_account_ids: List[uuid.UUID]) -> dict:
    """按 video_account_id 批量聚合报表域数据，返回 {account_id: {play_count, attributed_revenue, ad_revenue}}.

    复用现有看板域的聚合语义：
    - video_metrics.play_count / attributed_revenue（视频跑量 + 归因收益）
    - ad_metrics.revenue（广告变现 IAA 收益）
    仅对已关联发布账号（video_account_id 非空）做聚合；未关联的返回全 0。
    """
    result = {
        str(aid): {"play_count": 0, "attributed_revenue": 0.0, "ad_revenue": 0.0}
        for aid in video_account_ids
    }
    if not video_account_ids:
        return result

    video_rows = await db.execute(
        select(
            VideoMetric.account_id,
            func.coalesce(func.sum(VideoMetric.play_count), 0),
            func.coalesce(func.sum(VideoMetric.attributed_revenue), 0),
        )
        .where(VideoMetric.account_id.in_(video_account_ids))
        .group_by(VideoMetric.account_id)
    )
    for row in video_rows.all():
        aid = str(row[0])
        if aid in result:
            result[aid]["play_count"] = int(row[1] or 0)
            result[aid]["attributed_revenue"] = float(row[2] or 0)

    ad_rows = await db.execute(
        select(
            AdMetric.account_id,
            func.coalesce(func.sum(AdMetric.revenue), 0),
        )
        .where(AdMetric.account_id.in_(video_account_ids))
        .group_by(AdMetric.account_id)
    )
    for row in ad_rows.all():
        aid = str(row[0])
        if aid in result:
            result[aid]["ad_revenue"] = float(row[1] or 0)

    return result


def _serialize_channel_account(acc: ChannelAccount, report: Optional[dict] = None) -> dict:
    data = {
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
        "operators": [_serialize_operator(o) for o in (acc.operators or [])],
        "report_play_count": 0,
        "report_attributed_revenue": 0.0,
        "report_ad_revenue": 0.0,
    }
    if report:
        data.update(report)
    return data


def _parse_date(value: Optional[str]):
    """解析注册日期，非法/空返回 None."""
    if not value:
        return None
    try:
        from datetime import date
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="register_date 格式应为 YYYY-MM-DD")


def _parse_uuid(value: Optional[str], field: str):
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field} format")


def _validate_operator_identity(op: OperatorCreate):
    """双轨校验：operator_user_id 与 operator_name 至少填一个."""
    if not op.operator_user_id and not op.operator_name:
        raise HTTPException(
            status_code=422,
            detail="operator_user_id 与 operator_name 至少填写一个（可从系统选或手填外部姓名）",
        )


# ---------- 台账 CRUD ----------

@router.get("/channel-accounts", response_model=List[ChannelAccountResponse])
async def list_channel_accounts(
    keyword: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """台账列表（可按名称/微信号关键字、启停状态过滤；RBAC 数据隔离）。"""
    query = select(ChannelAccount)
    filters = []
    if keyword:
        kw = f"%{keyword}%"
        filters.append(
            or_(ChannelAccount.channel_name.ilike(kw), ChannelAccount.wechat_id.ilike(kw))
        )
    if enabled is not None:
        filters.append(ChannelAccount.enabled == enabled)
    if current_user and not user_can_access_all_materials(current_user):
        filters.append(ChannelAccount.created_by == current_user.id)
    if filters:
        query = query.where(*filters)
    query = query.order_by(ChannelAccount.created_at.desc())
    result = await db.execute(query)
    accounts = result.scalars().all()

    # 批量聚合报表域数据（按 video_account_id）
    account_ids = [a.video_account_id for a in accounts if a.video_account_id]
    report = await _load_report_metrics(db, account_ids)
    return [
        _serialize_channel_account(
            a,
            report.get(str(a.video_account_id)) if a.video_account_id else None,
        )
        for a in accounts
    ]


@router.get("/channel-accounts/{account_id}", response_model=ChannelAccountResponse)
async def get_channel_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """台账详情（含运营者列表）。"""
    aid = _parse_uuid(account_id, "account_id")
    result = await db.execute(
        select(ChannelAccount).where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    _check_access(acc, current_user)
    report = None
    if acc.video_account_id:
        report = (await _load_report_metrics(db, [acc.video_account_id])).get(
            str(acc.video_account_id)
        )
    return _serialize_channel_account(acc, report)


@router.post("/channel-accounts", response_model=ChannelAccountResponse, status_code=201)
async def create_channel_account(
    data: ChannelAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增台账（video_account_id 可空，先登记后关联）。"""
    acc = ChannelAccount(
        channel_name=data.channel_name,
        wechat_id=data.wechat_id,
        verify_type=data.verify_type,
        verify_name=data.verify_name,
        register_date=_parse_date(data.register_date),
        cooperation_modes=data.cooperation_modes,
        coop_company=data.coop_company,
        video_account_id=_parse_uuid(data.video_account_id, "video_account_id"),
        remark=data.remark,
        enabled=data.enabled,
        created_by=current_user.id if current_user else None,
    )
    db.add(acc)
    await db.flush()
    await db.refresh(acc)
    return _serialize_channel_account(acc)


@router.put("/channel-accounts/{account_id}", response_model=ChannelAccountResponse)
async def update_channel_account(
    account_id: str,
    data: ChannelAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新台账（含补绑/换绑 video_account_id）。"""
    aid = _parse_uuid(account_id, "account_id")
    result = await db.execute(
        select(ChannelAccount).where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    _check_access(acc, current_user)

    updates = data.model_dump(exclude_unset=True)
    if "register_date" in updates:
        acc.register_date = _parse_date(updates.pop("register_date"))
    if "video_account_id" in updates:
        acc.video_account_id = _parse_uuid(updates.pop("video_account_id"), "video_account_id")
    for field, value in updates.items():
        setattr(acc, field, value)

    await db.flush()
    await db.refresh(acc)
    return _serialize_channel_account(acc)


@router.delete("/channel-accounts/{account_id}", status_code=204)
async def delete_channel_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除台账（级联删除运营者）。"""
    aid = _parse_uuid(account_id, "account_id")
    result = await db.execute(
        select(ChannelAccount).where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    _check_access(acc, current_user)
    await db.delete(acc)
    await db.flush()
    return None


# ---------- 运营者管理 ----------

@router.post("/channel-accounts/{account_id}/operators", response_model=OperatorResponse, status_code=201)
async def add_operator(
    account_id: str,
    data: OperatorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增运营者（从系统选 FK 或手填外部姓名，至少填一个）。"""
    aid = _parse_uuid(account_id, "account_id")
    acc = await _load_account(aid, db)
    _check_access(acc, current_user)
    _validate_operator_identity(data)

    op = ChannelOperator(
        channel_account_id=aid,
        operator_user_id=_parse_uuid(data.operator_user_id, "operator_user_id"),
        operator_name=data.operator_name,
        operator_phone=data.operator_phone,
    )
    db.add(op)
    await db.flush()
    await db.refresh(op)
    return _serialize_operator(op)


@router.put("/channel-accounts/{account_id}/operators/{op_id}", response_model=OperatorResponse)
async def update_operator(
    account_id: str,
    op_id: str,
    data: OperatorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新运营者信息。"""
    aid = _parse_uuid(account_id, "account_id")
    oid = _parse_uuid(op_id, "op_id")
    acc = await _load_account(aid, db)
    _check_access(acc, current_user)

    result = await db.execute(
        select(ChannelOperator).where(
            ChannelOperator.id == oid,
            ChannelOperator.channel_account_id == aid,
        )
    )
    op = result.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    updates = data.model_dump(exclude_unset=True)
    if "operator_user_id" in updates:
        op.operator_user_id = _parse_uuid(updates.pop("operator_user_id"), "operator_user_id")
    for field, value in updates.items():
        setattr(op, field, value)
    # 更新后仍须满足双轨约束（服务层兜底）
    if not op.operator_user_id and not op.operator_name:
        raise HTTPException(
            status_code=422,
            detail="operator_user_id 与 operator_name 至少填写一个",
        )

    await db.flush()
    await db.refresh(op)
    return _serialize_operator(op)


@router.delete("/channel-accounts/{account_id}/operators/{op_id}", status_code=204)
async def delete_operator(
    account_id: str,
    op_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """移除运营者。"""
    aid = _parse_uuid(account_id, "account_id")
    oid = _parse_uuid(op_id, "op_id")
    acc = await _load_account(aid, db)
    _check_access(acc, current_user)

    result = await db.execute(
        select(ChannelOperator).where(
            ChannelOperator.id == oid,
            ChannelOperator.channel_account_id == aid,
        )
    )
    op = result.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")
    await db.delete(op)
    await db.flush()
    return None


# ---------- Helpers ----------

async def _load_account(account_id: uuid.UUID, db: AsyncSession) -> ChannelAccount:
    result = await db.execute(
        select(ChannelAccount).where(ChannelAccount.id == account_id)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    return acc


def _check_access(acc: ChannelAccount, current_user: Optional[User]):
    """数据隔离校验：非全量权限用户只能操作自己创建的台账."""
    if current_user and not user_can_access_all_materials(current_user):
        if acc.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权访问该视频号台账")
