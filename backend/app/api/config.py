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
    description: Optional[str] = None
    updated_at: str


class ProfileCreate(BaseModel):
    name: str
    platform: str
    description: Optional[str] = None
    dedupe_config: Optional[dict] = None
    target_resolution: Optional[str] = None
    target_bitrate: Optional[str] = None
    max_duration: Optional[int] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    description: Optional[str] = None
    dedupe_config: Optional[dict] = None
    target_resolution: Optional[str] = None
    target_bitrate: Optional[str] = None
    max_duration: Optional[int] = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    platform: Optional[str] = None
    description: Optional[str] = None
    dedupe_config: Optional[dict] = None
    target_resolution: Optional[str] = None
    target_bitrate: Optional[str] = None
    max_duration: Optional[int] = None
    created_at: str

    model_config = {"from_attributes": True}


CONFIG_DESCRIPTIONS: Dict[str, str] = {
    "default_autoclip_config": "AI 智能选点默认参数：min_score_threshold 为入选最低评分(0-100)；max_clips 为最多生成的候选片段数；min_duration/max_duration 为候选片段的最短/最长时长(秒)，超出范围的高光片段会被裁剪或过滤。",
    "default_dedupe_config": "默认去重参数：mode 为去重模式(fast/dedupe/scrub)；flip_mirror 水平镜像翻转；speed_change 微调播放速度；saturation_value/brightness_value 为饱和度/亮度微调系数；sharpen_amount 锐化强度。用于切片时降低平台查重风险。",
    "default_interval_config": "区间检测默认参数：mode 为检测模式(credits 片尾字幕/static 静止画面/watermark 水印)；scan_window 扫描窗口(秒)；frame_interval 抽帧间隔(秒)；static_threshold 静止画面判定阈值；gold_ratio_threshold 黄金比例阈值；min_static_duration 静止画面最短持续时间(秒)。",
    "storage_retention_days": "素材与成品文件保留天数，超过该时限的临时文件会被自动清理。",
    "auto_cleanup_enabled": "是否启用自动清理任务（true/false）。开启后系统会定时清理过期临时资源文件。",
    "max_concurrent_tasks": "全局最大并发切片任务数，用于限制多人同时切片时同时执行的切片任务数量（不含区间检测），避免任务无限堆积抢占资源。当前达到上限时新的切片/重试请求会被拒绝，可在多人协作繁忙时适当调大。",
    "task_timeout_hours": "任务超时时间（小时），超过该时长的任务将被判定为超时并自动终止。",
    "dashboard_config": "数据看板配置（JSON）：用于配置看板展示的指标与筛选条件。",
}


