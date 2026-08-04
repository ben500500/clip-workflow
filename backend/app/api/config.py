import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import SystemConfig, PlatformProfile

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    key: str
    value: Any


class ConfigResponse(BaseModel):
    key: str
    value: Any
    updated_at: str


class ProfileCreate(BaseModel):
    name: str
    platform: str
    dedupe_config: Optional[dict] = None
    target_resolution: Optional[str] = None
    target_bitrate: Optional[str] = None
    max_duration: Optional[int] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    dedupe_config: Optional[dict] = None
    target_resolution: Optional[str] = None
    target_bitrate: Optional[str] = None
    max_duration: Optional[int] = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    platform: Optional[str] = None
    dedupe_config: Optional[dict] = None
    target_resolution: Optional[str] = None
    target_bitrate: Optional[str] = None
    max_duration: Optional[int] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_config(cfg: SystemConfig) -> dict:
    return {
        "key": cfg.key,
        "value": cfg.value,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else "",
    }


def _serialize_profile(profile: PlatformProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "platform": profile.platform,
        "dedupe_config": profile.dedupe_config,
        "target_resolution": profile.target_resolution,
        "target_bitrate": profile.target_bitrate,
        "max_duration": profile.max_duration,
        "created_at": profile.created_at.isoformat() if profile.created_at else "",
    }


@router.get("/config", response_model=List[ConfigResponse])
async def get_all_config(db: AsyncSession = Depends(get_db)):
    """Get all system configuration key-value pairs."""
    result = await db.execute(
        select(SystemConfig).order_by(SystemConfig.key)
    )
    configs = result.scalars().all()

    # If no configs exist, return defaults
    if not configs:
        defaults = {
            "default_autoclip_config": {
                "llm_provider": "dashscope",
                "llm_model": "qwen-plus",
                "min_score_threshold": 60,
                "max_clips": 30,
                "min_duration": 30,
                "max_duration": 180,
            },
            "default_dedupe_config": {
                "mode": "fast",
                "flip_mirror": False,
                "speed_change": True,
                "speed_factor": 1.04,
                "saturation": True,
                "saturation_value": 0.95,
                "brightness": True,
                "brightness_value": 0.01,
                "sharpen": True,
                "sharpen_amount": 0.8,
            },
            "default_interval_config": {
                "mode": "credits",
                "scan_window": 6.0,
                "frame_interval": 0.5,
                "static_threshold": 5,
                "gold_ratio_threshold": 0.03,
                "min_static_duration": 9,
            },
            "storage_retention_days": 30,
            "auto_cleanup_enabled": False,
            "max_concurrent_tasks": 4,
            "task_timeout_hours": 2,
        }
        return [
            ConfigResponse(key=k, value=v, updated_at="")
            for k, v in defaults.items()
        ]

    return [_serialize_config(c) for c in configs]


@router.put("/config", response_model=ConfigResponse)
async def update_config(
    data: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a system configuration value."""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == data.key)
    )
    config = result.scalar_one_or_none()

    if config:
        config.value = data.value
        config.updated_at = datetime.utcnow()
    else:
        config = SystemConfig(key=data.key, value=data.value)
        db.add(config)

    await db.flush()
    await db.refresh(config)
    return _serialize_config(config)


@router.get("/config/platform-profiles", response_model=List[ProfileResponse])
async def list_platform_profiles(db: AsyncSession = Depends(get_db)):
    """List all platform profiles."""
    result = await db.execute(
        select(PlatformProfile).order_by(PlatformProfile.name)
    )
    profiles = result.scalars().all()
    return [_serialize_profile(p) for p in profiles]


@router.post("/config/platform-profiles", response_model=ProfileResponse, status_code=201)
async def create_platform_profile(
    data: ProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new platform profile."""
    # Check for duplicate name
    existing = await db.execute(
        select(PlatformProfile).where(PlatformProfile.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Platform profile with name '{data.name}' already exists",
        )

    profile = PlatformProfile(
        name=data.name,
        platform=data.platform,
        dedupe_config=data.dedupe_config,
        target_resolution=data.target_resolution,
        target_bitrate=data.target_bitrate,
        max_duration=data.max_duration,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return _serialize_profile(profile)


@router.put("/config/platform-profiles/{profile_id}", response_model=ProfileResponse)
async def update_platform_profile(
    profile_id: str,
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a platform profile."""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    result = await db.execute(
        select(PlatformProfile).where(PlatformProfile.id == pid)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Platform profile not found")

    if data.name is not None:
        # Check for duplicate name
        dup = await db.execute(
            select(PlatformProfile).where(
                PlatformProfile.name == data.name,
                PlatformProfile.id != pid,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Platform profile with name '{data.name}' already exists",
            )
        profile.name = data.name
    if data.platform is not None:
        profile.platform = data.platform
    if data.dedupe_config is not None:
        profile.dedupe_config = data.dedupe_config
    if data.target_resolution is not None:
        profile.target_resolution = data.target_resolution
    if data.target_bitrate is not None:
        profile.target_bitrate = data.target_bitrate
    if data.max_duration is not None:
        profile.max_duration = data.max_duration

    await db.flush()
    await db.refresh(profile)
    return _serialize_profile(profile)