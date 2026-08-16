"""publish API 子域：账号库（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持 `/publish/video-accounts...` 不变。
本模块负责视频号/抖音/快手矩阵账号 CRUD 与批量导入。
"""
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import VideoAccount, User, user_can_access_all_materials
from app.utils.helpers import utc_iso

router = APIRouter()


class VideoAccountCreate(BaseModel):
    account_name: str
    platform: str
    group_name: Optional[str] = None
    wxid: Optional[str] = None
    account_uid: Optional[str] = None
    profile_id: Optional[str] = None
    mini_program_enabled: bool = False
    remark: Optional[str] = None
    enabled: bool = True
    # 多运营者（R14）：operator_id=号主（微信号主人）；created_by 由后端取当前用户写入
    operator_id: Optional[str] = None


class VideoAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    platform: Optional[str] = None
    group_name: Optional[str] = None
    wxid: Optional[str] = None
    account_uid: Optional[str] = None
    profile_id: Optional[str] = None
    mini_program_enabled: Optional[bool] = None
    remark: Optional[str] = None
    enabled: Optional[bool] = None
    operator_id: Optional[str] = None


class VideoAccountResponse(BaseModel):
    id: str
    account_name: str
    platform: str
    group_name: Optional[str] = None
    wxid: Optional[str] = None
    account_uid: Optional[str] = None
    profile_id: Optional[str] = None
    mini_program_enabled: bool = False
    remark: Optional[str] = None
    enabled: bool = True
    created_by: Optional[str] = None
    operator_id: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class VideoAccountBatchImport(BaseModel):
    """账号批量导入：每行一个账号（账号名/平台/分组/视频号ID/备注）。"""
    accounts: List[VideoAccountCreate]
    skip_duplicates: bool = True


def _serialize_video_account(acc: VideoAccount) -> dict:
    return {
        "id": str(acc.id),
        "account_name": acc.account_name,
        "platform": acc.platform,
        "group_name": acc.group_name,
        "wxid": acc.wxid,
        "account_uid": acc.account_uid,
        "profile_id": str(acc.profile_id) if acc.profile_id else None,
        "mini_program_enabled": acc.mini_program_enabled or False,
        "remark": acc.remark,
        "enabled": acc.enabled if acc.enabled is not None else True,
        "created_by": str(acc.created_by) if acc.created_by else None,
        "operator_id": str(acc.operator_id) if acc.operator_id else None,
        "created_at": utc_iso(acc.created_at) if acc.created_at else "",
        "updated_at": utc_iso(acc.updated_at) if acc.updated_at else "",
    }


@router.get("/publish/video-accounts", response_model=List[VideoAccountResponse])
async def list_video_accounts(
    platform: Optional[str] = Query(None),
    group_name: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """账号库列表（可按平台/分组过滤，多运营者 RBAC：operator 仅见自己归属的号）."""
    filters = []
    if platform:
        filters.append(VideoAccount.platform == platform)
    if group_name:
        filters.append(VideoAccount.group_name == group_name)
    query = select(VideoAccount)
    if filters:
        query = query.where(and_(*filters))
    if current_user and not user_can_access_all_materials(current_user):
        query = query.where(
            (VideoAccount.operator_id == current_user.id)
            | (VideoAccount.created_by == current_user.id)
        )
    query = query.order_by(VideoAccount.platform, VideoAccount.group_name, VideoAccount.account_name)
    result = await db.execute(query)
    accounts = result.scalars().all()
    return [_serialize_video_account(a) for a in accounts]


@router.post("/publish/video-accounts", response_model=VideoAccountResponse, status_code=201)
async def create_video_account(
    data: VideoAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """新增账号（手动新增 / 初始化导入的单条）。"""
    acc = VideoAccount(
        account_name=data.account_name,
        platform=data.platform,
        group_name=data.group_name,
        wxid=data.wxid,
        account_uid=data.account_uid,
        profile_id=uuid.UUID(data.profile_id) if data.profile_id else None,
        mini_program_enabled=data.mini_program_enabled,
        remark=data.remark,
        enabled=data.enabled,
        # 多运营者归属：created_by=操作人；operator_id=号主（缺省同操作人）
        created_by=current_user.id if current_user else None,
        operator_id=uuid.UUID(data.operator_id) if data.operator_id else (current_user.id if current_user else None),
    )
    db.add(acc)
    await db.flush()
    await db.refresh(acc)
    return _serialize_video_account(acc)


@router.post("/publish/video-accounts/batch", response_model=dict, status_code=201)
async def batch_import_video_accounts(
    data: VideoAccountBatchImport,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """账号批量导入（Excel/CSV 解析后的结构化数组落库）。

    skip_duplicates=True 时按 (platform, account_name) 去重，重复项跳过并计数。
    """
    imported = 0
    skipped = 0
    errors = []
    for item in data.accounts:
        try:
            if data.skip_duplicates:
                dup = await db.execute(
                    select(VideoAccount).where(
                        VideoAccount.platform == item.platform,
                        VideoAccount.account_name == item.account_name,
                    )
                )
                if dup.scalar_one_or_none():
                    skipped += 1
                    continue
            acc = VideoAccount(
                account_name=item.account_name,
                platform=item.platform,
                group_name=item.group_name,
                wxid=item.wxid,
                account_uid=item.account_uid,
                profile_id=uuid.UUID(item.profile_id) if item.profile_id else None,
                mini_program_enabled=item.mini_program_enabled,
                remark=item.remark,
                enabled=item.enabled,
                created_by=current_user.id if current_user else None,
                operator_id=uuid.UUID(item.operator_id) if item.operator_id else (current_user.id if current_user else None),
            )
            db.add(acc)
            imported += 1
        except Exception as e:
            errors.append({"account_name": item.account_name, "error": str(e)})
    await db.flush()
    return {"imported": imported, "skipped": skipped, "errors": errors}


@router.put("/publish/video-accounts/{account_id}", response_model=VideoAccountResponse)
async def update_video_account(
    account_id: str,
    data: VideoAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更新账号信息。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(select(VideoAccount).where(VideoAccount.id == aid))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Video account not found")
    # RBAC：operator 仅可操作自己归属的账号
    if current_user and not user_can_access_all_materials(current_user):
        if acc.operator_id not in (current_user.id, None) and acc.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="No permission to update this account")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("profile_id", "operator_id"):
            setattr(acc, field, uuid.UUID(value) if value else None)
            continue
        setattr(acc, field, value)

    await db.flush()
    await db.refresh(acc)
    return _serialize_video_account(acc)


@router.delete("/publish/video-accounts/{account_id}", status_code=204)
async def delete_video_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """删除账号。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(select(VideoAccount).where(VideoAccount.id == aid))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Video account not found")
    # RBAC：operator 仅可删除自己归属的账号
    if current_user and not user_can_access_all_materials(current_user):
        if acc.operator_id not in (current_user.id, None) and acc.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="No permission to delete this account")

    await db.delete(acc)
    await db.flush()
    return None
