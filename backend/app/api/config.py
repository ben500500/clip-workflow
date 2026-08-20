import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import SystemConfig, PlatformProfile
from app.utils.helpers import utc_iso

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
    "default_dedupe_config": "默认去重参数（新四层体系）：preset 为基础档位(light/standard/heavy)；manual 可逐项覆盖各去重手段（crop/hflip/speed/saturation/gamma/contrast/brightness/colorbalance/colortemperature/noise/scanline/vignette/roll_band/jitter/sharpen/watermark），未填 manual 时沿用 preset 预设。用于切片时降低平台查重风险。",
    "default_interval_config": "区间检测默认参数：mode 为检测模式(credits 片尾字幕/static 静止画面/watermark 水印)；scan_window 扫描窗口(秒)；frame_interval 抽帧间隔(秒)；static_threshold 静止画面判定阈值；gold_ratio_threshold 黄金比例阈值；min_static_duration 静止画面最短持续时间(秒)。",
    "storage_retention_days": "素材与成品文件保留天数，超过该时限的临时文件会被自动清理。",
    "auto_cleanup_enabled": "是否启用自动清理任务（true/false）。开启后系统会定时清理过期临时资源文件。",
    "max_concurrent_tasks": "全局最大并发切片任务数，用于限制多人同时切片时同时执行的切片任务数量（不含区间检测），避免任务无限堆积抢占资源。当前达到上限时新的切片/重试请求会被拒绝，可在多人协作繁忙时适当调大。",
    "task_timeout_hours": "任务超时时间（小时），超过该时长的任务将被判定为超时并自动终止。",
    "dashboard_config": "数据看板配置（JSON）：用于配置看板展示的指标与筛选条件。",
    "shortdrama_seedance_config": "短片制作 Seedance 官方 API 直连配置（JSON）：enabled 为总开关（默认 false）；model 模型名；resolution 480p/720p/1080p；watermark 是否加水印；long_duration_policy 超 10s 策略（truncate/block）；timeout 超时秒；daily_quota 日配额（0=不限）。api_key 配置环境变量 SEEDANCE_API_KEY。",
    "asr_method": "语音识别(ASR)引擎：aliyun_speech=阿里云 qwen3-asr-flash(需 DASHSCOPE_API_KEY)；whisper=本地 faster-whisper(无需 Key)；funasr_local=本地 FunASR SenseVoice(需安装 FunASR 运行时，未装前选择会失败)。",
    "publish_rate_config": "发布风控/节奏参数（JSON）：acct_limit 单账号每日发布上限；op_limit 单运营者每日发布上限；op_inflight_limit 单运营者并发在途上限；global_inflight_limit 全局并发在途上限；min_delay_ms/max_delay_ms 发布 tab 启动前随机延迟区间(毫秒)；fingerprint_variant 是否启用 UA/指纹变体。用于多运营者发布时降低风控风险，支持运行时热更。",
    "default_download_resolution": "资源下载默认分辨率：720p 或 1080p（默认 720p）。下载视频资源入库时按该分辨率统一缩放，节省存储并适配各平台主流清晰度。",
    "lan_source_config": "局域网获取剧集配置（JSON）：enabled 为总开关（默认 false，开启后剧目详情页显示「局域网获取剧集」面板）；base_url 为 dupload cdn 源基础地址；manage_base 为 IAA 管理平台基础地址（可选，提供剧目清单）；api_prefix 为剧集清单接口路径前缀（可选）；download_timeout 为单集拉流整体超时(秒)；queue 为导入任务队列；default_project 为默认入库归属项目名；concurrency 为每集 HTTP 下载并发数。可在系统设置热更，无需改 .env。",
    "dupload_config": "推送到下载平台(dupload)配置（JSON）：enabled 为总开关（默认 false，开启后剧目详情页出现「推送到下载平台」区块）；base_url 为 dupload 服务基础地址（默认 http://192.168.1.21:8800）；import_path 为批量导入接口路径（默认 /api/dupload/tasks）；action 为动作（only_download 仅下载 / upload_miniapp 上传小程序，默认 only_download）；share_url_field 为剧目模型里素材链接(shareUrl)的字段名（默认 material_link）；request_timeout 为单次请求超时(秒)；work_host 可选指定推送的单个主机(字符串)，work_hosts 可选指定推送的主机列表(数组)，均未配置时默认拉取 dupload 全部 hosts 逐台推送；app_secret 可选(按 workHost 匹配，缺省时尝试从 hosts 接口探测，否则传空串)；cp_id 为批量导入接口必填字段（POST /api/dupload/tasks 公开无鉴权，缺任一返回 422，保存后 app_secret 不回显）；auth_headers 为附加鉴权请求头(JSON，可放 Authorization/Cookie 等，保存后不回显，接口公开时可留空)。可在系统设置热更，无需改 .env。",
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
            "preset": "std_crop_desat",
            "manual": {
                "crop": 0.05,
                "hflip": False,
                "speed": 1.03,
                "saturation": 0.90,
                "gamma": 1.02,
                "contrast": 1.02,
                "brightness": 0.008,
                "noise": 0,
                "vignette": None,
                "roll_band": 0,
                "jitter": 0,
                "sharpen": 0.3,
                "watermark": None,
            },
        },
        "description": "默认去重参数（新四层体系）：preset 为基础档位(light/standard/heavy 或 std_crop_desat/std_retro_scan)；manual 可逐项覆盖各去重手段（crop/hflip/speed/saturation/gamma/contrast/brightness/noise/vignette/roll_band/jitter/sharpen/watermark），未填 manual 时沿用 preset 预设。默认档位统一不做视频镜像（hflip=False）。用于切片时降低平台查重风险。",
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
    {
        "key": "dashboard_config",
        "value": {
            "default_account_id": None,
            "default_date_range": 30,
            "chart_colors": ["#1890ff", "#52c41a", "#faad14", "#f5222d"],
            "auto_refresh_interval": 300,
            "enable_funnel": True,
            "enable_ecosystem": True,
        },
        "description": "数据看板配置（JSON）：用于配置看板展示的指标与筛选条件。",
    },
    {
        "key": "shortdrama_seedance_config",
        "value": {
            "enabled": False,
            "model": "seedance-1-0-pro-250528",
            "resolution": "1080p",
            "watermark": True,
            "long_duration_policy": "truncate",
            "timeout": 600,
            "daily_quota": 0,
        },
        "description": "短片制作 Seedance 官方 API 直连配置（JSON）：enabled 为总开关（默认 false，关闭时前端不展示该通道、后端接口返回 403）；model 为火山方舟模型名/接入点；resolution 480p/720p/1080p；watermark 是否加水印；long_duration_policy 为超 10s 策略（truncate 截成10s / block 拒绝）；timeout 生成超时秒；daily_quota 日配额（0=不限）。api_key 请配置环境变量 SEEDANCE_API_KEY。",
    },
    {
        "key": "asr_method",
        "value": "whisper",
        "description": "语音识别(ASR)引擎：aliyun_speech=阿里云 qwen3-asr-flash(需 DASHSCOPE_API_KEY)；whisper=本地 faster-whisper(无需 Key)；funasr_local=本地 FunASR SenseVoice(需安装 FunASR 运行时，未装前选择会失败)。",
    },
    {
        "key": "publish_rate_config",
        "value": {
            "acct_limit": 20,
            "op_limit": 20,
            "op_inflight_limit": 1,
            "global_inflight_limit": 4,
            "min_delay_ms": 0,
            "max_delay_ms": 0,
            "fingerprint_variant": False
        },
        "description": "发布风控/节奏参数（JSON）：acct_limit 单账号每日发布上限；op_limit 单运营者每日发布上限；op_inflight_limit 单运营者并发在途上限；global_inflight_limit 全局并发在途上限；min_delay_ms/max_delay_ms 发布 tab 启动前随机延迟区间(毫秒)；fingerprint_variant 是否启用 UA/指纹变体。用于多运营者发布时降低风控风险，支持运行时热更。",
    },
    {
        "key": "default_download_resolution",
        "value": "720p",
        "description": "资源下载默认分辨率：720p 或 1080p（默认 720p）。下载视频资源入库时按该分辨率统一缩放。",
    },
    {
        "key": "lan_source_config",
        "value": {
            "enabled": False,
            "base_url": "http://192.168.1.163:8765",
            "manage_base": "http://192.168.1.21:8800",
            "api_prefix": "",
            "download_timeout": 900,
            "queue": "lan_source",
            "default_project": "局域网导入",
            "concurrency": 2,
        },
        "description": "局域网获取剧集配置（JSON）：enabled 为总开关（默认 false，开启后剧目详情页出现「局域网获取剧集」面板）；base_url 为 dupload cdn 源基础地址（回退路径，默认 192.168.1.163:8765）；manage_base 为 IAA 小程序管理平台基础地址（**剧集直链主来源**：/api/ext/drama/{name}/videos，默认 192.168.1.21:8800）；api_prefix 剧集清单接口路径前缀（可选）；download_timeout 单集拉流整体超时(秒)；default_project 默认入库归属项目名；concurrency 每集 HTTP 下载并发数。配置保存后即时生效，无需重启。",
    },
    {
        "key": "dupload_config",
        "value": {
            "enabled": True,
            "base_url": "http://192.168.1.21:8800",
            "import_path": "/api/dupload/tasks",
            "action": "only_download",
            "share_url_field": "material_link",
            "request_timeout": 30,
            "work_host": "",
            "work_hosts": [],
            "app_secret": "",
            "cp_id": "",
            "auth_headers": {},
        },
        "description": "推送到下载平台(dupload)配置（JSON）：enabled 为总开关（默认 false，开启后剧目详情页出现「推送到下载平台」区块）；base_url 为 dupload 服务基础地址（默认 http://192.168.1.21:8800）；import_path 为批量导入接口路径（默认 /api/dupload/tasks）；action 为动作（only_download 仅下载 / upload_miniapp 上传小程序，默认 only_download）；share_url_field 为剧目模型里素材链接(shareUrl)的字段名（默认 material_link）；request_timeout 为单次请求超时(秒)；work_host 可选指定推送的单个主机(字符串)，work_hosts 可选指定推送的主机列表(数组)，均未配置时默认拉取 dupload 全部 hosts 逐台推送；app_secret 可选(按 workHost 匹配，缺省时尝试从 hosts 接口探测，否则传空串)；cp_id 为批量导入接口必填字段（POST /api/dupload/tasks 公开无鉴权，缺任一返回 422，保存后 app_secret 不回显）；auth_headers 为附加鉴权请求头(JSON，可放 Authorization/Cookie 等，保存后不回显，接口公开时可留空)。配置保存后即时生效，无需重启。",
    },
]


