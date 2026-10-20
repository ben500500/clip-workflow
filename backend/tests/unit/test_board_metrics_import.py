"""看板指标自动导入（board_data.json → video_metrics）单元测试（ISSUE #366）。

覆盖：
1. 纯函数：计数解析、完播率归一化（0.456 / 45.6 / "45.6%"）、日期解析（含坏日期不丢行）、
   has_drama=false 时剧名置空、平均时长解析；
2. 视频集摊平：weekly_videos ∪ all_top_videos，按 id 去重，缺 id 丢弃；
3. 账号映射：channel_name 精确匹配且 enabled=true，未命中整账号跳过并计数；
4. upsert 幂等：跑两遍行数不翻倍、值为最新；
5. fail-soft：文件缺失 / JSON 损坏 / 顶层非对象 → success=False，不抛异常；
6. import_history 留痕：import_mode=board_sync 且 errors 带 skipped_accounts；
7. 序列化：/api/dashboard/videos 的 publish_date 是 Date 列，不能走 datetime 的 utc_iso。

运行：cd backend && python -m pytest tests/unit/test_board_metrics_import.py -v
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# app.config 是模块级单例，导入即校验必填项 —— 必须在 import 业务模块前置好测试 env
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_board.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from sqlalchemy import select  # noqa: E402

from app.database import Base  # noqa: E402
from app.models.channel import ChannelAccount  # noqa: E402
from app.models.material import ImportHistory  # noqa: E402
from app.models.models import VideoMetric  # noqa: E402
from app.services import board_metrics_service as bms  # noqa: E402


# ─────────────────────────────────────────────────────────────
# 纯函数
# ─────────────────────────────────────────────────────────────

def test_as_int_tolerates_commas_and_strings():
    assert bms._as_int(1234) == 1234
    assert bms._as_int("1,234") == 1234
    assert bms._as_int("12.7") == 12
    assert bms._as_int(None) == 0
    assert bms._as_int("") == 0
    assert bms._as_int("--") == 0
    assert bms._as_int(True) == 0


@pytest.mark.parametrize("raw,expected", [
    (0.456, 0.456),
    (45.6, 0.456),
    ("45.6%", 0.456),
    ("0.456", 0.456),
    ("45.6", 0.456),
    (1, 1.0),
    (100, 1.0),
    (None, None),
    ("", None),
    ("n/a", None),
])
def test_normalize_rate(raw, expected):
    got = bms.normalize_rate(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_parse_board_date_formats_and_failures():
    assert bms.parse_board_date("2026-10-20 08:00") == date(2026, 10, 20)
    assert bms.parse_board_date("2026-10-20 08:00:00") == date(2026, 10, 20)
    assert bms.parse_board_date("2026-10-20") == date(2026, 10, 20)
    assert bms.parse_board_date("not-a-date") is None
    assert bms.parse_board_date("") is None
    assert bms.parse_board_date(None) is None


def test_normalize_duration():
    assert bms.normalize_duration(12.3456) == 12.346
    assert bms.normalize_duration("12.5s") == 12.5
    assert bms.normalize_duration("12.5") == 12.5
    assert bms.normalize_duration(None) is None
    assert bms.normalize_duration("abc") is None


def test_extract_drama_name_respects_has_drama():
    assert bms.extract_drama_name({"has_drama": True, "drama_name": "闪婚老公是首富"}) == "闪婚老公是首富"
    assert bms.extract_drama_name({"has_drama": False, "drama_name": "残留剧名"}) is None
    assert bms.extract_drama_name({"has_drama": True, "drama_name": "  "}) is None


def test_build_metric_payload_maps_fields():
    video = {
        "id": "v1",
        "title": "太上爆款1",
        "date": "2026-10-20 08:00",
        "plays": "123,456",
        "today_plays": 5432,
        "likes": 88,
        "comments": 7,
        "shares": 5,
        "favorites": 3,
        "full_play_rate": "42.5%",
        "avg_play_time": 14.2,
        "has_drama": True,
        "drama_name": "闪婚老公是首富",
    }
    payload = bms.build_metric_payload(video, "acct-uuid")
    assert payload["title"] == "太上爆款1"
    assert payload["play_count"] == 123456
    assert payload["today_play_count"] == 5432
    assert payload["like_count"] == 88
    assert payload["finish_rate"] == pytest.approx(0.425)
    assert payload["avg_play_time"] == pytest.approx(14.2)
    assert payload["drama_name"] == "闪婚老公是首富"
    assert payload["publish_date"] == date(2026, 10, 20)
    assert payload["source"] == "board"
    assert payload["platform"] == "wechat_channels"
    assert payload["publish_task_id"] is None
    assert payload["account_id"] == "acct-uuid"


# ─────────────────────────────────────────────────────────────
# 摊平：weekly_videos ∪ all_top_videos
# ─────────────────────────────────────────────────────────────

def _video(vid, **over):
    base = {
        "id": vid,
        "title": f"t-{vid}",
        "date": "2026-10-20 08:00",
        "plays": 100,
        "today_plays": 10,
        "likes": 1,
        "comments": 1,
        "shares": 1,
        "favorites": 1,
        "full_play_rate": 0.5,
        "avg_play_time": 10,
        "has_drama": False,
        "drama_name": None,
    }
    base.update(over)
    return base


def test_collect_account_videos_unions_and_dedupes():
    payload = {
        "accounts": [
            {"account": "太上短剧", "weekly_videos": [_video("a"), _video("b")]},
            {"account": "帷幕小剧场", "weekly_videos": [_video("c")]},
        ],
        "all_top_videos": [
            _video("b"),                                   # 与周榜重复 → 去重
            _video("d", account="太上短剧"),                # 总榜独有 → 并入
            _video("e", account="没登记的号"),              # 账号未登记 → 保留在字典里，后续跳过
            _video(None, account="太上短剧"),               # 缺 id → 丢弃
            _video("", account="太上短剧"),                 # 空 id → 丢弃
        ],
    }
    got = bms.collect_account_videos(payload)
    assert [v["id"] for v in got["太上短剧"]] == ["a", "b", "d"]
    assert [v["id"] for v in got["帷幕小剧场"]] == ["c"]
    assert [v["id"] for v in got["没登记的号"]] == ["e"]


def test_collect_account_videos_empty_payload():
    assert bms.collect_account_videos({}) == {}


# ─────────────────────────────────────────────────────────────
# 落库：账号匹配 / 幂等 / fail-soft / 留痕
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def _session(tmp_path):
    """临时 sqlite 会话（建表 → 用 → 释放）。

    用 asynccontextmanager 而不是 async fixture：pytest.ini 是 asyncio_mode=strict，
    仓内既有用例（如 test_remotion_mix.py）也不用 async fixture，保持同一写法。
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/board.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as db:
            yield db
    finally:
        await engine.dispose()


