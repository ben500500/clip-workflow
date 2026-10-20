"""看板指标自动导入：163 `data-update` 采集系统 board_data.json → video_metrics（ISSUE #366）。

数据源事实：163 宿主机 `/home/cc12703/data-update/data/dashboard/board_data.json`
每 2 小时刷新一轮，45 个短剧推广账号。字段与 video_metrics 高度吻合。

口径（已拍板）：
- 账号映射：board 的 `account` ↔ `channel_accounts.channel_name` 精确匹配且 enabled=true；
  未命中的账号整账号跳过并计数，不做任何猜测性匹配。
- 视频集：该账号 `weekly_videos` ∪ 顶层 `all_top_videos` 中该账号的条目，按 `id` 去重。
- upsert 幂等：按 `video_id` 判定存在则更新、不存在则插入。
- fail-soft：文件缺失 / JSON 损坏 / 顶层非对象 → warning 后正常返回，不重试不告警。
"""

import json
import logging
import os
from datetime import date, datetime
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.channel import ChannelAccount
from app.models.material import ImportHistory
from app.models.models import VideoMetric

logger = logging.getLogger(__name__)

SOURCE_TAG = "board"
PLATFORM = "wechat_channels"
IMPORT_MODE = "board_sync"
TARGET_TABLE = "video_metrics"
HISTORY_FILE_NAME = "data-update board_data.json"
FLUSH_EVERY = 200


# ─────────────────────────────────────────────────────────────
# 纯函数：解析与归一化
# ─────────────────────────────────────────────────────────────

def _as_int(value: Any) -> int:
    """把源数据的计数类字段收敛成 int（缺省/非法 → 0）。"""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def normalize_rate(value: Any) -> Optional[float]:
    """完播率归一化到 0~1。

    源数据同一字段既可能是 0.456，也可能是 45.6，还可能是 "45.6%"。
    统一口径：>1 一律除以 100。空值返回 None（不写 0，避免污染统计）。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace("%", "").replace(",", "")
        if not text:
            return None
        try:
            num = float(text)
        except (TypeError, ValueError):
            return None
    else:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
    if num != num:  # NaN
        return None
    if num > 1:
        num = num / 100.0
    return round(num, 6)


def parse_board_date(value: Any) -> Optional[date]:
    """解析源数据 `date`（"YYYY-MM-DD HH:MM"）为日期；失败返回 None（不丢行）。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # 兜底：只取前 10 位 YYYY-MM-DD
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def extract_drama_name(video: dict) -> Optional[str]:
    """has_drama=false 时剧名置空（源数据可能仍残留 drama_name）。"""
    if not video.get("has_drama"):
        return None
    name = video.get("drama_name")
    if name is None:
        return None
    name = str(name).strip()
    return name or None


def build_metric_payload(video: dict, account_id) -> dict:
    """board 视频条目 → video_metrics 列值（不含 video_id 幂等键）。"""
    return {
        "title": (str(video.get("title")).strip()[:500] if video.get("title") else None),
        "account_id": account_id,
        "publish_task_id": None,
        "platform": PLATFORM,
        "publish_date": parse_board_date(video.get("date")),
        "play_count": _as_int(video.get("plays")),
        "today_play_count": _as_int(video.get("today_plays")),
        "like_count": _as_int(video.get("likes")),
        "comment_count": _as_int(video.get("comments")),
        "share_count": _as_int(video.get("shares")),
        "favorite_count": _as_int(video.get("favorites")),
        "finish_rate": normalize_rate(video.get("full_play_rate")),
        "avg_play_time": normalize_duration(video.get("avg_play_time")),
        "drama_name": extract_drama_name(video),
        "source": SOURCE_TAG,
    }