# 平台去重默认配置：首次部署/空库时预置几套常用配置，方便开箱即用
# 默认分辨率统一为 720p（码率相应降低），适配各平台主流的清晰度与查重需求
DEFAULT_PLATFORM_PROFILES: List[dict] = [
    {
        "name": "视频号-轻度去重",
        "platform": "wechat_channel",
        "description": "视频号默认去重配方（预设 light + 手动微调）：轻微变速+轻微降饱和+轻锐化+半透明贴纸水印；统一不做镜像，明显影响画质的效果均降到最低，兼顾成片质量与查重。",
        "dedupe_config": {
            "preset": "light",
            "manual": {
                "crop": 0.02,
                "hflip": False,
                "speed": 1.03,
                "saturation": 0.92,
                "brightness": 0.01,
                "sharpen": 0.6,
                "watermark": {"text": "WHYH", "opacity": 0.22, "position": "bottom-right"},
            },
        },
        "target_resolution": "1280x720",
        "target_bitrate": "2500k",
        "max_duration": 180,
    },
    {
        "name": "抖音-标准去重",
        "platform": "douyin",
        "description": "抖音标准去重配方（预设 standard）：变速+轻微降饱和+轻锐化+贴纸水印；统一不做镜像，去掉明显影响画质的噪点/扫描线/偏色/色温/暗角。",
        "dedupe_config": {
            "preset": "standard",
            "manual": {
                "hflip": False,
                "speed": 1.05,
                "sharpen": 0.8,
                "watermark": {"text": "DY原创", "opacity": 0.25, "position": "top-right"},
            },
        },
        "target_resolution": "720x1280",
        "target_bitrate": "2500k",
        "max_duration": 150,
    },
    {
        "name": "快手-深度去重",
        "platform": "kuaishou",
        "description": "快手深度去重配方（预设 heavy + 手动强化）：较大幅度变速/轻微降饱和+锐化+贴纸水印；统一不做镜像，去掉滚动暗带等明显影响画质的效果。",
        "dedupe_config": {
            "preset": "heavy",
            "manual": {
                "hflip": False,
                "speed": 1.08,
                "sharpen": 1.0,
                "watermark": {"text": "KS精选", "opacity": 0.28, "position": "bottom-center"},
            },
        },
        "target_resolution": "720x1280",
        "target_bitrate": "2200k",
        "max_duration": 150,
    },
]


