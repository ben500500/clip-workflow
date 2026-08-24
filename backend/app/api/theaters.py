"""剧场（Theater）CRUD API。

对应需求「剧目直接挂剧场 + 视频号列表页剧场管理」：
- 视频号列表页提供「新增剧场」功能（视频号列表页新增/管理剧场）；
- 剧目直接挂剧场（dramas.theater_id）、视频号挂剧场（channel_accounts / video_accounts 的 theater_id）；
- 按剧场筛选（剧目库、视频号列表）。

数据隔离：沿用 `user_can_access_all_materials` RBAC（operator 仅见自己创建的剧场）。
"""
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import User, user_can_access_all_materials
from app.models.theater import Theater
from app.utils.helpers import utc_iso

router = APIRouter()


# ---------- Schemas ----------

class TheaterCreate(BaseModel):
    name: str
    remark: Optional[str] = None
    operator_id: Optional[str] = None


class TheaterUpdate(BaseModel):
    name: Optional[str] = None
    remark: Optional[str] = None
    operator_id: Optional[str] = None


class TheaterResponse(BaseModel):
    id: str
    name: str
    remark: Optional[str] = None
    operator_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------- Serializer ----------

def _serialize_theater(t: Theater) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "remark": t.remark,
        "operator_id": str(t.operator_id) if t.operator_id else None,
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": utc_iso(t.created_at) if t.created_at else "",
        "updated_at": utc_iso(t.updated_at) if t.updated_at else "",
    }


def _parse_uuid(value: Optional[str], field: str):
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field} format")


def _apply_rbac_filter(current_user: User):
    if current_user and not user_can_access_all_materials(current_user):
        return (Theater.operator_id == current_user.id) | (Theater.created_by == current_user.id)
    return None


# ---------- CRUD ----------

@router.get("/theaters", response_model=List[TheaterResponse])
async def list_theaters(
    keyword: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """剧场列表（可按名称关键字搜索；RBAC 数据隔离）。"""
    query = select(Theater)
    filters = []
    if keyword:
        kw = f"%{keyword}%"
        filters.append(Theater.name.ilike(kw))
    rbac = _apply_rbac_filter(current_user)
    if rbac is not None:
        filters.append(rbac)
    if filters:
        query = query.where(*filters)
    query = query.order_by(Theater.created_at.desc())
    result = await db.execute(query)
    return [_serialize_theater(t) for t in result.scalars().all()]


@router.get("/theaters/{theater_id}", response_model=TheaterResponse)
async def get_theater(
    theater_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """剧场详情。"""
    tid = _parse_uuid(theater_id, "theater_id")
    result = await db.execute(select(Theater).where(Theater.id == tid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Theater not found")
    return _serialize_theater(t)


@router.post("/theaters", response_model=TheaterResponse, status_code=201)
async def create_theater(
    data: TheaterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增剧场。name 唯一。"""
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="剧场名称不能为空")
    existing = await db.execute(select(Theater).where(Theater.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"同名剧场已存在：{name}")

    t = Theater(
        name=name,
        remark=data.remark,
        operator_id=_parse_uuid(data.operator_id, "operator_id") or (current_user.id if current_user else None),
        created_by=current_user.id if current_user else None,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return _serialize_theater(t)


@router.put("/theaters/{theater_id}", response_model=TheaterResponse)
async def update_theater(
    theater_id: str,
    data: TheaterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新剧场信息。"""
    tid = _parse_uuid(theater_id, "theater_id")
    result = await db.execute(select(Theater).where(Theater.id == tid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Theater not found")
    _check_access(t, current_user)

    updates = data.model_dump(exclude_unset=True)
    new_name = updates.get("name")
    if new_name:
        new_name = new_name.strip()
        if new_name != t.name:
            dup = await db.execute(
                select(Theater).where(Theater.name == new_name, Theater.id != t.id)
            )
            if dup.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"同名剧场已存在：{new_name}")
            t.name = new_name
    if "operator_id" in updates:
        t.operator_id = _parse_uuid(updates.pop("operator_id"), "operator_id")
    for field, value in updates.items():
        if field == "name":
            continue
        setattr(t, field, value)

    await db.flush()
    await db.refresh(t)
    return _serialize_theater(t)


@router.delete("/theaters/{theater_id}", status_code=204)
async def delete_theater(
    theater_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除剧场（关联剧目/视频号的 theater_id 置空，不级联删除）。"""
    tid = _parse_uuid(theater_id, "theater_id")
    result = await db.execute(select(Theater).where(Theater.id == tid))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Theater not found")
    _check_access(t, current_user)
    await db.delete(t)
    await db.flush()
    return None


def _check_access(t: Theater, current_user: Optional[User]):
    """数据隔离：非全量权限用户只能操作自己创建的剧场."""
    if current_user and not user_can_access_all_materials(current_user):
        if t.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权操作该剧场")
