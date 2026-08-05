"""
Smart import service - automatically detect platform export format and import data.

Supports three modes:
1. Auto-detect mode: Match file headers against known platform fingerprints
2. Manual mapping mode: User drags column mappings in the UI
3. Standard template mode: Download template and fill in data
"""

import asyncio
import io
import logging
import uuid
from datetime import date, datetime
from functools import partial
from typing import Any, Optional

import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ImportTemplate, ImportHistory, VideoMetric, MiniProgramMetric, AdMetric
from app.services.data_import_service import import_video_metrics

logger = logging.getLogger(__name__)

# ==================== Platform Fingerprints ====================

PLATFORM_FINGERPRINTS = {
    "wechat_channels_creator": {
        "name": "视频号创作者中心",
        "required_headers": ["播放量", "完播率"],
        "optional_headers": ["点赞", "评论", "转发", "收藏", "分享", "新增粉丝"],
        "transforms": {
            "播放量": "play_count",
            "完播率": "finish_rate",
            "点赞": "like_count",
            "评论": "comment_count",
            "转发": "share_count",
            "收藏": "favorite_count",
        },
        "target_table": "video_metrics",
    },
    "wechat_miniprogram_analysis": {
        "name": "小程序数据分析",
        "required_headers": ["访问用户数", "访问次数"],
        "optional_headers": ["新增用户", "人均停留时长", "页面留存率"],
        "transforms": {
            "访问用户数": "uv",
            "访问次数": "pv",
            "新增用户": "new_user_count",
            "人均停留时长": "avg_duration",
        },
        "target_table": "mini_program_metrics",
    },
    "wechat_ad_platform": {
        "name": "广告/流量主后台",
        "required_headers": ["曝光量", "点击量"],
        "optional_headers": ["点击率", "收入", "eCPM", "结算金额"],
        "transforms": {
            "曝光量": "impression_count",
            "点击量": "click_count",
            "点击率": "ctr",
            "收入": ("revenue", lambda x: float(x) / 100),
            "eCPM": "ecpm",
            "结算金额": ("revenue", lambda x: float(x) / 100),
        },
        "unit_conversions": {
            "revenue": {"from": "分", "to": "元", "factor": 0.01},
        },
        "target_table": "ad_metrics",
    },
    "douyin_creator": {
        "name": "抖音创作者中心",
        "required_headers": ["播放量", "点赞数"],
        "optional_headers": ["评论数", "分享数", "收藏数", "完播率"],
        "transforms": {
            "播放量": "play_count",
            "点赞数": "like_count",
            "评论数": "comment_count",
            "分享数": "share_count",
        },
        "target_table": "video_metrics",
    },
    "kuaishou_creator": {
        "name": "快手创作者中心",
        "required_headers": ["播放数", "点赞数"],
        "optional_headers": ["评论数", "转发数", "完播率"],
        "transforms": {
            "播放数": "play_count",
            "点赞数": "like_count",
            "评论数": "comment_count",
            "转发数": "share_count",
        },
        "target_table": "video_metrics",
    },
}


def _normalize_headers(headers: list) -> list:
    """Normalize header names: strip whitespace, remove non-breaking spaces."""
    return [h.strip().replace("\u00a0", " ").replace("\ufeff", "") for h in headers]


def _read_headers_sync(file_bytes: bytes) -> list:
    """Read column headers from an Excel/CSV file."""
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", nrows=0)
        return list(df.columns)
    except Exception:
        pass
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=0)
        return list(df.columns)
    except Exception:
        return []


def _read_preview_sync(file_bytes: bytes, nrows: int = 5) -> list:
    """Read preview rows from a file."""
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", nrows=nrows)
        return df.fillna("").to_dict(orient="records")
    except Exception:
        pass
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=nrows)
        return df.fillna("").to_dict(orient="records")
    except Exception:
        return []