def _write_payload(tmp_path, payload) -> str:
    path = tmp_path / "board_data.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


async def _seed_accounts(db):
    db.add(ChannelAccount(channel_name="太上短剧", enabled=True))
    db.add(ChannelAccount(channel_name="帷幕小剧场", enabled=True))
    db.add(ChannelAccount(channel_name="停用剧场", enabled=False))
    await db.commit()


@pytest.mark.asyncio
async def test_import_maps_matches_and_skips(tmp_path):
  async with _session(tmp_path) as session:
    await _seed_accounts(session)
    payload = {
        "generated_at": "2026-10-20 08:00",
        "accounts": [
            {"account": "太上短剧", "weekly_videos": [_video("a"), _video("b", date="坏日期", has_drama=False,
                                                                    drama_name="残留")]},
            {"account": "停用剧场", "weekly_videos": [_video("x")]},
            {"account": "没登记的号", "weekly_videos": [_video("y")]},
        ],
        "all_top_videos": [_video("c", account="帷幕小剧场")],
    }
    path = _write_payload(tmp_path, payload)
    stats = await bms.run_board_import(session, path)
    await session.commit()

    assert stats["success"] is True
    assert stats["imported_count"] == 3
    assert stats["updated_count"] == 0
    assert stats["skipped_accounts"] == ["停用剧场", "没登记的号"]
    assert stats["matched_accounts"] == ["太上短剧", "帷幕小剧场"]

    rows = (await session.execute(select(VideoMetric))).scalars().all()
    by_id = {r.video_id: r for r in rows}
    assert set(by_id) == {"a", "b", "c"}
    assert by_id["a"].source == "board"
    assert by_id["a"].platform == "wechat_channels"
    assert by_id["a"].publish_task_id is None
    # 坏日期不丢行，publish_date 留 NULL
    assert by_id["b"].publish_date is None
    # has_drama=false → drama_name 置 NULL
    assert by_id["b"].drama_name is None
    # 未登记/停用账号的行不会入库
    assert "x" not in by_id and "y" not in by_id


