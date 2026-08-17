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
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.models import (
    AdMetric,
    ChannelAccount,
    ChannelOperator,
    User,
    VideoAccount,
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
    # 视频号列表先登记：直接填写名称/视频号ID，创建后自动同步到账号库
    channel_name: Optional[str] = None       # 视频号名称
    wechat_id: Optional[str] = None          # 视频号ID（平台侧唯一标识）
    platform: Optional[str] = "wechat_channel"  # 同步到账号库时的平台，缺省视频号
    verify_type: Optional[str] = None        # personal / enterprise
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_modes: Optional[List[CooperationMode]] = None   # ["IAA","IAP"]
    coop_company: Optional[str] = None
    video_account_id: Optional[str] = None   # 选填：已存在账号库关联时直接绑定
    remark: Optional[str] = None
    enabled: bool = True


class ChannelAccountFromVideoAccount(BaseModel):
    """从账号库一键登记台账：video_account_id + 工商/合作信息.

    名称/微信号由账号库自动带出；账号库号主（operator_id）自动作为首个运营者打通归属。
    """
    video_account_id: str
    verify_type: Optional[str] = None        # personal / enterprise
    verify_name: Optional[str] = None
    register_date: Optional[str] = None
    cooperation_modes: Optional[List[CooperationMode]] = None   # ["IAA","IAP"]
    coop_company: Optional[str] = None
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
    video_account_id: Optional[str] = None   # 方向1：不可置空，只能换绑到其它账号库
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


async def _reload_channel_account(db: AsyncSession, acc_id: uuid.UUID) -> ChannelAccount:
    """带 operators 关系重新查询（async 会话内 eager-load，避免序列化时触发
    MissingGreenlet：greenlet_spawn has not been called）。"""
    result = await db.execute(
        select(ChannelAccount)
        .where(ChannelAccount.id == acc_id)
        .options(selectinload(ChannelAccount.operators))
    )
    return result.scalar_one()


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
    query = select(ChannelAccount).options(selectinload(ChannelAccount.operators))
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
        select(ChannelAccount).options(selectinload(ChannelAccount.operators)).where(ChannelAccount.id == aid)
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
    """新增台账（视频号列表先登记）：直接填写名称/视频号ID，创建后自动同步到账号库。

    若未指定 video_account_id，则按名称/视频号ID 在账号库中查找，找不到时自动创建
    相同账号并绑定，保证「视频号列表先添加，账号库同步添加相同账号」的顺序。
    """
    channel_name = (data.channel_name or "").strip()
    wechat_id = (data.wechat_id or "").strip()
    if not channel_name:
        raise HTTPException(status_code=422, detail="视频号名称不能为空")

    # 1) 已指定关联账号库：直接绑定（校验存在且不重复）
    if data.video_account_id:
        video_account = await _load_video_account(
            _parse_uuid(data.video_account_id, "video_account_id"), db
        )
        await _ensure_no_existing(video_account.id, db, exclude_id=None)
    else:
        # 2) 未指定：按名称/视频号ID 查找账号库，找到则复用，找不到则自动同步创建
        video_account = await _find_or_create_video_account(
            db, channel_name, wechat_id, data.platform or "wechat_channel",
            data.remark, current_user.id if current_user else None,
        )
        await _ensure_no_existing(video_account.id, db, exclude_id=None)

    acc = ChannelAccount(
        channel_name=channel_name or video_account.account_name,
        wechat_id=wechat_id or video_account.wxid,
        verify_type=data.verify_type,
        verify_name=data.verify_name,
        register_date=_parse_date(data.register_date),
        cooperation_modes=data.cooperation_modes,
        coop_company=data.coop_company,
        video_account_id=video_account.id,
        remark=data.remark,
        enabled=data.enabled,
        created_by=current_user.id if current_user else None,
    )
    db.add(acc)
    await db.flush()
    acc = await _reload_channel_account(db, acc.id)
    return _serialize_channel_account(acc)


@router.post(
    "/channel-accounts/from-video-account",
    response_model=ChannelAccountResponse,
    status_code=201,
)
async def create_channel_from_video_account(
    data: ChannelAccountFromVideoAccount,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """从账号库一键登记台账：自动带出名称/微信号，并把账号库号主作为首个运营者打通归属。"""
    video_account = await _load_video_account(
        _parse_uuid(data.video_account_id, "video_account_id"), db
    )
    await _ensure_no_existing(video_account.id, db, exclude_id=None)
    acc = ChannelAccount(
        channel_name=video_account.account_name,
        wechat_id=video_account.wxid,
        verify_type=data.verify_type,
        verify_name=data.verify_name,
        register_date=_parse_date(data.register_date),
        cooperation_modes=data.cooperation_modes,
        coop_company=data.coop_company,
        video_account_id=video_account.id,
        remark=data.remark,
        enabled=data.enabled,
        created_by=current_user.id if current_user else None,
    )
    # 打通归属：账号库号主（operator_id）自动作为首个运营者（仅当号主存在）
    if video_account.operator_id:
        acc.operators.append(
            ChannelOperator(
                channel=acc,
                operator_user_id=video_account.operator_id,
            )
        )
    db.add(acc)
    await db.flush()
    acc = await _reload_channel_account(db, acc.id)
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
        select(ChannelAccount).options(selectinload(ChannelAccount.operators)).where(ChannelAccount.id == aid)
    )
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Channel account not found")
    _check_access(acc, current_user)

    updates = data.model_dump(exclude_unset=True)
    if "register_date" in updates:
        acc.register_date = _parse_date(updates.pop("register_date"))
    if "video_account_id" in updates:
        new_vaid = _parse_uuid(updates.pop("video_account_id"), "video_account_id")
        if new_vaid is None:
            # 视频号列表先登记：允许解绑账号库（列表独立于账号库）
            acc.video_account_id = None
        else:
            video_account = await _load_video_account(new_vaid, db)
            await _ensure_no_existing(video_account.id, db, exclude_id=acc.id)
            acc.video_account_id = video_account.id
            # 换绑后名称/视频号ID随新账号库自动带出
            if "channel_name" not in updates:
                acc.channel_name = video_account.account_name
            if "wechat_id" not in updates:
                acc.wechat_id = video_account.wxid
    for field, value in updates.items():
        setattr(acc, field, value)

    await db.flush()
    acc = await _reload_channel_account(db, acc.id)
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
        select(ChannelAccount).options(selectinload(ChannelAccount.operators)).where(ChannelAccount.id == aid)
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


async def _load_video_account(video_account_id: uuid.UUID, db: AsyncSession) -> VideoAccount:
    """加载账号库账号，不存在则 400（台账以账号库为主数据，必须存在）。"""
    result = await db.execute(
        select(VideoAccount).where(VideoAccount.id == video_account_id)
    )
    va = result.scalar_one_or_none()
    if not va:
        raise HTTPException(status_code=400, detail="关联的发布账号不存在，请先从账号库选择")
    return va


async def _find_or_create_video_account(
    db: AsyncSession,
    channel_name: str,
    wechat_id: str,
    platform: str,
    remark: Optional[str],
    current_user_id: Optional[uuid.UUID],
) -> VideoAccount:
    """按名称/视频号ID 在账号库中查找，找不到则自动同步创建相同账号（视频号列表先登记）。

    匹配优先级：视频号ID（wxid） > 账号名。保证同一视频号在账号库中不重复。
    """
    # 按视频号ID（wxid）精确匹配
    if wechat_id:
        result = await db.execute(
            select(VideoAccount).where(VideoAccount.wxid == wechat_id)
        )
        va = result.scalar_one_or_none()
        if va:
            return va
    # 按名称匹配
    result = await db.execute(
        select(VideoAccount).where(VideoAccount.account_name == channel_name)
    )
    va = result.scalar_one_or_none()
    if va:
        # 名称命中但缺视频号ID时补写，保持两库同步
        if wechat_id and not va.wxid:
            va.wxid = wechat_id
        return va

    # 都不存在：自动同步创建账号库账号
    va = VideoAccount(
        account_name=channel_name,
        platform=platform,
        wxid=wechat_id or None,
        remark=remark,
        enabled=True,
        created_by=current_user_id,
        operator_id=current_user_id,
    )
    db.add(va)
    await db.flush()
    await db.refresh(va)
    return va


async def _ensure_no_existing(
    video_account_id: uuid.UUID,
    db: AsyncSession,
    exclude_id: Optional[uuid.UUID],
) -> None:
    """幂等：同一发布账号最多对应一条台账（exclude_id 用于更新时排除自身）。"""
    query = select(ChannelAccount.id).where(
        ChannelAccount.video_account_id == video_account_id
    )
    if exclude_id:
        query = query.where(ChannelAccount.id != exclude_id)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="该发布账号已登记过视频号台账，不能重复登记",
        )


def _check_access(acc: ChannelAccount, current_user: Optional[User]):
    """数据隔离校验：非全量权限用户只能操作自己创建的台账."""
    if current_user and not user_can_access_all_materials(current_user):
        if acc.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权访问该视频号台账")