def _detect_platform(headers: list) -> Optional[dict]:
    """
    Detect the platform by matching headers against known fingerprints.
    Returns the matched platform fingerprint dict, or None.
    """
    normalized = [h.lower().strip() for h in headers]
    best_match = None
    best_score = 0

    for platform_id, fingerprint in PLATFORM_FINGERPRINTS.items():
        required = [r.lower() for r in fingerprint["required_headers"]]
        optional = [o.lower() for o in fingerprint["optional_headers"]]
        matched_required = sum(1 for r in required if any(r in n for n in normalized))
        matched_optional = sum(1 for o in optional if any(o in n for n in normalized))

        score = matched_required * 2 + matched_optional
        if matched_required >= len(required) and score > best_score:
            best_score = score
            best_match = {"platform_id": platform_id, **fingerprint}

    return best_match


def _transform_row_sync(
    df: pd.DataFrame,
    mapping: dict,
    target_table: str,
) -> list:
    """
    Transform a DataFrame using the field mapping.
    mapping: {target_field: source_column_name}
    Returns list of dicts ready for import.
    """
    df = df.fillna("")
    records = []
    for _, row in df.iterrows():
        record = {}
        for target_field, source_col in mapping.items():
            if source_col in row:
                val = row[source_col]
                if isinstance(val, str) and val.strip() == "":
                    val = 0
                record[target_field] = val
        records.append(record)
    return records


async def detect_platform(file_bytes: bytes) -> dict:
    """
    Detect platform from file content.
    Returns detected platform info or None.
    """
    loop = asyncio.get_event_loop()
    headers = await loop.run_in_executor(None, _read_headers_sync, file_bytes)
    if not headers:
        return {"detected": False, "headers": [], "platform": None}

    normalized = _normalize_headers(headers)
    match = await loop.run_in_executor(None, _detect_platform, normalized)

    # Preview rows
    preview = await loop.run_in_executor(None, _read_preview_sync, file_bytes, 5)

    if match:
        return {
            "detected": True,
            "headers": headers,
            "platform": match,
            "preview": preview,
            "suggested_mapping": match["transforms"],
            "target_table": match.get("target_table", "video_metrics"),
        }
    return {
        "detected": False,
        "headers": headers,
        "platform": None,
        "preview": preview,
        "suggested_mapping": {},
        "target_table": None,
    }


async def preview_file(file_bytes: bytes) -> dict:
    """
    Preview file content (headers + first N rows).
    """
    loop = asyncio.get_event_loop()
    headers = await loop.run_in_executor(None, _read_headers_sync, file_bytes)
    preview = await loop.run_in_executor(None, _read_preview_sync, file_bytes, 5)
    return {
        "headers": headers or [],
        "preview": preview or [],
        "total_rows": len(preview) if preview else 0,
    }


async def confirm_import(
    file_bytes: bytes,
    mapping: dict,
    target_table: str,
    account_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> dict:
    """
    Confirm import with user-specified mapping.
    """
    loop = asyncio.get_event_loop()

    # Read all data
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes))

    df = df.fillna("")
    records = _transform_row_sync(df, mapping, target_table)

    if not records:
        return {"success": False, "imported_count": 0, "errors": ["没有可导入的数据"]}

    # Convert to a file-like object and delegate to existing importers
    # Build a simple file-like wrapper
    class BytesFileWrapper:
        def __init__(self, data: bytes, name: str = "import.xlsx"):
            self.file = io.BytesIO(data)
            self.filename = name

    wrapped = BytesFileWrapper(file_bytes)

    if target_table == "video_metrics":
        result = await import_video_metrics(wrapped, account_id, db)
    elif target_table == "mini_program_metrics":
        from app.services.data_import_service import import_mini_program_metrics
        result = await import_mini_program_metrics(wrapped, account_id, db)
    elif target_table == "ad_metrics":
        from app.services.data_import_service import import_ad_metrics
        result = await import_ad_metrics(wrapped, account_id, db)
    else:
        return {"success": False, "imported_count": 0, "errors": [f"未知的目标表: {target_table}"]}

    return result