# 各平台常见分辨率/码率快捷选项（调研整理，供前端下拉快捷选择）
# 码率为目标码率（kbps），分辨率横向优先（竖屏平台也列出竖屏分辨率）
PLATFORM_PRESETS: dict[str, list[dict]] = {
    "wechat_channel": [
        {"label": "720p 横屏 1280x720 · 2500k", "target_resolution": "1280x720", "target_bitrate": "2500k"},
        {"label": "720p 竖屏 720x1280 · 2500k", "target_resolution": "720x1280", "target_bitrate": "2500k"},
        {"label": "1080p 横屏 1920x1080 · 5000k", "target_resolution": "1920x1080", "target_bitrate": "5000k"},
        {"label": "1080p 竖屏 1080x1920 · 5000k", "target_resolution": "1080x1920", "target_bitrate": "5000k"},
    ],
    "douyin": [
        {"label": "720p 竖屏 720x1280 · 2500k", "target_resolution": "720x1280", "target_bitrate": "2500k"},
        {"label": "720p 横屏 1280x720 · 2500k", "target_resolution": "1280x720", "target_bitrate": "2500k"},
        {"label": "1080p 竖屏 1080x1920 · 5000k", "target_resolution": "1080x1920", "target_bitrate": "5000k"},
        {"label": "1080p 横屏 1920x1080 · 5000k", "target_resolution": "1920x1080", "target_bitrate": "5000k"},
    ],
    "kuaishou": [
        {"label": "720p 竖屏 720x1280 · 2200k", "target_resolution": "720x1280", "target_bitrate": "2200k"},
        {"label": "720p 横屏 1280x720 · 2200k", "target_resolution": "1280x720", "target_bitrate": "2200k"},
        {"label": "1080p 竖屏 1080x1920 · 4500k", "target_resolution": "1080x1920", "target_bitrate": "4500k"},
        {"label": "1080p 横屏 1920x1080 · 4500k", "target_resolution": "1920x1080", "target_bitrate": "4500k"},
    ],
}


