"""publish API 子域：定时发布时间窗口（R99 定时发布）。

负责预置 + 自定义时间窗口的 CRUD，以及「窗口 → 具体发布时间点」的解析工具。

- 预置窗口（is_preset=True）：07:00-08:00 早晨黄金档、18:00-20:00 晚间黄金档，
  系统内置，不可删除 / 改时段。
- 自定义窗口（is_preset=False）：运营者可增删改，用于业务自定义发布时段。

窗口只描述一天内的起止时段（每天循环），不绑定具体日期；创建发布任务时选择窗口，
系统在窗口内随机选一个今天/明天的具体时间点作为 PublishTask.scheduled_at，
实现窗口内错峰分散发布（降低同刻集中触发的风控风险）。
"""
import random
import uuid
from datetime import datetime, timedelta
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import PublishTimeSlot, User
from app.utils.helpers import utc_iso

router = APIRouter()

# 系统预置窗口定义（迁移时写入 DB，作为列表接口的保底兜底）
PRESET_SLOTS = [
    {"name": "早晨黄金档", "start_time": "07:00", "end_time": "08:00"},
    {"name": "晚间黄金档", "start_time": "18:00", "end_time": "20:00"},
]


class PublishTimeSlotCreate(BaseModel):
    name: str
    start_time: str
    end_time: str
    enabled: bool = True


class PublishTimeSlotUpdate(BaseModel):
    name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    enabled: Optional[bool] = None


class PublishTimeSlotResponse(BaseModel):
    id: str
    name: str
    start_time: str
    end_time: str
    enabled: bool = True
    is_preset: bool = False
    created_by: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_slot(slot: PublishTimeSlot) -> dict:
    return {
        "id": str(slot.id),
        "name": slot.name,
        "start_time": slot.start_time,
        "end_time": slot.end_time,
        "enabled": slot.enabled if slot.enabled is not None else True,
        "is_preset": bool(slot.is_preset),
        "created_by": str(slot.created_by) if slot.created_by else None,
        "created_at": utc_iso(slot.created_at) if slot.created_at else "",
    }


def _validate_time_range(start_time: str, end_time: str) -> None:
    """校验 HH:MM 格式且 start < end（不允许跨零点窗口，简化错峰选点）。"""
    import re
    pattern = re.compile(r"^\d{2}:\d{2}$")
    if not pattern.match(start_time) or not pattern.match(end_time):
        raise HTTPException(status_code=400, detail="时间格式须为 HH:MM，如 07:00")
    sh, sm = int(start_time[:2]), int(start_time[3:])
    eh, em = int(end_time[:2]), int(end_time[3:])
    if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 23 and 0 <= em <= 59):
        raise HTTPException(status_code=400, detail="时间超出合法范围 (00:00-23:59)")
    if (sh, sm) >= (eh, em):
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间（暂不支持跨零点窗口）")


