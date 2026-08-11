"""
Dashboard API routes - analytics and metrics for short drama operations.
"""

import io
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import (
    VideoMetric,
    MiniProgramMetric,
    AdMetric,
    DramaMetric,
    FunnelSnapshot,
    EcosystemMetric,
    SystemConfig,
)
from app.services import dashboard_service, data_import_service, smart_import_service
from app.utils.helpers import utc_iso

router = APIRouter()


# ---- Pydantic schemas ----

class VideoMetricResponse(BaseModel):
    id: str
    publish_task_id: Optional[str] = None
    video_id: Optional[str] = None
    title: Optional[str] = None
    publish_date: Optional[str] = None
    account_id: Optional[str] = None
    play_count: int = 0
    finish_rate: float = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    favorite_count: int = 0
    social_recommend_ratio: float = 0
    social_recommend_play: int = 0
    friend_recommend_play: int = 0
    jump_click_count: int = 0
    jump_click_rate: float = 0
    attributed_uv: int = 0
    attributed_revenue: float = 0
    content_type: Optional[str] = None
    drama_id: Optional[str] = None
    traffic_method: Optional[str] = None
    publish_time_slot: Optional[str] = None
    play_level: Optional[str] = None
    production_cost: float = 0
    recorded_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class VideoTagsUpdate(BaseModel):
    tags: list


class ImportResultResponse(BaseModel):
    success: bool
    imported_count: int = 0
    errors: list = []


class DashboardConfigResponse(BaseModel):
    config: dict


# ---- Serializers ----

def _serialize_video_metric(m: VideoMetric) -> dict:
    return {
        "id": str(m.id),
        "publish_task_id": str(m.publish_task_id) if m.publish_task_id else None,
        "video_id": m.video_id,
        "title": m.title,
        "publish_date": utc_iso(m.publish_date) if m.publish_date else None,
        "account_id": str(m.account_id) if m.account_id else None,
        "play_count": m.play_count or 0,
        "finish_rate": m.finish_rate or 0,
        "like_count": m.like_count or 0,
        "comment_count": m.comment_count or 0,
        "share_count": m.share_count or 0,
        "favorite_count": m.favorite_count or 0,
        "social_recommend_ratio": m.social_recommend_ratio or 0,
        "social_recommend_play": m.social_recommend_play or 0,
        "friend_recommend_play": m.friend_recommend_play or 0,
        "jump_click_count": m.jump_click_count or 0,
        "jump_click_rate": m.jump_click_rate or 0,
        "attributed_uv": m.attributed_uv or 0,
        "attributed_revenue": m.attributed_revenue or 0,
        "content_type": m.content_type,
        "tags": m.tags or [],
        "drama_id": str(m.drama_id) if m.drama_id else None,
        "traffic_method": m.traffic_method,
        "publish_time_slot": m.publish_time_slot,
        "play_level": m.play_level,
        "production_cost": m.production_cost or 0,
        "recorded_at": utc_iso(m.recorded_at) if m.recorded_at else "",
        "updated_at": utc_iso(m.updated_at) if m.updated_at else "",
    }


def _parse_account_id(account_id: Optional[str]) -> Optional[uuid.UUID]:
    """Parse and validate account_id parameter."""
    if not account_id:
        return None
    try:
        return uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id format")


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse date string to date object."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str}")


# ---- Overview endpoints ----