def normalize_duration(value: Any) -> Optional[float]:
    """平均播放时长（秒）。"12.5s" / "12.5" / 12.5 都吃；空值 → None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().lower().rstrip("s").strip()
        if not text:
            return None
        try:
            return round(float(text), 3)
        except (TypeError, ValueError):
            return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:
        return None
    return round(num, 3)


def collect_account_videos(payload: dict) -> dict:
    """把 board_data.json 摊平成 {账号名: [视频条目...]}（周榜 ∪ 总榜，按 id 去重）。

    同一 video_id 在两处都出现时保留先出现的条目（weekly_videos 在前，
    其指标口径与总榜同构，先到先得即可）；无 `id` 的条目不参与幂等，直接丢弃。

    ⚠️ 真实 board_data.json 里 `accounts` 是 **{账号名: 账号体} 的字典**
    （账号体含 theater/metrics/weekly_videos 等），账号名在 key 上；
    列表形态仅保留作兼容（老合成样例）。
    """
    result: dict[str, list] = {}
    seen: dict[str, set] = {}

    def _push(account: Any, video: Any) -> None:
        if not account or not isinstance(video, dict):
            return
        name = str(account).strip()
        if not name:
            return
        raw_id = video.get("id")
        if raw_id is None:
            return
        video_id = str(raw_id).strip()
        if not video_id:
            return
        bucket_seen = seen.setdefault(name, set())
        if video_id in bucket_seen:
            return
        bucket_seen.add(video_id)
        result.setdefault(name, []).append(video)

    accounts_field = payload.get("accounts")
    if isinstance(accounts_field, dict):
        for name, body in accounts_field.items():
            if not isinstance(body, dict):
                continue
            for video in body.get("weekly_videos") or []:
                _push(name, video)
    elif isinstance(accounts_field, list):
        for account in accounts_field:
            if not isinstance(account, dict):
                continue
            name = account.get("account") or account.get("channel_name")
            for video in account.get("weekly_videos") or []:
                _push(name, video)

    for video in payload.get("all_top_videos") or []:
        if isinstance(video, dict):
            _push(video.get("account"), video)

    return result


# ─────────────────────────────────────────────────────────────
# 读取与导入
# ─────────────────────────────────────────────────────────────

def resolve_data_path(path: Optional[str] = None) -> str:
    return path or settings.BOARD_DATA_JSON_PATH


def load_board_payload(path: Optional[str] = None) -> Optional[dict]:
    """读 board_data.json。任何异常都只 warning 并返回 None（fail-soft，等下一轮）。"""
    target = resolve_data_path(path)
    if not os.path.isfile(target):
        logger.warning("board metrics import skipped: 文件不存在 %s", target)
        return None
    try:
        with open(target, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("board metrics import skipped: 读取/解析失败 %s (%s)", target, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("board metrics import skipped: 顶层不是对象 (%s)", type(payload).__name__)
        return None
    return payload


async def _match_accounts(db: AsyncSession, names: Iterable[str]) -> dict:
    """账号名 → ChannelAccount 对象（channel_name 精确匹配 + enabled=true，取第一个）。"""
    wanted = {str(n).strip() for n in names if n and str(n).strip()}
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(ChannelAccount)
            .where(ChannelAccount.channel_name.in_(wanted))
            .where(ChannelAccount.enabled.is_(True))
            .order_by(ChannelAccount.created_at)
        )
    ).scalars().all()
    matched: dict[str, ChannelAccount] = {}
    for row in rows:
        matched.setdefault(row.channel_name, row)
    return matched


async def _existing_metric_ids(db: AsyncSession, video_ids: list) -> dict:
    """video_id → 已存在的 VideoMetric（幂等 upsert 用）。"""
    found: dict[str, VideoMetric] = {}
    chunk = 500
    for start in range(0, len(video_ids), chunk):
        part = video_ids[start:start + chunk]
        rows = (
            await db.execute(select(VideoMetric).where(VideoMetric.video_id.in_(part)))
        ).scalars().all()
        for row in rows:
            if row.video_id is not None:
                found.setdefault(row.video_id, row)
    return found


async def run_board_import(db: AsyncSession, path: Optional[str] = None) -> dict:
    """执行一轮导入。返回统计（调用方负责 commit/rollback）。

    返回：success / imported_count / updated_count / skipped_accounts /
    matched_accounts / error_count / errors / generated_at / data_path
    """
    data_path = resolve_data_path(path)
    stats: dict = {
        "success": False,
        "imported_count": 0,
        "updated_count": 0,
        "skipped_accounts": [],
        "matched_accounts": [],
        "error_count": 0,
        "errors": [],
        "video_total": 0,
        "data_path": data_path,
        "generated_at": None,
    }

    payload = load_board_payload(path)
    if payload is None:
        stats["errors"].append("board_data.json 不可用（缺失或解析失败），等待下一轮")
        return stats

    stats["generated_at"] = payload.get("generated_at")
    by_account = collect_account_videos(payload)
    if not by_account:
        stats["success"] = True
        logger.warning("board metrics import: payload 里没有任何可导入的视频条目")
        await _write_history(db, stats)
        return stats

    matched = await _match_accounts(db, by_account.keys())
    skipped = sorted(n for n in by_account if n not in matched)
    stats["skipped_accounts"] = skipped
    stats["matched_accounts"] = sorted(matched.keys())

    pending: list[tuple[str, dict, Any]] = []
    for name in sorted(by_account):
        account = matched.get(name)
        if account is None:
            continue
        for video in by_account[name]:
            pending.append((str(video["id"]).strip(), video, account.id))

    stats["video_total"] = len(pending)
    if not pending:
        stats["success"] = True
        await _write_history(db, stats)
        return stats

    existing = await _existing_metric_ids(db, [vid for vid, _, _ in pending])
    now = datetime.utcnow()

    for index, (video_id, video, account_id) in enumerate(pending, start=1):
        try:
            values = build_metric_payload(video, account_id)
            row = existing.get(video_id)
            if row is None:
                row = VideoMetric(video_id=video_id, recorded_at=now)
                db.add(row)
                existing[video_id] = row
                stats["imported_count"] += 1
            else:
                stats["updated_count"] += 1
            for key, value in values.items():
                setattr(row, key, value)
            row.recorded_at = now
            row.updated_at = now
        except Exception as exc:  # 单条异常只跳过该条，不中断整轮
            stats["error_count"] += 1
            if len(stats["errors"]) < 20:
                stats["errors"].append(f"video_id={video_id}: {exc}")
            logger.warning("board metrics import: 跳过异常条目 %s (%s)", video_id, exc)
            continue

        if index % FLUSH_EVERY == 0:
            await db.flush()

    await db.flush()
    stats["success"] = True
    await _write_history(db, stats)
    logger.info(
        "board metrics import done: imported=%s updated=%s skipped_accounts=%s errors=%s",
        stats["imported_count"], stats["updated_count"], len(skipped), stats["error_count"],
    )
    return stats


async def _write_history(db: AsyncSession, stats: dict) -> None:
    """每轮往 import_history 留痕（含 skipped_accounts 清单）。"""
    errors = list(stats.get("errors") or [])
    if stats.get("skipped_accounts"):
        errors = errors + [f"skipped_accounts={stats['skipped_accounts']}"]
    try:
        db.add(
            ImportHistory(
                file_name=HISTORY_FILE_NAME,
                platform=PLATFORM,
                import_mode=IMPORT_MODE,
                target_table=TARGET_TABLE,
                imported_count=stats.get("imported_count", 0),
                updated_count=stats.get("updated_count", 0),
                error_count=stats.get("error_count", 0) + len(stats.get("skipped_accounts") or []),
                errors=errors or None,
            )
        )
        await db.flush()
    except Exception as exc:  # 留痕失败不影响导入本身
        logger.warning("board metrics import: 写 import_history 失败 %s", exc)
