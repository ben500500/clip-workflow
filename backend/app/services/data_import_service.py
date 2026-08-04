"""
Data import service - Excel bulk import for metrics data.

Handles importing video metrics, mini program metrics, and ad metrics
from Excel files using pandas. Validates required columns before import.
"""

import logging
import uuid
from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import VideoMetric, MiniProgramMetric, AdMetric

logger = logging.getLogger(__name__)


# Required columns for each import type
VIDEO_METRICS_REQUIRED_COLUMNS = ["video_id", "title", "publish_date"]
VIDEO_METRICS_OPTIONAL_COLUMNS = [
    "play_count", "finish_rate", "like_count", "comment_count", "share_count",
    "favorite_count", "social_recommend_ratio", "social_recommend_play",
    "friend_recommend_play", "jump_click_count", "jump_click_rate",
    "attributed_uv", "attributed_revenue", "content_type", "drama_id",
    "traffic_method", "publish_time_slot", "play_level", "production_cost",
]

MINI_PROGRAM_REQUIRED_COLUMNS = ["date"]
MINI_PROGRAM_OPTIONAL_COLUMNS = [
    "uv", "new_user_count", "drama_play_count", "avg_play_duration", "drama_finish_rate",
]

AD_METRICS_REQUIRED_COLUMNS = ["date"]
AD_METRICS_OPTIONAL_COLUMNS = [
    "impression_count", "click_count", "ctr", "ecpm", "revenue",
    "reward_video_impression", "reward_video_revenue",
    "interstitial_impression", "interstitial_revenue",
]