def _default_profile_for(profile: PlatformProfile) -> dict | None:
    """按平台/名称匹配内置默认去重配置（用于恢复默认）。"""
    for seed in DEFAULT_PLATFORM_PROFILES:
        if seed["name"] == profile.name:
            return seed
    for seed in DEFAULT_PLATFORM_PROFILES:
        if seed.get("platform") == profile.platform:
            return seed
    return None


def _serialize_config(cfg: SystemConfig) -> dict:
    return {
        "key": cfg.key,
        "value": cfg.value,
        "description": cfg.description or CONFIG_DESCRIPTIONS.get(cfg.key),
        "updated_at": utc_iso(cfg.updated_at) if cfg.updated_at else "",
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
        "created_at": utc_iso(profile.created_at) if profile.created_at else "",
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


@router.post("/config/reset-default", response_model=ConfigResponse)
async def reset_config_default(
    data: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """系统设置：将指定配置项恢复为默认值.

    默认值取自 DEFAULT_CONFIGS；对 JSON 类配置（default_dedupe_config 等）同样适用。
    恢复后删除数据库中的覆盖记录，使其重新展示默认值。
    """
    default = next((d for d in DEFAULT_CONFIGS if d["key"] == data.key), None)
    if default is None:
        raise HTTPException(status_code=404, detail=f"配置项 {data.key} 没有内置默认值")

    # 删除数据库中的覆盖记录（若有），使其回落到默认值
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == data.key)
    )
    config = result.scalar_one_or_none()
    if config:
        await db.delete(config)
        await db.flush()

    return ConfigResponse(
        key=default["key"],
        value=default["value"],
        description=default["description"],
        updated_at="",
    )


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


@router.post("/config/platform-profiles/{profile_id}/reset-default", response_model=ProfileResponse)
async def reset_platform_profile_default(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
):
    """去重配置：将指定平台配置恢复为内置默认值（含去重 JSON、分辨率、码率、最大时长）。

    注意：用户自建配置若无同名内置默认，则按其平台匹配默认配置；
    若均未匹配则返回 404。
    """
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

    default = _default_profile_for(profile)
    if default is None:
        raise HTTPException(
            status_code=404,
            detail="该配置没有内置默认值，无法恢复默认（可新建配置）",
        )

    profile.dedupe_config = default.get("dedupe_config")
    profile.target_resolution = default.get("target_resolution")
    profile.target_bitrate = default.get("target_bitrate")
    profile.max_duration = default.get("max_duration")
    profile.description = default.get("description") or profile.description

    await db.flush()
    await db.refresh(profile)
    return _serialize_profile(profile)


@router.get("/config/platform-presets")
async def get_platform_presets():
    """返回各平台常见分辨率/码率快捷选项（供前端下拉选择）."""
    return {
        "presets": PLATFORM_PRESETS,
        "defaults": {
            p["platform"]: {
                "target_resolution": p.get("target_resolution"),
                "target_bitrate": p.get("target_bitrate"),
            }
            for p in DEFAULT_PLATFORM_PROFILES
            if p.get("platform")
        },
    }


@router.delete("/config/platform-profiles/{profile_id}", status_code=204)
async def delete_platform_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除平台去重配置."""
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

    await db.delete(profile)
    await db.flush()
    return None