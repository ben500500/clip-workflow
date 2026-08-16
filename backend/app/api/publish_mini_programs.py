"""publish API 子域：小程序链接库（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持 `/publish/mini-programs...` 不变。
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import MiniProgram
from app.utils.helpers import utc_iso

router = APIRouter()


class MiniProgramCreate(BaseModel):
    name: str
    appid: Optional[str] = None
    path: Optional[str] = None
    full_link: str
    remark: Optional[str] = None
    enabled: bool = True


class MiniProgramUpdate(BaseModel):
    name: Optional[str] = None
    appid: Optional[str] = None
    path: Optional[str] = None
    full_link: Optional[str] = None
    remark: Optional[str] = None
    enabled: Optional[bool] = None


class MiniProgramResponse(BaseModel):
    id: str
    name: str
    appid: Optional[str] = None
    path: Optional[str] = None
    full_link: str
    remark: Optional[str] = None
    enabled: bool = True
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_mini_program(mp: MiniProgram) -> dict:
    return {
        "id": str(mp.id),
        "name": mp.name,
        "appid": mp.appid,
        "path": mp.path,
        "full_link": mp.full_link,
        "remark": mp.remark,
        "enabled": mp.enabled if mp.enabled is not None else True,
        "created_at": utc_iso(mp.created_at) if mp.created_at else "",
    }


@router.get("/publish/mini-programs", response_model=List[MiniProgramResponse])
async def list_mini_programs(
    enabled_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """小程序链接库列表。"""
    query = select(MiniProgram)
    if enabled_only:
        query = query.where(MiniProgram.enabled == True)  # noqa: E712
    query = query.order_by(MiniProgram.name)
    result = await db.execute(query)
    programs = result.scalars().all()
    return [_serialize_mini_program(mp) for mp in programs]


@router.post("/publish/mini-programs", response_model=MiniProgramResponse, status_code=201)
async def create_mini_program(
    data: MiniProgramCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增小程序链接。"""
    mp = MiniProgram(
        name=data.name,
        appid=data.appid,
        path=data.path,
        full_link=data.full_link,
        remark=data.remark,
        enabled=data.enabled,
    )
    db.add(mp)
    await db.flush()
    await db.refresh(mp)
    return _serialize_mini_program(mp)


@router.put("/publish/mini-programs/{mp_id}", response_model=MiniProgramResponse)
async def update_mini_program(
    mp_id: str,
    data: MiniProgramUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新小程序链接。"""
    try:
        mid = uuid.UUID(mp_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mini program ID format")

    result = await db.execute(select(MiniProgram).where(MiniProgram.id == mid))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(status_code=404, detail="Mini program not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(mp, field, value)

    await db.flush()
    await db.refresh(mp)
    return _serialize_mini_program(mp)


@router.delete("/publish/mini-programs/{mp_id}", status_code=204)
async def delete_mini_program(
    mp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除小程序链接。"""
    try:
        mid = uuid.UUID(mp_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mini program ID format")

    result = await db.execute(select(MiniProgram).where(MiniProgram.id == mid))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(status_code=404, detail="Mini program not found")

    await db.delete(mp)
    await db.flush()
    return None