@router.get("/dashboard/overview")
async def get_overview(
    account_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get overview dashboard data: today_revenue, week_revenue, total_play, total_uv, ecpm, revenue_per_uv."""
    aid = _parse_account_id(account_id)
    target_date = _parse_date(date)
    return await dashboard_service.get_overview(db, aid, target_date)


@router.get("/dashboard/overview/trend")
async def get_overview_trend(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get trend data for overview charts."""
    aid = _parse_account_id(account_id)
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    return await dashboard_service.get_trend(db, aid, sd, ed)


@router.get("/dashboard/overview/funnel")
async def get_overview_funnel(
    account_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get funnel data for overview."""
    aid = _parse_account_id(account_id)
    target_date = _parse_date(date)
    return await dashboard_service.get_funnel(db, aid, target_date)


@router.get("/dashboard/overview/top-videos")
async def get_top_videos(
    account_id: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get top videos by attributed_revenue."""
    aid = _parse_account_id(account_id)
    return await dashboard_service.get_video_ranking(db, aid, sort_by="attributed_revenue", limit=limit)


# ---- Video metrics endpoints ----

@router.get("/dashboard/videos")
async def list_video_metrics(
    account_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: Optional[str] = Query("play_count"),
    content_type: Optional[str] = Query(None),
    play_level: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List video metrics with pagination and filters."""
    filters = []
    aid = _parse_account_id(account_id)
    if aid:
        filters.append(VideoMetric.account_id == aid)
    if content_type:
        filters.append(VideoMetric.content_type == content_type)
    if play_level:
        filters.append(VideoMetric.play_level == play_level)

    # Count total
    count_query = select(func.count(VideoMetric.id))
    if filters:
        count_query = count_query.where(and_(*filters))
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Sort
    valid_sort_columns = {
        "play_count", "finish_rate", "like_count", "comment_count",
        "share_count", "jump_click_count", "attributed_revenue",
        "publish_date", "recorded_at",
    }
    if sort_by not in valid_sort_columns:
        sort_by = "play_count"
    sort_column = getattr(VideoMetric, sort_by)

    # Paginate
    query = select(VideoMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(sort_column)).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    videos = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_video_metric(v) for v in videos],
    }


@router.get("/dashboard/videos/ranking")
async def get_video_ranking(
    account_id: Optional[str] = Query(None),
    sort_by: str = Query("play_count"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get video ranking by various metrics."""
    aid = _parse_account_id(account_id)
    return await dashboard_service.get_video_ranking(db, aid, sort_by=sort_by, limit=limit)


@router.get("/dashboard/videos/{video_id}")
async def get_video_detail(
    video_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get video metric detail."""
    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    result = await db.execute(select(VideoMetric).where(VideoMetric.id == vid))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video metric not found")

    return _serialize_video_metric(video)


@router.put("/dashboard/videos/{video_id}/tags")
async def update_video_tags(
    video_id: str,
    data: VideoTagsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update video tags (stored as JSON array in video_metrics.tags).

    视频标签系统（二期）：支持多标签，与 content_type 保持兼容（同时回写第一个标签）。
    """
    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    result = await db.execute(select(VideoMetric).where(VideoMetric.id == vid))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video metric not found")

    # 规范化标签：去空、去重、截断长度
    tags = [str(t).strip()[:50] for t in (data.tags or []) if str(t).strip()]
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    video.tags = unique_tags
    if unique_tags:
        video.content_type = unique_tags[0][:50]

    await db.flush()
    await db.refresh(video)
    return _serialize_video_metric(video)


# ---- Mini program metrics ----

@router.get("/dashboard/mini-program")
async def get_mini_program_metrics(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get mini program metrics."""
    filters = []
    aid = _parse_account_id(account_id)
    if aid:
        filters.append(MiniProgramMetric.account_id == aid)
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    if sd:
        filters.append(MiniProgramMetric.date >= sd)
    if ed:
        filters.append(MiniProgramMetric.date <= ed)

    query = select(MiniProgramMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(MiniProgramMetric.date))

    result = await db.execute(query)
    metrics = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "date": utc_iso(m.date) if m.date else None,
            "account_id": str(m.account_id) if m.account_id else None,
            "uv": m.uv or 0,
            "new_user_count": m.new_user_count or 0,
            "drama_play_count": m.drama_play_count or 0,
            "avg_play_duration": m.avg_play_duration or 0,
            "drama_finish_rate": m.drama_finish_rate or 0,
            "recorded_at": utc_iso(m.recorded_at) if m.recorded_at else None,
        }
        for m in metrics
    ]


# ---- Ad metrics ----

@router.get("/dashboard/ads")
async def get_ad_metrics(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get ad metrics."""
    filters = []
    aid = _parse_account_id(account_id)
    if aid:
        filters.append(AdMetric.account_id == aid)
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    if sd:
        filters.append(AdMetric.date >= sd)
    if ed:
        filters.append(AdMetric.date <= ed)

    query = select(AdMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(AdMetric.date))

    result = await db.execute(query)
    metrics = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "date": utc_iso(m.date) if m.date else None,
            "account_id": str(m.account_id) if m.account_id else None,
            "impression_count": m.impression_count or 0,
            "click_count": m.click_count or 0,
            "ctr": m.ctr or 0,
            "ecpm": m.ecpm or 0,
            "revenue": m.revenue or 0,
            "reward_video_impression": m.reward_video_impression or 0,
            "reward_video_revenue": m.reward_video_revenue or 0,
            "interstitial_impression": m.interstitial_impression or 0,
            "interstitial_revenue": m.interstitial_revenue or 0,
            "recorded_at": utc_iso(m.recorded_at) if m.recorded_at else None,
        }
        for m in metrics
    ]


# ---- Drama ranking ----

@router.get("/dashboard/dramas")
async def get_drama_ranking(
    account_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get drama ranking by play count or revenue."""
    filters = []
    aid = _parse_account_id(account_id)
    if aid:
        filters.append(DramaMetric.account_id == aid)
    target_date = _parse_date(date)
    if target_date:
        filters.append(DramaMetric.date == target_date)

    query = select(DramaMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(DramaMetric.play_count)).limit(limit)

    result = await db.execute(query)
    metrics = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "date": utc_iso(m.date) if m.date else None,
            "drama_id": str(m.drama_id) if m.drama_id else None,
            "account_id": str(m.account_id) if m.account_id else None,
            "uv": m.uv or 0,
            "play_count": m.play_count or 0,
            "finish_rate": m.finish_rate or 0,
            "ad_impression": m.ad_impression or 0,
            "ad_revenue": m.ad_revenue or 0,
            "recorded_at": utc_iso(m.recorded_at) if m.recorded_at else None,
        }
        for m in metrics
    ]


# ---- Funnel endpoints ----

@router.get("/dashboard/funnel")
async def get_funnel(
    account_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get funnel data."""
    aid = _parse_account_id(account_id)
    target_date = _parse_date(date)
    return await dashboard_service.get_funnel(db, aid, target_date)


@router.get("/dashboard/funnel/trend")
async def get_funnel_trend(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get funnel trend data over time."""
    filters = []
    aid = _parse_account_id(account_id)
    if aid:
        filters.append(FunnelSnapshot.account_id == aid)
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    if sd:
        filters.append(FunnelSnapshot.date >= sd)
    if ed:
        filters.append(FunnelSnapshot.date <= ed)

    query = select(FunnelSnapshot)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(FunnelSnapshot.date)

    result = await db.execute(query)
    snapshots = result.scalars().all()

    return [
        {
            "date": utc_iso(s.date) if s.date else None,
            "total_play": s.total_play or 0,
            "jump_click": s.jump_click or 0,
            "jump_rate": s.jump_rate or 0,
            "mini_program_uv": s.mini_program_uv or 0,
            "drama_play_uv": s.drama_play_uv or 0,
            "play_rate": s.play_rate or 0,
            "ad_exposure_uv": s.ad_exposure_uv or 0,
            "exposure_rate": s.exposure_rate or 0,
            "revenue": s.revenue or 0,
            "revenue_per_1000_play": s.revenue_per_1000_play or 0,
        }
        for s in snapshots
    ]


# ---- Data import endpoints ----

@router.post("/dashboard/metrics/video", response_model=ImportResultResponse)
async def import_video_metrics(
    file: UploadFile = File(...),
    account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Import video metrics from Excel file."""
    aid = _parse_account_id(account_id)
    result = await data_import_service.import_video_metrics(file, aid, db)
    return result


@router.post("/dashboard/metrics/mini-program", response_model=ImportResultResponse)
async def import_mini_program_metrics(
    file: UploadFile = File(...),
    account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Import mini program metrics from Excel file."""
    aid = _parse_account_id(account_id)
    result = await data_import_service.import_mini_program_metrics(file, aid, db)
    return result


@router.post("/dashboard/metrics/ads", response_model=ImportResultResponse)
async def import_ad_metrics(
    file: UploadFile = File(...),
    account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Import ad metrics from Excel file."""
    aid = _parse_account_id(account_id)
    result = await data_import_service.import_ad_metrics(file, aid, db)
    return result


@router.get("/dashboard/metrics/template")
async def download_import_template(
    type: str = Query("video", regex="^(video|mini_program|ad)$"),
):
    """Download Excel import template for metrics data."""
    try:
        content = await data_import_service.generate_import_template(type)
        filename = f"{type}_metrics_template.xlsx"
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- Dashboard config endpoints ----

@router.get("/dashboard/config")
async def get_dashboard_config(db: AsyncSession = Depends(get_db)):
    """Get dashboard configuration."""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "dashboard_config")
    )
    config = result.scalar_one_or_none()

    if config:
        return {"config": config.value}

    # Return defaults
    return {
        "config": {
            "default_account_id": None,
            "default_date_range": 30,
            "chart_colors": ["#1890ff", "#52c41a", "#faad14", "#f5222d"],
            "auto_refresh_interval": 300,
            "enable_funnel": True,
            "enable_ecosystem": True,
        }
    }


@router.put("/dashboard/config")
async def update_dashboard_config(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update dashboard configuration."""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "dashboard_config")
    )
    config = result.scalar_one_or_none()

    if config:
        config.value = data
        config.updated_at = datetime.utcnow()
    else:
        config = SystemConfig(key="dashboard_config", value=data)
        db.add(config)

    await db.flush()
    await db.refresh(config)

    return {"config": config.value}


# ---- Smart import endpoints ----

@router.post("/dashboard/import/upload")
async def smart_import_upload(
    file: UploadFile = File(...),
    account_id: Optional[str] = Query(None),
):
    """Smart import: upload file and auto-detect platform format."""
    aid = _parse_account_id(account_id)
    file_bytes = await file.read()
    result = await smart_import_service.detect_platform(file_bytes)
    return result


@router.post("/dashboard/import/preview")
async def import_preview(
    file: UploadFile = File(...),
):
    """Preview file content (headers + first 5 rows) for manual mapping."""
    file_bytes = await file.read()
    return await smart_import_service.preview_file(file_bytes)


@router.post("/dashboard/import/confirm")
async def import_confirm(
    file: UploadFile = File(...),
    mapping: str = Query(..., description="JSON string of field mapping"),
    target_table: str = Query(...),
    account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Confirm import with user-specified field mapping."""
    import json
    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid mapping JSON")

    aid = _parse_account_id(account_id)
    file_bytes = await file.read()
    return await smart_import_service.confirm_import(file_bytes, mapping_dict, target_table, aid, db)


@router.get("/dashboard/import/templates")
async def list_import_templates(
    db: AsyncSession = Depends(get_db),
):
    """Get saved import templates."""
    return await smart_import_service.get_import_templates(db)


@router.post("/dashboard/import/templates/custom")
async def save_custom_import_template(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Save a custom import template."""
    name = data.get("name", "")
    platform = data.get("platform", "custom")
    mapping = data.get("mapping", {})
    unit_conversions = data.get("unit_conversions")
    return await smart_import_service.save_custom_template(name, platform, mapping, unit_conversions, db)


@router.get("/dashboard/import/history")
async def list_import_history(
    db: AsyncSession = Depends(get_db),
):
    """Get import history records."""
    return await smart_import_service.get_import_history(db)


# ---- Ecosystem endpoints ----

@router.get("/dashboard/ecosystem")
async def get_ecosystem(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get ecosystem metrics (公众号/企微)."""
    aid = _parse_account_id(account_id)
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    return await smart_import_service.get_ecosystem_metrics(db, aid, sd, ed)


# ---- Cross analysis ----

@router.get("/dashboard/videos/cross-analysis")
async def get_cross_analysis(
    account_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Cross analysis: compare metrics across dimensions."""
    aid = _parse_account_id(account_id)
    return await smart_import_service.get_cross_analysis(db, aid, page, page_size)


# ---- Drama detail ----

@router.get("/dashboard/dramas/{drama_id}")
async def get_drama_detail(
    drama_id: str,
    account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get drama detail by drama_id."""
    filters = [DramaMetric.drama_id == drama_id]
    aid = _parse_account_id(account_id)
    if aid:
        filters.append(DramaMetric.account_id == aid)

    # Get summary
    result = await db.execute(
        select(
            func.sum(DramaMetric.uv).label("total_uv"),
            func.sum(DramaMetric.play_count).label("total_play"),
            func.avg(DramaMetric.finish_rate).label("avg_finish_rate"),
            func.sum(DramaMetric.ad_impression).label("total_ad_impression"),
            func.sum(DramaMetric.ad_revenue).label("total_ad_revenue"),
        ).where(and_(*filters))
    )
    row = result.one()
    summary = {
        "drama_id": drama_id,
        "total_uv": int(row[0] or 0),
        "total_play": int(row[1] or 0),
        "avg_finish_rate": round(float(row[2] or 0), 4),
        "total_ad_impression": int(row[3] or 0),
        "total_ad_revenue": round(float(row[4] or 0), 2),
    }

    # Get daily trend
    trend_query = select(DramaMetric).where(and_(*filters)).order_by(DramaMetric.date)
    trend_result = await db.execute(trend_query)
    trend = [
        {
            "date": utc_iso(m.date) if m.date else None,
            "uv": m.uv or 0,
            "play_count": m.play_count or 0,
            "finish_rate": m.finish_rate or 0,
            "ad_impression": m.ad_impression or 0,
            "ad_revenue": m.ad_revenue or 0,
        }
        for m in trend_result.scalars().all()
    ]

    return {"summary": summary, "trend": trend}


# ---- Funnel compare ----

@router.get("/dashboard/funnel/compare")
async def get_funnel_compare(
    account_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get funnel comparison: this week vs last week."""
    aid = _parse_account_id(account_id)
    today = date.today()
    # Current week: Monday to today
    monday = today - __import__("datetime").timedelta(days=today.weekday())
    # Last week
    last_monday = monday - __import__("datetime").timedelta(days=7)
    last_sunday = monday - __import__("datetime").timedelta(days=1)

    def build_filter(start, end):
        f = [FunnelSnapshot.date >= start, FunnelSnapshot.date <= end]
        if aid:
            f.append(FunnelSnapshot.account_id == aid)
        return f

    this_week = await db.execute(
        select(
            func.avg(FunnelSnapshot.jump_rate).label("avg_jump_rate"),
            func.avg(FunnelSnapshot.play_rate).label("avg_play_rate"),
            func.avg(FunnelSnapshot.exposure_rate).label("avg_exposure_rate"),
            func.sum(FunnelSnapshot.revenue).label("total_revenue"),
        ).where(and_(*build_filter(monday, today)))
    )
    last_week = await db.execute(
        select(
            func.avg(FunnelSnapshot.jump_rate).label("avg_jump_rate"),
            func.avg(FunnelSnapshot.play_rate).label("avg_play_rate"),
            func.avg(FunnelSnapshot.exposure_rate).label("avg_exposure_rate"),
            func.sum(FunnelSnapshot.revenue).label("total_revenue"),
        ).where(and_(*build_filter(last_monday, last_sunday)))
    )

    tw = this_week.one()
    lw = last_week.one()

    def calc_change(current, previous):
        if previous and previous > 0:
            return round((current - previous) / previous * 100, 1)
        return 0

    return {
        "this_week": {
            "avg_jump_rate": round(float(tw[0] or 0), 2),
            "avg_play_rate": round(float(tw[1] or 0), 2),
            "avg_exposure_rate": round(float(tw[2] or 0), 2),
            "total_revenue": round(float(tw[3] or 0), 2),
        },
        "last_week": {
            "avg_jump_rate": round(float(lw[0] or 0), 2),
            "avg_play_rate": round(float(lw[1] or 0), 2),
            "avg_exposure_rate": round(float(lw[2] or 0), 2),
            "total_revenue": round(float(lw[3] or 0), 2),
        },
        "changes": {
            "jump_rate_change": calc_change(float(tw[0] or 0), float(lw[0] or 0)),
            "play_rate_change": calc_change(float(tw[1] or 0), float(lw[1] or 0)),
            "exposure_rate_change": calc_change(float(tw[2] or 0), float(lw[2] or 0)),
            "revenue_change": calc_change(float(tw[3] or 0), float(lw[3] or 0)),
        },
    }


# ============================================================================
# 短片分析（P3）：分视频号/抖音综合展现
# 链路：短片生成(shortdrama_prompts) → 发布(publish_tasks) → 平台数据(video_metrics)
# ============================================================================


def _serialize_shortdrama_analysis_row(v: VideoMetric, ctx: dict) -> dict:
    """把平台数据行与短片生成侧信息拼装成综合展示行。

    ctx 预加载：publish_tasks（by id）、shortdrama_prompts（by id）、publish_materials（by id）。
    """
    pt = ctx.get("tasks", {}).get(str(v.publish_task_id)) if v.publish_task_id else None
    prompt = None
    material = None
    if pt:
        prompt = ctx.get("prompts", {}).get(str(pt.prompt_record_id)) if pt.prompt_record_id else None
        material = ctx.get("materials", {}).get(str(pt.material_id)) if pt.material_id else None
    # 若发布任务未直接关联提示词记录，尝试通过发布素材回退（素材 → 提示词）
    if not prompt and material and material.prompt_record_id:
        prompt = ctx.get("prompts", {}).get(str(material.prompt_record_id))

    # 平台/账号：优先取发布任务冗余快照，再退化为 video_metrics 自身字段
    platform = (pt.platform if pt else None) or v.platform
    account_name = (pt.account_name if pt else None) or None

    # 生成侧信息
    prompt_record_id = str(pt.prompt_record_id) if pt and pt.prompt_record_id else None
    if not prompt_record_id and prompt:
        prompt_record_id = str(prompt.id)
    generation = {
        "prompt_record_id": prompt_record_id,
        "material_id": str(pt.material_id) if pt and pt.material_id else None,
        "source_text": prompt.source_text[:120] if prompt else None,
        "duration": prompt.duration if prompt else None,
        "theme": prompt.theme if prompt else None,
        "tone": prompt.tone if prompt else None,
        "short_title": material.material_json.get("short_title") if material and material.material_json else None,
        "material_tags": (material.material_json.get("tags") or {}).get("all", [])
        if material and material.material_json else [],
    }

    return {
        "video_metric_id": str(v.id),
        "publish_task_id": str(v.publish_task_id) if v.publish_task_id else None,
        "platform": platform,
        "account_name": account_name,
        "video_id": v.video_id,
        "title": v.title,
        "publish_date": utc_iso(v.publish_date) if v.publish_date else None,
        "play_count": v.play_count or 0,
        "finish_rate": v.finish_rate or 0,
        "like_count": v.like_count or 0,
        "comment_count": v.comment_count or 0,
        "share_count": v.share_count or 0,
        "favorite_count": v.favorite_count or 0,
        "jump_click_count": v.jump_click_count or 0,
        "jump_click_rate": v.jump_click_rate or 0,
        "attributed_uv": v.attributed_uv or 0,
        "attributed_revenue": v.attributed_revenue or 0,
        "tags": v.tags or [],
        "generation": generation,
    }


@router.get("/dashboard/shortdrama/analysis")
async def get_shortdrama_analysis(
    platform: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """短片分析综合列表：平台数据 JOIN 发布任务 JOIN 短片生成元数据。

    - platform 过滤（wechat_channel / douyin / kuaishou，缺省为全部）
    - 未关联到短片来源的历史视频 generation 显示 null（前端显示「-」）
    """
    from app.models.models import PublishTask, ShortdramaPrompt, PublishMaterial

    filters = []
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    if sd:
        filters.append(VideoMetric.publish_date >= sd)
    if ed:
        filters.append(VideoMetric.publish_date <= ed)

    # 平台过滤：video_metrics.platform 或 关联 publish_tasks.platform 任一命中
    if platform:
        task_ids = (
            await db.execute(
                select(PublishTask.id).where(PublishTask.platform == platform)
            )
        ).scalars().all()
        filters.append(
            or_(
                VideoMetric.platform == platform,
                VideoMetric.publish_task_id.in_(task_ids) if task_ids else False,
            )
        )

    count_query = select(func.count(VideoMetric.id))
    if filters:
        count_query = count_query.where(and_(*filters))
    total = (await db.execute(count_query)).scalar() or 0

    query = select(VideoMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(VideoMetric.publish_date), desc(VideoMetric.recorded_at))
    query = query.offset((page - 1) * page_size).limit(page_size)
    videos = (await db.execute(query)).scalars().all()

    # 预加载关联数据，避免 N+1
    task_ids = [v.publish_task_id for v in videos if v.publish_task_id]
    tasks_map = {}
    prompts_map = {}
    materials_map = {}
    if task_ids:
        tasks = (await db.execute(select(PublishTask).where(PublishTask.id.in_(task_ids)))).scalars().all()
        tasks_map = {str(t.id): t for t in tasks}
        prompt_ids = [t.prompt_record_id for t in tasks if t.prompt_record_id]
        material_ids = [t.material_id for t in tasks if t.material_id]
        if material_ids:
            materials = (await db.execute(select(PublishMaterial).where(PublishMaterial.id.in_(material_ids)))).scalars().all()
            materials_map = {str(m.id): m for m in materials}
            # 素材回退关联的提示词记录也一并预加载
            prompt_ids = prompt_ids + [m.prompt_record_id for m in materials if m.prompt_record_id]
        if prompt_ids:
            prompts = (await db.execute(select(ShortdramaPrompt).where(ShortdramaPrompt.id.in_(prompt_ids)))).scalars().all()
            prompts_map = {str(p.id): p for p in prompts}

    ctx = {"tasks": tasks_map, "prompts": prompts_map, "materials": materials_map}
    items = [_serialize_shortdrama_analysis_row(v, ctx) for v in videos]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/dashboard/shortdrama/summary")
async def get_shortdrama_summary(
    platform: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """短片分析 KPI：发布条数 / 总播放 / 平均完播率 / 总跳转 / 归因收益。"""
    from app.models.models import PublishTask

    filters = []
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    if sd:
        filters.append(VideoMetric.publish_date >= sd)
    if ed:
        filters.append(VideoMetric.publish_date <= ed)
    if platform:
        task_ids = (
            await db.execute(
                select(PublishTask.id).where(PublishTask.platform == platform)
            )
        ).scalars().all()
        filters.append(
            or_(
                VideoMetric.platform == platform,
                VideoMetric.publish_task_id.in_(task_ids) if task_ids else False,
            )
        )

    agg = await db.execute(
        select(
            func.count(VideoMetric.id),
            func.coalesce(func.sum(VideoMetric.play_count), 0),
            func.coalesce(func.avg(VideoMetric.finish_rate), 0),
            func.coalesce(func.sum(VideoMetric.jump_click_count), 0),
            func.coalesce(func.sum(VideoMetric.attributed_revenue), 0),
        ).where(and_(*filters)) if filters
        else select(
            func.count(VideoMetric.id),
            func.coalesce(func.sum(VideoMetric.play_count), 0),
            func.coalesce(func.avg(VideoMetric.finish_rate), 0),
            func.coalesce(func.sum(VideoMetric.jump_click_count), 0),
            func.coalesce(func.sum(VideoMetric.attributed_revenue), 0),
        )
    )
    row = agg.one()
    return {
        "platform": platform,
        "published_count": int(row[0] or 0),
        "total_play": int(row[1] or 0),
        "avg_finish_rate": round(float(row[2] or 0), 2),
        "total_jump_click": int(row[3] or 0),
        "attributed_revenue": round(float(row[4] or 0), 2),
    }


@router.get("/dashboard/shortdrama/topics")
async def get_shortdrama_topics(
    platform: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """短片分析话题标签 TOP 排行（取发布素材话题标签聚合）。"""
    from app.models.models import PublishTask, PublishMaterial

    filters = []
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    if sd:
        filters.append(VideoMetric.publish_date >= sd)
    if ed:
        filters.append(VideoMetric.publish_date <= ed)
    if platform:
        task_ids = (
            await db.execute(
                select(PublishTask.id).where(PublishTask.platform == platform)
            )
        ).scalars().all()
        filters.append(
            or_(
                VideoMetric.platform == platform,
                VideoMetric.publish_task_id.in_(task_ids) if task_ids else False,
            )
        )

    # 话题排行：限制取最近的数据窗口（limit * 20 条采样），避免全量加载
    base_query = select(VideoMetric)
    if filters:
        base_query = base_query.where(and_(*filters))
    base_query = base_query.order_by(
        desc(VideoMetric.publish_date), desc(VideoMetric.recorded_at)
    ).limit(limit * 20)
    videos = (await db.execute(base_query)).scalars().all()
    task_ids = [v.publish_task_id for v in videos if v.publish_task_id]
    if not task_ids:
        return []

    tasks = (await db.execute(select(PublishTask).where(PublishTask.id.in_(task_ids)))).scalars().all()
    material_ids = [t.material_id for t in tasks if t.material_id]
    if not material_ids:
        return []
    materials = (await db.execute(select(PublishMaterial).where(PublishMaterial.id.in_(material_ids)))).scalars().all()

    counter = {}
    for m in materials:
        if not m.material_json:
            continue
        tags = (m.material_json.get("tags") or {}).get("all", [])
        for tag in tags:
            tag = str(tag).strip()
            if tag:
                counter[tag] = counter.get(tag, 0) + 1
    ranked = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"tag": tag, "count": count} for tag, count in ranked]