@pytest.mark.asyncio
async def test_import_is_idempotent_and_takes_latest(tmp_path):
  async with _session(tmp_path) as session:
    await _seed_accounts(session)
    v1 = _video("a", plays=100, today_plays=5, full_play_rate=0.3)
    path = _write_payload(tmp_path, {"accounts": [{"account": "太上短剧", "weekly_videos": [v1]}]})

    first = await bms.run_board_import(session, path)
    await session.commit()
    assert (first["imported_count"], first["updated_count"]) == (1, 0)
    count_after_first = len((await session.execute(select(VideoMetric))).scalars().all())

    # 第二轮：同 id 更新指标
    v2 = _video("a", plays=999, today_plays=77, full_play_rate=60)
    path2 = _write_payload(tmp_path, {"accounts": [{"account": "太上短剧", "weekly_videos": [v2]}]})
    second = await bms.run_board_import(session, path2)
    await session.commit()

    assert (second["imported_count"], second["updated_count"]) == (0, 1)
    rows = (await session.execute(select(VideoMetric))).scalars().all()
    assert len(rows) == count_after_first  # 行数不翻倍
    assert rows[0].play_count == 999
    assert rows[0].today_play_count == 77
    assert rows[0].finish_rate == pytest.approx(0.6)

    # 第三轮：原样再跑一遍，仍然只有 1 行
    third = await bms.run_board_import(session, path2)
    await session.commit()
    assert (third["imported_count"], third["updated_count"]) == (0, 1)
    assert len((await session.execute(select(VideoMetric))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_import_writes_history_with_skipped_accounts(tmp_path):
  async with _session(tmp_path) as session:
    await _seed_accounts(session)
    payload = {"accounts": [
        {"account": "太上短剧", "weekly_videos": [_video("a")]},
        {"account": "没登记的号", "weekly_videos": [_video("y")]},
    ]}
    await bms.run_board_import(session, _write_payload(tmp_path, payload))
    await session.commit()

    hist = (await session.execute(select(ImportHistory))).scalars().all()
    assert len(hist) == 1
    row = hist[0]
    assert row.file_name == "data-update board_data.json"
    assert row.platform == "wechat_channels"
    assert row.import_mode == "board_sync"
    assert row.target_table == "video_metrics"
    assert row.imported_count == 1
    assert any("没登记的号" in str(e) for e in (row.errors or []))


@pytest.mark.asyncio
async def test_import_fail_soft_on_missing_file(tmp_path):
  async with _session(tmp_path) as session:
    stats = await bms.run_board_import(session, str(tmp_path / "nope.json"))
    assert stats["success"] is False
    assert stats["imported_count"] == 0
    assert stats["errors"]


@pytest.mark.asyncio
async def test_import_fail_soft_on_broken_json(tmp_path):
  async with _session(tmp_path) as session:
    bad = tmp_path / "board_data.json"
    bad.write_text("{not json", encoding="utf-8")
    stats = await bms.run_board_import(session, str(bad))
    assert stats["success"] is False
    assert stats["errors"]


@pytest.mark.asyncio
async def test_import_fail_soft_on_non_object_top_level(tmp_path):
  async with _session(tmp_path) as session:
    arr = tmp_path / "board_data.json"
    arr.write_text("[1,2,3]", encoding="utf-8")
    stats = await bms.run_board_import(session, str(arr))
    assert stats["success"] is False
    assert stats["errors"]


@pytest.mark.asyncio
async def test_import_skips_bad_row_without_aborting_round(tmp_path):
  async with _session(tmp_path) as session:
    await _seed_accounts(session)
    good = _video("ok")
    broken = {"id": "broken", "plays": {"weird": "dict"}}  # 字段类型异常 → 该条跳过
    payload = {"accounts": [{"account": "太上短剧", "weekly_videos": [good, broken]}]}
    stats = await bms.run_board_import(session, _write_payload(tmp_path, payload))
    await session.commit()

    assert stats["success"] is True
    assert stats["imported_count"] >= 1
    rows = {r.video_id for r in (await session.execute(select(VideoMetric))).scalars().all()}
    assert "ok" in rows


# ─────────────────────────────────────────────────────────────
# 序列化：Date 列不能走 datetime 的 utc_iso
# ─────────────────────────────────────────────────────────────

def test_iso_date_handles_date_column():
    from app.api.dashboard import _iso_date

    assert _iso_date(date(2026, 10, 20)) == "2026-10-20"
    assert _iso_date(None) == ""


def test_serialize_video_metric_includes_board_columns():
    from app.api.dashboard import _serialize_video_metric

    metric = VideoMetric(
        video_id="a",
        title="t",
        publish_date=date(2026, 10, 20),
        today_play_count=5,
        avg_play_time=12.5,
        drama_name="某剧",
        source="board",
        play_count=100,
    )
    payload = _serialize_video_metric(metric)
    assert payload["publish_date"] == "2026-10-20"
    assert payload["today_play_count"] == 5
    assert payload["avg_play_time"] == 12.5
    assert payload["drama_name"] == "某剧"
    assert payload["source"] == "board"