DEFAULT_CONFIGS: List[dict] = [
    {
        "key": "default_autoclip_config",
        "value": {
            "llm_provider": "dashscope",
            "llm_model": "qwen-plus",
            "min_score_threshold": 60,
            "max_clips": 30,
            "min_duration": 30,
            "max_duration": 180,
        },
        "description": "AI 智能选点默认参数：min_score_threshold 为入选最低评分(0-100)；max_clips 为最多生成的候选片段数；min_duration/max_duration 为候选片段的最短/最长时长(秒)，超出范围的高光片段会被裁剪或过滤。",
    },
    {
        "key": "default_dedupe_config",
        "value": {
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
        "description": "默认去重参数：mode 为去重模式(fast/dedupe/scrub)；flip_mirror 水平镜像翻转；speed_change 微调播放速度；saturation_value/brightness_value 为饱和度/亮度微调系数；sharpen_amount 锐化强度。用于切片时降低平台查重风险。",
    },
    {
        "key": "default_interval_config",
        "value": {
            "mode": "credits",
            "scan_window": 6.0,
            "frame_interval": 0.5,
            "static_threshold": 5,
            "gold_ratio_threshold": 0.03,
            "min_static_duration": 9,
        },
        "description": "区间检测默认参数：mode 为检测模式(credits 片尾字幕/static 静止画面/watermark 水印)；scan_window 扫描窗口(秒)；frame_interval 抽帧间隔(秒)；static_threshold 静止画面判定阈值；gold_ratio_threshold 黄金比例阈值；min_static_duration 静止画面最短持续时间(秒)。",
    },
    {
        "key": "storage_retention_days",
        "value": 30,
        "description": "素材与成品文件保留天数，超过该时限的临时文件会被自动清理。",
    },
    {
        "key": "auto_cleanup_enabled",
        "value": False,
        "description": "是否启用自动清理任务（true/false）。开启后系统会定时清理过期临时资源文件。",
    },
    {
        "key": "max_concurrent_tasks",
        "value": 4,
        "description": "全局最大并发切片任务数，用于限制多人同时切片时同时执行的切片任务数量（不含区间检测），避免任务无限堆积抢占资源。当前达到上限时新的切片/重试请求会被拒绝，可在多人协作繁忙时适当调大。",
    },
    {
        "key": "task_timeout_hours",
        "value": 2,
        "description": "任务超时时间（小时），超过该时长的任务将被判定为超时并自动终止。",
    },
]


# 平台去重默认配置：首次部署/空库时预置几套常用配置，方便开箱即用
DEFAULT_PLATFORM_PROFILES: List[dict] = [
    {
        "name": "视频号-轻度去重",
        "platform": "wechat_channel",
        "description": "视频号默认去重配置：轻微变速+饱和度微调，兼顾成片质量与查重，适合常规内容分发。",
        "dedupe_config": {
            "mode": "fast",
            "flip_mirror": False,
            "speed_change": True,
            "speed_factor": 1.03,
            "saturation": True,
            "saturation_value": 0.96,
            "brightness": True,
            "brightness_value": 0.01,
            "sharpen": True,
            "sharpen_amount": 0.6,
        },
        "target_resolution": "1920x1080",
        "target_bitrate": "4000k",
        "max_duration": 180,
    },
    {
        "name": "抖音-标准去重",
        "platform": "douyin",
        "description": "抖音标准去重配置：镜像翻转+变速+饱和/亮度/锐化综合处理，降低平台查重风险。",
        "dedupe_config": {
            "mode": "dedupe",
            "flip_mirror": True,
            "speed_change": True,
            "speed_factor": 1.05,
            "saturation": True,
            "saturation_value": 0.93,
            "brightness": True,
            "brightness_value": 0.02,
            "sharpen": True,
            "sharpen_amount": 1.0,
        },
        "target_resolution": "1920x1080",
        "target_bitrate": "5000k",
        "max_duration": 150,
    },
    {
        "name": "快手-深度去重",
        "platform": "kuaishou",
        "description": "快手深度去重配置：镜像+较大幅度变速/色调调整，用于高查重风险的二创内容。",
        "dedupe_config": {
            "mode": "dedupe",
            "flip_mirror": True,
            "speed_change": True,
            "speed_factor": 1.08,
            "saturation": True,
            "saturation_value": 0.9,
            "brightness": True,
            "brightness_value": 0.03,
            "sharpen": True,
            "sharpen_amount": 1.2,
        },
        "target_resolution": "1920x1080",
        "target_bitrate": "4500k",
        "max_duration": 150,
    },
]


def _serialize_config(cfg: SystemConfig) -> dict:
    return {
        "key": cfg.key,
        "value": cfg.value,
        "description": cfg.description or CONFIG_DESCRIPTIONS.get(cfg.key),
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else "",
    }


def _serialize_profile(profile: PlatformProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "platform": profile.platform,
        "description": profile.description,
        "dedupe_config": profile.dedupe_config,
        "target_resolution": profile.target_resolution,
        "target_bitrate": profile.target_bitrate,
        "max_duration": profile.max_duration,
        "created_at": profile.created_at.isoformat() if profile.created_at else "",
    }


@router.get("/config", response_model=List[ConfigResponse])
async def get_all_config(db: AsyncSession = Depends(get_db)):
    """Get all system configuration key-value pairs.

    默认配置与数据库中已保存的配置合并返回：
    - 数据库中的配置（用户已修改/新增）优先返回其值；
    - 数据库中不存在的默认配置项仍会展示，避免“修改一项后其它配置项消失”。
    """
    result = await db.execute(
        select(SystemConfig)
    )
    configs = result.scalars().all()
    saved = {c.key: c for c in configs}

    merged: List[ConfigResponse] = []
    for default in DEFAULT_CONFIGS:
        saved_cfg = saved.pop(default["key"], None)
        if saved_cfg is not None:
            merged.append(_serialize_config(saved_cfg))
        else:
            merged.append(ConfigResponse(
                key=default["key"],
                value=default["value"],
                description=default["description"],
                updated_at="",
            ))
    # 数据库中用户新增的自定义配置项也一并返回
    for key in sorted(saved.keys()):
        merged.append(_serialize_config(saved[key]))

    return merged


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
        if not config.description:
            config.description = CONFIG_DESCRIPTIONS.get(data.key)
    else:
        config = SystemConfig(
            key=data.key,
            value=data.value,
            description=CONFIG_DESCRIPTIONS.get(data.key),
        )
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
        description=data.description,
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
    if data.description is not None:
        profile.description = data.description
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