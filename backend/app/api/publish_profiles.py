"""publish API 子域：发布配置（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持 `/publish/profiles...` 不变。
本模块负责发布配置（PublishProfile）CRUD。
"""
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import PublishProfile, User, user_can_access_all_materials
from app.utils.helpers import utc_iso

router = APIRouter()


class PublishProfileCreate(BaseModel):
    platform: str
    account_name: Optional[str] = None
    chrome_debug_port: int = 9222
    cookie_file: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_tags: Optional[list] = None
    mini_program_link: Optional[str] = None
    publish_mode: str = "immediate"
    require_manual_confirm: bool = True
    min_interval_seconds: int = 300
    max_daily_publish: int = 20
    # 多运营者（R14/Part3）：operator_id=号主；tier/proxy/fingerprint/egress_ip/chrome_debug_host 毕业字段
    operator_id: Optional[str] = None
    tier: Optional[int] = 0
    proxy_url: Optional[str] = None
    fingerprint_profile: Optional[dict] = None
    egress_ip: Optional[str] = None
    chrome_debug_host: Optional[str] = None


class PublishProfileUpdate(BaseModel):
    platform: Optional[str] = None
    account_name: Optional[str] = None
    chrome_debug_port: Optional[int] = None
    cookie_file: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_tags: Optional[list] = None
    mini_program_link: Optional[str] = None
    publish_mode: Optional[str] = None
    require_manual_confirm: Optional[bool] = None
    min_interval_seconds: Optional[int] = None
    max_daily_publish: Optional[int] = None
    operator_id: Optional[str] = None
    tier: Optional[int] = None
    proxy_url: Optional[str] = None
    fingerprint_profile: Optional[dict] = None
    egress_ip: Optional[str] = None
    chrome_debug_host: Optional[str] = None
    grad_status: Optional[str] = None


class PublishProfileResponse(BaseModel):
    id: str
    platform: Optional[str] = None
    account_name: Optional[str] = None
    chrome_debug_port: int = 9222
    cookie_file: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_tags: Optional[list] = None
    mini_program_link: Optional[str] = None
    publish_mode: str = "immediate"
    require_manual_confirm: bool = True
    min_interval_seconds: int = 300
    max_daily_publish: int = 20
    created_by: Optional[str] = None
    operator_id: Optional[str] = None
    tier: Optional[int] = 0
    proxy_url: Optional[str] = None
    fingerprint_profile: Optional[dict] = None
    egress_ip: Optional[str] = None
    chrome_debug_host: Optional[str] = None
    grad_status: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_publish_profile(profile: PublishProfile) -> dict:
    return {
        "id": str(profile.id),
        "platform": profile.platform,
        "account_name": profile.account_name,
        "chrome_debug_port": profile.chrome_debug_port or 9222,
        # Cookie 脱敏显示（RPA Cookie 安全存储）
        "cookie_file": "****" if profile.cookie_file else None,
        "title_template": profile.title_template,
        "description_template": profile.description_template,
        "default_tags": profile.default_tags,
        "mini_program_link": profile.mini_program_link,
        "publish_mode": profile.publish_mode or "immediate",
        "require_manual_confirm": profile.require_manual_confirm if profile.require_manual_confirm is not None else True,
        "min_interval_seconds": profile.min_interval_seconds or 300,
        "max_daily_publish": profile.max_daily_publish or 20,
        "created_by": str(profile.created_by) if profile.created_by else None,
        "operator_id": str(profile.operator_id) if profile.operator_id else None,
        "tier": profile.tier or 0,
        "proxy_url": profile.proxy_url,
        "fingerprint_profile": profile.fingerprint_profile,
        "egress_ip": profile.egress_ip,
        "chrome_debug_host": profile.chrome_debug_host,
        "grad_status": profile.grad_status,
        "created_at": utc_iso(profile.created_at) if profile.created_at else "",
    }


@router.get("/publish/profiles", response_model=List[PublishProfileResponse])
async def list_publish_profiles(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """List publish profiles（多运营者 RBAC：operator 仅见自己归属/授权的号）."""
    query = select(PublishProfile).order_by(PublishProfile.created_at.desc())
    if current_user and not user_can_access_all_materials(current_user):
        # 运营专员仅可见自己为号主(operator_id)或操作人(created_by)的 profile
        query = query.where(
            (PublishProfile.operator_id == current_user.id)
            | (PublishProfile.created_by == current_user.id)
        )
    result = await db.execute(query)
    profiles = result.scalars().all()
    return [_serialize_publish_profile(p) for p in profiles]


@router.post("/publish/profiles", response_model=PublishProfileResponse, status_code=201)
async def create_publish_profile(
    data: PublishProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """Create a new publish profile."""
    # 加密存储 RPA Cookie（AES-256/Fernet，三期安全）
    cookie_value = data.cookie_file
    if cookie_value and cookie_value != "****":
        from app.auth import encrypt_cookie
        try:
            cookie_value = encrypt_cookie(cookie_value)
        except Exception:
            cookie_value = data.cookie_file

    profile = PublishProfile(
        platform=data.platform,
        account_name=data.account_name,
        chrome_debug_port=data.chrome_debug_port,
        cookie_file=cookie_value,
        title_template=data.title_template,
        description_template=data.description_template,
        default_tags=data.default_tags,
        mini_program_link=data.mini_program_link,
        publish_mode=data.publish_mode,
        require_manual_confirm=data.require_manual_confirm,
        min_interval_seconds=data.min_interval_seconds,
        max_daily_publish=data.max_daily_publish,
        # 多运营者归属：created_by=操作人；operator_id=号主（缺省同操作人）
        created_by=current_user.id if current_user else None,
        operator_id=uuid.UUID(data.operator_id) if data.operator_id else (current_user.id if current_user else None),
        tier=data.tier,
        proxy_url=data.proxy_url,
        fingerprint_profile=data.fingerprint_profile,
        egress_ip=data.egress_ip,
        chrome_debug_host=data.chrome_debug_host,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return _serialize_publish_profile(profile)


@router.put("/publish/profiles/{profile_id}", response_model=PublishProfileResponse)
async def update_publish_profile(
    profile_id: str,
    data: PublishProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """Update a publish profile."""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    result = await db.execute(select(PublishProfile).where(PublishProfile.id == pid))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Publish profile not found")
    # RBAC：operator 仅可操作自己归属的 profile
    if current_user and not user_can_access_all_materials(current_user):
        if profile.operator_id not in (current_user.id, None) and profile.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="No permission to update this profile")

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        # Cookie 字段特殊处理：加密存储 + 跳过“****”占位（未修改）
        if field == "cookie_file":
            if value and value != "****":
                from app.auth import encrypt_cookie
                try:
                    profile.cookie_file = encrypt_cookie(value)
                except Exception:
                    profile.cookie_file = value
            continue
        setattr(profile, field, value)

    await db.flush()
    await db.refresh(profile)
    return _serialize_publish_profile(profile)


@router.delete("/publish/profiles/{profile_id}", status_code=204)
async def delete_publish_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """Delete a publish profile."""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    result = await db.execute(select(PublishProfile).where(PublishProfile.id == pid))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Publish profile not found")
    # RBAC：operator 仅可删除自己归属的 profile
    if current_user and not user_can_access_all_materials(current_user):
        if profile.operator_id not in (current_user.id, None) and profile.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="No permission to delete this profile")

    await db.delete(profile)
    await db.flush()
    return None