@router.get("/publish/time-slots", response_model=List[PublishTimeSlotResponse])
async def list_publish_time_slots(
    enabled_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """列表时间窗口：预置 + 自定义（enabled_only=True 仅返回启用项，供发布弹窗选择）。"""
    query = select(PublishTimeSlot).order_by(PublishTimeSlot.is_preset.desc(), PublishTimeSlot.start_time.asc())
    if enabled_only:
        query = query.where(PublishTimeSlot.enabled == True)  # noqa: E712
    result = await db.execute(query)
    slots = result.scalars().all()
    return [_serialize_slot(s) for s in slots]


@router.post("/publish/time-slots", response_model=PublishTimeSlotResponse, status_code=201)
async def create_publish_time_slot(
    data: PublishTimeSlotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """创建自定义时间窗口（预置窗口不可新建）。"""
    _validate_time_range(data.start_time, data.end_time)
    slot = PublishTimeSlot(
        name=data.name,
        start_time=data.start_time,
        end_time=data.end_time,
        enabled=data.enabled,
        is_preset=False,
        created_by=current_user.id if current_user else None,
        created_at=datetime.utcnow(),
    )
    db.add(slot)
    await db.flush()
    await db.refresh(slot)
    return _serialize_slot(slot)


@router.put("/publish/time-slots/{slot_id}", response_model=PublishTimeSlotResponse)
async def update_publish_time_slot(
    slot_id: str,
    data: PublishTimeSlotUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新自定义时间窗口（预置窗口禁止修改时段/删除）。"""
    try:
        sid = uuid.UUID(slot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot ID format")
    result = await db.execute(select(PublishTimeSlot).where(PublishTimeSlot.id == sid))
    slot = result.scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Time slot not found")
    if slot.is_preset:
        raise HTTPException(status_code=403, detail="预置时间窗口不可修改")

    update_fields = data.model_dump(exclude_unset=True)
    if "start_time" in update_fields or "end_time" in update_fields:
        _validate_time_range(
            update_fields.get("start_time", slot.start_time),
            update_fields.get("end_time", slot.end_time),
        )
    for field, value in update_fields.items():
        setattr(slot, field, value)
    await db.flush()
    await db.refresh(slot)
    return _serialize_slot(slot)


@router.delete("/publish/time-slots/{slot_id}", status_code=204)
async def delete_publish_time_slot(
    slot_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除自定义时间窗口（预置窗口不可删除）。"""
    try:
        sid = uuid.UUID(slot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot ID format")
    result = await db.execute(select(PublishTimeSlot).where(PublishTimeSlot.id == sid))
    slot = result.scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Time slot not found")
    if slot.is_preset:
        raise HTTPException(status_code=403, detail="预置时间窗口不可删除")
    await db.delete(slot)
    await db.flush()
    return None


def resolve_scheduled_at(slot: PublishTimeSlot | None, scheduled_at: datetime | None = None) -> datetime | None:
    """把时间窗口 / 指定时间解析为具体的发布时间点。

    说明：
    - 窗口的 start_time/end_time 是业务本地时间（北京时间，UTC+8）；
      而全库时间列统一存储 naive UTC（utcnow()）。故先把窗口转成 UTC 再比较/选点。
    - 若直接给了具体 scheduled_at（前端 dayjs 已按本地时区 toISOString() 转成 UTC），原样返回。
    - 若给了时间窗口，则在窗口内随机选一个「今天或明天」的合法时刻返回。
      - 窗口在「今天」内：取今天窗口内随机点；
      - 窗口已过（今天该时段已结束）：取明天窗口内随机点。
    - 都为空 → 返回 None（立即发布）。
    """
    if scheduled_at is not None:
        return scheduled_at
    if slot is None:
        return None

    # 本地时区偏移（小时）。优先从配置/系统取，缺省北京 +8。
    local_utc_offset_hours = getattr(settings, "LOCAL_TZ_OFFSET_HOURS", 8) or 8

    now = datetime.utcnow()
    # 把窗口起始时间换算成本地时区的「今天」绝对时刻
    today_local = datetime.utcnow() + timedelta(hours=local_utc_offset_hours)
    today_local = today_local.replace(hour=0, minute=0, second=0, microsecond=0)

    def _random_in_window(day_local: datetime) -> datetime:
        sh, sm = int(slot.start_time[:2]), int(slot.start_time[3:])
        eh, em = int(slot.end_time[:2]), int(slot.end_time[3:])
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        total = end_min - start_min
        chosen = start_min + (random.randint(0, total - 1) if total > 0 else 0)
        local_dt = day_local.replace(hour=chosen // 60, minute=chosen % 60, second=0, microsecond=0)
        # 本地时间转回 UTC 存储
        return local_dt - timedelta(hours=local_utc_offset_hours)

    # 今天窗口结束时刻（本地）转 UTC
    eh, em = int(slot.end_time[:2]), int(slot.end_time[3:])
    window_today_end_local = today_local.replace(hour=eh, minute=em, second=0, microsecond=0)
    window_today_end_utc = window_today_end_local - timedelta(hours=local_utc_offset_hours)
    if window_today_end_utc > now:
        # 窗口今天还有剩余时间 → 在今天窗口内随机
        return _random_in_window(today_local)
    # 窗口今天已过 → 明天
    tomorrow_local = today_local + timedelta(days=1)
    return _random_in_window(tomorrow_local)
