"""
Dashboard service - data aggregation and analytics for the v2 dashboard.

Provides overview statistics, video rankings, funnel data, and trend analysis
for the short drama operations dashboard.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    VideoMetric,
    MiniProgramMetric,
    AdMetric,
    DramaMetric,
    FunnelSnapshot,
    EcosystemMetric,
)

logger = logging.getLogger(__name__)


async def get_overview(
    db: AsyncSession,
    account_id: Optional[uuid.UUID] = None,
    target_date: Optional[date] = None,
) -> dict:
    """
    Get overview dashboard data.

    Returns aggregated metrics:
    - today_revenue: today's total ad revenue
    - week_revenue: last 7 days total revenue
    - total_play: total play count (all time or filtered)
    - total_uv: total unique visitors
    - ecpm: effective cost per mille
    - revenue_per_uv: average revenue per UV
    """
    if target_date is None:
        target_date = date.today()

    # Build base filter
    base_filter = []
    if account_id:
        base_filter.append(VideoMetric.account_id == account_id)

    # Today's revenue from ad_metrics
    today_filter = [AdMetric.date == target_date]
    if account_id:
        today_filter.append(AdMetric.account_id == account_id)

    today_result = await db.execute(
        select(func.coalesce(func.sum(AdMetric.revenue), 0)).where(and_(*today_filter))
    )
    today_revenue = float(today_result.scalar() or 0)

    # Week revenue (last 7 days)
    week_start = target_date - timedelta(days=6)
    week_filter = [AdMetric.date >= week_start, AdMetric.date <= target_date]
    if account_id:
        week_filter.append(AdMetric.account_id == account_id)

    week_result = await db.execute(
        select(func.coalesce(func.sum(AdMetric.revenue), 0)).where(and_(*week_filter))
    )
    week_revenue = float(week_result.scalar() or 0)

    # Total play count from video_metrics
    play_result = await db.execute(
        select(func.coalesce(func.sum(VideoMetric.play_count), 0)).where(and_(*base_filter)) if base_filter
        else select(func.coalesce(func.sum(VideoMetric.play_count), 0))
    )
    total_play = int(play_result.scalar() or 0)

    # Total UV from mini_program_metrics
    uv_filter = []
    if account_id:
        uv_filter.append(MiniProgramMetric.account_id == account_id)

    uv_result = await db.execute(
        select(func.coalesce(func.sum(MiniProgramMetric.uv), 0)).where(and_(*uv_filter)) if uv_filter
        else select(func.coalesce(func.sum(MiniProgramMetric.uv), 0))
    )
    total_uv = int(uv_result.scalar() or 0)

    # eCPM from ad_metrics
    ecpm_filter = [AdMetric.date == target_date]
    if account_id:
        ecpm_filter.append(AdMetric.account_id == account_id)

    ecpm_result = await db.execute(
        select(func.coalesce(func.avg(AdMetric.ecpm), 0)).where(and_(*ecpm_filter))
    )
    ecpm = float(ecpm_result.scalar() or 0)

    # Today's UV (same-day denominator for revenue_per_uv)
    today_uv_filter = [MiniProgramMetric.date == target_date]
    if account_id:
        today_uv_filter.append(MiniProgramMetric.account_id == account_id)
    today_uv_result = await db.execute(
        select(func.coalesce(func.sum(MiniProgramMetric.uv), 0)).where(and_(*today_uv_filter))
    )
    today_uv = int(today_uv_result.scalar() or 0)

    revenue_per_uv = (today_revenue / today_uv) if today_uv > 0 else 0

    return {
        "today_revenue": round(today_revenue, 2),
        "week_revenue": round(week_revenue, 2),
        "total_play": total_play,
        "total_uv": total_uv,
        "today_uv": today_uv,
        "ecpm": round(ecpm, 2),
        "revenue_per_uv": round(revenue_per_uv, 4),
        "date": target_date.isoformat(),
    }


async def get_video_ranking(
    db: AsyncSession,
    account_id: Optional[uuid.UUID] = None,
    sort_by: str = "play_count",
    limit: int = 20,
) -> list:
    """
    Get video ranking by various metrics.

    Supported sort_by values: play_count, finish_rate, like_count, comment_count,
    share_count, jump_click_count, attributed_revenue
    """
    # Validate sort column
    valid_sort_columns = {
        "play_count", "finish_rate", "like_count", "comment_count",
        "share_count", "jump_click_count", "attributed_revenue",
        "favorite_count", "social_recommend_play", "attributed_uv",
    }
    if sort_by not in valid_sort_columns:
        sort_by = "play_count"

    sort_column = getattr(VideoMetric, sort_by)

    filters = []
    if account_id:
        filters.append(VideoMetric.account_id == account_id)

    query = select(VideoMetric)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(sort_column)).limit(limit)

    result = await db.execute(query)
    videos = result.scalars().all()

    return [
        {
            "id": str(v.id),
            "video_id": v.video_id,
            "title": v.title,
            "publish_date": v.publish_date.isoformat() if v.publish_date else None,
            "play_count": v.play_count or 0,
            "finish_rate": v.finish_rate or 0,
            "like_count": v.like_count or 0,
            "comment_count": v.comment_count or 0,
            "share_count": v.share_count or 0,
            "jump_click_count": v.jump_click_count or 0,
            "attributed_revenue": v.attributed_revenue or 0,
            "content_type": v.content_type,
            "play_level": v.play_level,
        }
        for v in videos
    ]


async def get_funnel(
    db: AsyncSession,
    account_id: Optional[uuid.UUID] = None,
    target_date: Optional[date] = None,
) -> dict:
    """
    Get funnel data: play -> jump -> mini_uv -> ad_impression -> revenue.

    Returns funnel snapshot data with conversion rates between stages.
    """
    if target_date is None:
        target_date = date.today()

    filters = [FunnelSnapshot.date == target_date]
    if account_id:
        filters.append(FunnelSnapshot.account_id == account_id)

    result = await db.execute(
        select(FunnelSnapshot).where(and_(*filters)).order_by(desc(FunnelSnapshot.recorded_at)).limit(1)
    )
    snapshot = result.scalar_one_or_none()

    if snapshot:
        return {
            "date": snapshot.date.isoformat() if snapshot.date else None,
            "total_play": snapshot.total_play or 0,
            "jump_click": snapshot.jump_click or 0,
            "jump_rate": snapshot.jump_rate or 0,
            "mini_program_uv": snapshot.mini_program_uv or 0,
            "drama_play_uv": snapshot.drama_play_uv or 0,
            "play_rate": snapshot.play_rate or 0,
            "ad_exposure_uv": snapshot.ad_exposure_uv or 0,
            "exposure_rate": snapshot.exposure_rate or 0,
            "revenue": snapshot.revenue or 0,
            "revenue_per_1000_play": snapshot.revenue_per_1000_play or 0,
        }

    # If no snapshot, compute from raw metrics
    video_filter = [VideoMetric.publish_date == target_date]
    if account_id:
        video_filter.append(VideoMetric.account_id == account_id)

    play_result = await db.execute(
        select(func.coalesce(func.sum(VideoMetric.play_count), 0)).where(and_(*video_filter))
    )
    total_play = int(play_result.scalar() or 0)

    jump_result = await db.execute(
        select(func.coalesce(func.sum(VideoMetric.jump_click_count), 0)).where(and_(*video_filter))
    )
    jump_click = int(jump_result.scalar() or 0)

    mp_filter = [MiniProgramMetric.date == target_date]
    if account_id:
        mp_filter.append(MiniProgramMetric.account_id == account_id)

    mp_result = await db.execute(
        select(func.coalesce(func.sum(MiniProgramMetric.uv), 0)).where(and_(*mp_filter))
    )
    mini_program_uv = int(mp_result.scalar() or 0)

    ad_filter = [AdMetric.date == target_date]
    if account_id:
        ad_filter.append(AdMetric.account_id == account_id)

    ad_result = await db.execute(
        select(
            func.coalesce(func.sum(AdMetric.impression_count), 0),
            func.coalesce(func.sum(AdMetric.revenue), 0),
        ).where(and_(*ad_filter))
    )
    row = ad_result.one()
    ad_impression = int(row[0] or 0)
    revenue = float(row[1] or 0)

    drama_filter = [DramaMetric.date == target_date]
    if account_id:
        drama_filter.append(DramaMetric.account_id == account_id)
    drama_result = await db.execute(
        select(func.coalesce(func.sum(DramaMetric.uv), 0)).where(and_(*drama_filter))
    )
    drama_play_uv = int(drama_result.scalar() or 0)

    jump_rate = (jump_click / total_play * 100) if total_play > 0 else 0
    play_rate = (drama_play_uv / mini_program_uv * 100) if mini_program_uv > 0 else 0
    exposure_rate = (ad_impression / mini_program_uv * 100) if mini_program_uv > 0 else 0
    revenue_per_1000 = (revenue / total_play * 1000) if total_play > 0 else 0

    return {
        "date": target_date.isoformat(),
        "total_play": total_play,
        "jump_click": jump_click,
        "jump_rate": round(jump_rate, 2),
        "mini_program_uv": mini_program_uv,
        "drama_play_uv": drama_play_uv,
        "play_rate": round(play_rate, 2),
        "ad_exposure_uv": ad_impression,
        "exposure_rate": round(exposure_rate, 2),
        "revenue": round(revenue, 2),
        "revenue_per_1000_play": round(revenue_per_1000, 2),
    }


async def get_trend(
    db: AsyncSession,
    account_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list:
    """
    Get time series data for charts.

    Returns daily aggregated data points for the specified date range.
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=29)  # Default 30 days

    # Get video metrics trend
    video_filter = [
        VideoMetric.publish_date >= start_date,
        VideoMetric.publish_date <= end_date,
    ]
    if account_id:
        video_filter.append(VideoMetric.account_id == account_id)

    video_trend = await db.execute(
        select(
            VideoMetric.publish_date,
            func.sum(VideoMetric.play_count).label("play_count"),
            func.sum(VideoMetric.like_count).label("like_count"),
            func.sum(VideoMetric.comment_count).label("comment_count"),
            func.sum(VideoMetric.share_count).label("share_count"),
            func.sum(VideoMetric.jump_click_count).label("jump_click_count"),
            func.sum(VideoMetric.attributed_revenue).label("attributed_revenue"),
        )
        .where(and_(*video_filter))
        .group_by(VideoMetric.publish_date)
        .order_by(VideoMetric.publish_date)
    )

    # Get ad metrics trend
    ad_filter = [
        AdMetric.date >= start_date,
        AdMetric.date <= end_date,
    ]
    if account_id:
        ad_filter.append(AdMetric.account_id == account_id)

    ad_trend = await db.execute(
        select(
            AdMetric.date,
            func.sum(AdMetric.revenue).label("revenue"),
            func.sum(AdMetric.impression_count).label("impression_count"),
            func.avg(AdMetric.ecpm).label("ecpm"),
        )
        .where(and_(*ad_filter))
        .group_by(AdMetric.date)
        .order_by(AdMetric.date)
    )

    # Merge into unified trend data
    video_data = {
        str(row[0]): {
            "play_count": int(row[1] or 0),
            "like_count": int(row[2] or 0),
            "comment_count": int(row[3] or 0),
            "share_count": int(row[4] or 0),
            "jump_click_count": int(row[5] or 0),
            "attributed_revenue": float(row[6] or 0),
        }
        for row in video_trend.all()
    }

    ad_data = {
        str(row[0]): {
            "revenue": float(row[1] or 0),
            "impression_count": int(row[2] or 0),
            "ecpm": float(row[3] or 0),
        }
        for row in ad_trend.all()
    }

    # Build unified trend list
    trend = []
    current = start_date
    while current <= end_date:
        date_str = str(current)
        point = {
            "date": date_str,
            "play_count": 0,
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "jump_click_count": 0,
            "attributed_revenue": 0,
            "revenue": 0,
            "impression_count": 0,
            "ecpm": 0,
        }
        if date_str in video_data:
            point.update(video_data[date_str])
        if date_str in ad_data:
            point.update(ad_data[date_str])
        trend.append(point)
        current += timedelta(days=1)

    return trend