async def get_import_templates(db: AsyncSession) -> list:
    """Get saved import templates."""
    result = await db.execute(select(ImportTemplate).order_by(ImportTemplate.created_at.desc()))
    templates = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "platform": t.platform,
            "mapping": t.mapping,
            "unit_conversions": t.unit_conversions,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in templates
    ]


async def save_custom_template(
    name: str,
    platform: str,
    mapping: dict,
    unit_conversions: Optional[dict],
    db: AsyncSession,
) -> dict:
    """Save a custom import template."""
    template = ImportTemplate(
        name=name,
        platform=platform,
        mapping=mapping,
        unit_conversions=unit_conversions or {},
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return {
        "id": str(template.id),
        "name": template.name,
        "platform": template.platform,
        "mapping": template.mapping,
        "unit_conversions": template.unit_conversions,
        "created_at": template.created_at.isoformat() if template.created_at else None,
    }


async def get_import_history(db: AsyncSession) -> list:
    """Get import history records."""
    result = await db.execute(
        select(ImportHistory).order_by(ImportHistory.created_at.desc()).limit(50)
    )
    records = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "file_name": r.file_name,
            "platform": r.platform,
            "import_mode": r.import_mode,
            "target_table": r.target_table,
            "imported_count": r.imported_count,
            "updated_count": r.updated_count,
            "error_count": r.error_count,
            "errors": r.errors or [],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


async def get_ecosystem_metrics(
    db: AsyncSession,
    account_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list:
    """Get ecosystem metrics (公众号/企微)."""
    from app.models.models import EcosystemMetric

    filters = []
    if account_id:
        filters.append(EcosystemMetric.account_id == account_id)
    if start_date:
        filters.append(EcosystemMetric.date >= start_date)
    if end_date:
        filters.append(EcosystemMetric.date <= end_date)

    query = select(EcosystemMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(EcosystemMetric.date.desc())

    result = await db.execute(query)
    metrics = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "date": m.date.isoformat() if m.date else None,
            "account_id": str(m.account_id) if m.account_id else None,
            "article_count": m.article_count or 0,
            "article_read_count": m.article_read_count or 0,
            "mini_program_uv_from_article": m.mini_program_uv_from_article or 0,
            "wecom_new_friends": m.wecom_new_friends or 0,
            "wecom_total_friends": m.wecom_total_friends or 0,
            "wecom_source": m.wecom_source,
            "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
        }
        for m in metrics
    ]


async def get_cross_analysis(
    db: AsyncSession,
    account_id: Optional[uuid.UUID] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Cross analysis: compare video metrics across dimensions.
    Groups by content_type, traffic_method, publish_time_slot, play_level.
    """
    filters = []
    if account_id:
        filters.append(VideoMetric.account_id == account_id)

    base_query = select(VideoMetric)
    if filters:
        base_query = base_query.where(and_(*filters))

    # Aggregate by content_type
    from sqlalchemy import func as sa_func

    type_agg = await db.execute(
        select(
            VideoMetric.content_type,
            sa_func.count(VideoMetric.id).label("video_count"),
            sa_func.avg(VideoMetric.play_count).label("avg_play"),
            sa_func.avg(VideoMetric.finish_rate).label("avg_finish_rate"),
            sa_func.avg(VideoMetric.jump_click_rate).label("avg_jump_rate"),
            sa_func.sum(VideoMetric.attributed_revenue).label("total_revenue"),
        )
        .where(and_(*filters) if filters else sa_func.true())
        .group_by(VideoMetric.content_type)
        .order_by(sa_func.sum(VideoMetric.attributed_revenue).desc())
    )

    return {
        "by_content_type": [
            {
                "content_type": row[0] or "未分类",
                "video_count": int(row[1] or 0),
                "avg_play": round(float(row[2] or 0), 0),
                "avg_finish_rate": round(float(row[3] or 0), 4),
                "avg_jump_rate": round(float(row[4] or 0), 4),
                "total_revenue": round(float(row[5] or 0), 2),
            }
            for row in type_agg.all()
        ],
    }