def _validate_columns(df: pd.DataFrame, required: list, import_type: str) -> list:
    """
    Validate that required columns exist in the DataFrame.

    Returns a list of error messages (empty if valid).
    """
    errors = []
    df_columns_lower = [c.strip().lower() for c in df.columns]
    for col in required:
        if col.lower() not in df_columns_lower:
            errors.append(f"缺少必填列: {col}")
    return errors


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to lowercase and strip whitespace."""
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def _parse_date(value) -> Optional[date]:
    """Parse a date value from various formats."""
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(str(value)).date()
    except (ValueError, TypeError):
        return None


def _safe_int(value, default=0) -> int:
    """Safely convert a value to int."""
    if pd.isna(value):
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value, default=0.0) -> float:
    """Safely convert a value to float."""
    if pd.isna(value):
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


async def import_video_metrics(
    file,
    account_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> dict:
    """
    Import video metrics from an Excel file.

    Args:
        file: Upload file (Excel format)
        account_id: Account ID to associate with imported records
        db: Database session

    Returns:
        dict with import results: success, imported_count, errors
    """
    try:
        # Read Excel file
        df = pd.read_excel(file.file, engine="openpyxl")
        df = _normalize_columns(df)

        # Validate required columns
        errors = _validate_columns(df, VIDEO_METRICS_REQUIRED_COLUMNS, "video_metrics")
        if errors:
            return {"success": False, "imported_count": 0, "errors": errors}

        imported_count = 0
        import_errors = []

        for idx, row in df.iterrows():
            try:
                publish_date = _parse_date(row.get("publish_date"))
                if not publish_date:
                    import_errors.append(f"行 {idx + 2}: 无效的 publish_date")
                    continue

                # Parse drama_id if present
                drama_id = None
                if pd.notna(row.get("drama_id")):
                    try:
                        drama_id = uuid.UUID(str(row["drama_id"]))
                    except ValueError:
                        pass

                metric = VideoMetric(
                    video_id=str(row.get("video_id", "")),
                    title=str(row.get("title", ""))[:500],
                    publish_date=publish_date,
                    account_id=account_id,
                    play_count=_safe_int(row.get("play_count")),
                    finish_rate=_safe_float(row.get("finish_rate")),
                    like_count=_safe_int(row.get("like_count")),
                    comment_count=_safe_int(row.get("comment_count")),
                    share_count=_safe_int(row.get("share_count")),
                    favorite_count=_safe_int(row.get("favorite_count")),
                    social_recommend_ratio=_safe_float(row.get("social_recommend_ratio")),
                    social_recommend_play=_safe_int(row.get("social_recommend_play")),
                    friend_recommend_play=_safe_int(row.get("friend_recommend_play")),
                    jump_click_count=_safe_int(row.get("jump_click_count")),
                    jump_click_rate=_safe_float(row.get("jump_click_rate")),
                    attributed_uv=_safe_int(row.get("attributed_uv")),
                    attributed_revenue=_safe_float(row.get("attributed_revenue")),
                    content_type=str(row.get("content_type", ""))[:50] if pd.notna(row.get("content_type")) else None,
                    drama_id=drama_id,
                    traffic_method=str(row.get("traffic_method", ""))[:50] if pd.notna(row.get("traffic_method")) else None,
                    publish_time_slot=str(row.get("publish_time_slot", ""))[:10] if pd.notna(row.get("publish_time_slot")) else None,
                    play_level=str(row.get("play_level", ""))[:10] if pd.notna(row.get("play_level")) else None,
                    production_cost=_safe_float(row.get("production_cost")),
                )
                db.add(metric)
                imported_count += 1

            except Exception as e:
                import_errors.append(f"行 {idx + 2}: {str(e)}")

        await db.flush()

        return {
            "success": True,
            "imported_count": imported_count,
            "errors": import_errors,
        }

    except Exception as e:
        logger.error(f"Video metrics import failed: {e}", exc_info=True)
        return {"success": False, "imported_count": 0, "errors": [str(e)]}


async def import_mini_program_metrics(
    file,
    account_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> dict:
    """
    Import mini program metrics from an Excel file.

    Args:
        file: Upload file (Excel format)
        account_id: Account ID to associate with imported records
        db: Database session

    Returns:
        dict with import results: success, imported_count, errors
    """
    try:
        df = pd.read_excel(file.file, engine="openpyxl")
        df = _normalize_columns(df)

        errors = _validate_columns(df, MINI_PROGRAM_REQUIRED_COLUMNS, "mini_program_metrics")
        if errors:
            return {"success": False, "imported_count": 0, "errors": errors}

        imported_count = 0
        import_errors = []

        for idx, row in df.iterrows():
            try:
                record_date = _parse_date(row.get("date"))
                if not record_date:
                    import_errors.append(f"行 {idx + 2}: 无效的 date")
                    continue

                metric = MiniProgramMetric(
                    date=record_date,
                    account_id=account_id,
                    uv=_safe_int(row.get("uv")),
                    new_user_count=_safe_int(row.get("new_user_count")),
                    drama_play_count=_safe_int(row.get("drama_play_count")),
                    avg_play_duration=_safe_float(row.get("avg_play_duration")),
                    drama_finish_rate=_safe_float(row.get("drama_finish_rate")),
                )
                db.add(metric)
                imported_count += 1

            except Exception as e:
                import_errors.append(f"行 {idx + 2}: {str(e)}")

        await db.flush()

        return {
            "success": True,
            "imported_count": imported_count,
            "errors": import_errors,
        }

    except Exception as e:
        logger.error(f"Mini program metrics import failed: {e}", exc_info=True)
        return {"success": False, "imported_count": 0, "errors": [str(e)]}


async def import_ad_metrics(
    file,
    account_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> dict:
    """
    Import ad metrics from an Excel file.

    Args:
        file: Upload file (Excel format)
        account_id: Account ID to associate with imported records
        db: Database session

    Returns:
        dict with import results: success, imported_count, errors
    """
    try:
        df = pd.read_excel(file.file, engine="openpyxl")
        df = _normalize_columns(df)

        errors = _validate_columns(df, AD_METRICS_REQUIRED_COLUMNS, "ad_metrics")
        if errors:
            return {"success": False, "imported_count": 0, "errors": errors}

        imported_count = 0
        import_errors = []

        for idx, row in df.iterrows():
            try:
                record_date = _parse_date(row.get("date"))
                if not record_date:
                    import_errors.append(f"行 {idx + 2}: 无效的 date")
                    continue

                metric = AdMetric(
                    date=record_date,
                    account_id=account_id,
                    impression_count=_safe_int(row.get("impression_count")),
                    click_count=_safe_int(row.get("click_count")),
                    ctr=_safe_float(row.get("ctr")),
                    ecpm=_safe_float(row.get("ecpm")),
                    revenue=_safe_float(row.get("revenue")),
                    reward_video_impression=_safe_int(row.get("reward_video_impression")),
                    reward_video_revenue=_safe_float(row.get("reward_video_revenue")),
                    interstitial_impression=_safe_int(row.get("interstitial_impression")),
                    interstitial_revenue=_safe_float(row.get("interstitial_revenue")),
                )
                db.add(metric)
                imported_count += 1

            except Exception as e:
                import_errors.append(f"行 {idx + 2}: {str(e)}")

        await db.flush()

        return {
            "success": True,
            "imported_count": imported_count,
            "errors": import_errors,
        }

    except Exception as e:
        logger.error(f"Ad metrics import failed: {e}", exc_info=True)
        return {"success": False, "imported_count": 0, "errors": [str(e)]}


def generate_import_template(import_type: str) -> bytes:
    """
    Generate an Excel template for data import.

    Args:
        import_type: One of 'video', 'mini_program', 'ad'

    Returns:
        bytes: Excel file content
    """
    templates = {
        "video": {
            "columns": VIDEO_METRICS_REQUIRED_COLUMNS + VIDEO_METRICS_OPTIONAL_COLUMNS,
            "sample": {
                "video_id": "vid_001",
                "title": "测试视频标题",
                "publish_date": "2026-08-01",
                "play_count": 10000,
                "finish_rate": 0.65,
                "like_count": 500,
                "comment_count": 100,
                "share_count": 50,
                "attributed_revenue": 125.50,
            },
        },
        "mini_program": {
            "columns": MINI_PROGRAM_REQUIRED_COLUMNS + MINI_PROGRAM_OPTIONAL_COLUMNS,
            "sample": {
                "date": "2026-08-01",
                "uv": 5000,
                "new_user_count": 200,
                "drama_play_count": 3000,
                "avg_play_duration": 120.5,
                "drama_finish_rate": 0.45,
            },
        },
        "ad": {
            "columns": AD_METRICS_REQUIRED_COLUMNS + AD_METRICS_OPTIONAL_COLUMNS,
            "sample": {
                "date": "2026-08-01",
                "impression_count": 50000,
                "click_count": 1500,
                "ctr": 0.03,
                "ecpm": 25.50,
                "revenue": 1275.00,
            },
        },
    }

    template = templates.get(import_type)
    if not template:
        raise ValueError(f"Unknown import type: {import_type}. Supported: {list(templates.keys())}")

    df = pd.DataFrame([template["sample"]], columns=template["columns"])

    import io
    output = io.BytesIO()
    df.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)
    return output.getvalue()
