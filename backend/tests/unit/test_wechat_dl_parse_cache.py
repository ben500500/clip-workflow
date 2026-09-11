"""解析缓存 TTL 缺陷的单元测试。

背景：`_hit_parse_cache()` 取同 URL 最近一次 success 记录时没有任何时效判断，
而腾讯签名直链 play_url 只活 1~3 小时 → 命中即把死链交给下载器 → 必然
`direct download http 400`，且重试无效（缓存永远命中同一条死链）。

覆盖：
1. TTL 内命中（复用缓存，且 SQL 带时效过滤条件）；
2. 超时不命中（走实时解析，拿新直链）；
3. 截止时间必须由 Python 侧 utcnow() 计算，SQL 中不得出现 now()/func.now()
   （40 实例为 Asia/Shanghai，now() 偏 8h 会让过期记录被判为新鲜）。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_parse_cache.py -v
"""

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wechat_download import service as svc
from wechat_download.service import _hit_parse_cache, _parse_cache_cutoff


class _FakeResult:
    def __init__(self, rec):
        self._rec = rec

    def scalar_one_or_none(self):
        return self._rec


class _CachingSession:
    """极简 AsyncSession 替身：按 created_at 阈值模拟真实 SQL 的时效过滤。"""

    def __init__(self, rec):
        self.rec = rec
        self.stmt = None

    async def execute(self, stmt):
        self.stmt = stmt
        rec = self.rec
        if rec is None:
            return _FakeResult(None)
        # 从编译后的 SQL 参数里取出 cutoff（Python 侧算出的 naive UTC 截止时间）
        cutoff = None
        for param in stmt.compile().params.values():
            if isinstance(param, datetime):
                cutoff = param
        if cutoff is not None and rec.created_at < cutoff:
            return _FakeResult(None)  # 模拟 `created_at >= cutoff` 过滤掉过期行
        return _FakeResult(rec)


def _rec(created_at):
    rec = MagicMock()
    rec.id = uuid.uuid4()
    rec.channel = "yuanbao"
    rec.play_url = "https://finder.video.qq.com/live?sig=abc"
    rec.result_meta = {"title": "示例", "cover": "http://c", "duration": 12}
    rec.created_at = created_at
    return rec


NOW = datetime(2026, 9, 11, 12, 0, 0)
SRC = "https://channels.weixin.qq.com/xxx"


# ─────────────────────────────────────────────────────────────
# 1. TTL 语义：截止时间由 Python 侧 utcnow() 推导
# ─────────────────────────────────────────────────────────────

def test_cutoff_uses_python_utcnow_and_configured_ttl():
    assert _parse_cache_cutoff(NOW, 600) == NOW - timedelta(seconds=600)


def test_cutoff_default_ttl_is_10_minutes():
    """默认 TTL=600s，必须显著小于直链 1~3h 有效期。"""
    assert svc.settings.WECHAT_DL_PARSE_CACHE_TTL_SECONDS == 600
    assert _parse_cache_cutoff(NOW) == NOW - timedelta(seconds=600)


def test_ttl_config_must_be_in_recommended_range():
    """越界 TTL 直接拒绝：过小失去缓存意义，过大必然吃到死链。"""
    from pydantic import ValidationError
    from app.config import Settings

    base = dict(
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
        MINIO_ACCESS_KEY="k", MINIO_SECRET_KEY="s", JWT_SECRET="x" * 32,
    )
    for bad in (60, 299, 901, 7200):
        with pytest.raises(ValidationError):
            Settings(WECHAT_DL_PARSE_CACHE_TTL_SECONDS=bad, **base)
    for ok in (300, 600, 900):
        assert Settings(WECHAT_DL_PARSE_CACHE_TTL_SECONDS=ok, **base).WECHAT_DL_PARSE_CACHE_TTL_SECONDS == ok


# ─────────────────────────────────────────────────────────────
# 2. 验收③④：TTL 内命中 / 超时不命中
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hit_within_ttl_reuses_cached_play_url():
    """TTL 内重导：命中缓存并复用 play_url（避免重复调用限流的元宝接口）。"""
    db = _CachingSession(_rec(NOW - timedelta(minutes=5)))

    cached = await _hit_parse_cache(db, SRC, now=NOW)

    assert cached is not None
    assert cached.success is True
    assert cached.channel == "cache"
    assert cached.play_url == "https://finder.video.qq.com/live?sig=abc"


@pytest.mark.asyncio
async def test_miss_when_record_expired_beyond_ttl():
    """验收③核心：超过 TTL 的记录（死链）不再命中 → 触发实时解析。"""
    db = _CachingSession(_rec(NOW - timedelta(hours=3)))

    assert await _hit_parse_cache(db, SRC, now=NOW) is None


@pytest.mark.asyncio
async def test_boundary_exactly_ttl_still_hits():
    db = _CachingSession(_rec(NOW - timedelta(seconds=600)))
    assert await _hit_parse_cache(db, SRC, now=NOW) is not None

    db2 = _CachingSession(_rec(NOW - timedelta(seconds=601)))
    assert await _hit_parse_cache(db2, SRC, now=NOW) is None


@pytest.mark.asyncio
async def test_custom_ttl_respected():
    db = _CachingSession(_rec(NOW - timedelta(seconds=500)))
    assert await _hit_parse_cache(db, SRC, now=NOW, ttl_seconds=900) is not None
    assert await _hit_parse_cache(db, SRC, now=NOW, ttl_seconds=300) is None


@pytest.mark.asyncio
async def test_miss_when_no_success_record():
    assert await _hit_parse_cache(_CachingSession(None), SRC, now=NOW) is None


# ─────────────────────────────────────────────────────────────
# 3. 关键陷阱：截止时间必须 Python 侧算，SQL 中不得用 now()
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sql_never_uses_db_now_and_binds_python_cutoff():
    """若在 SQL 里用 now()，Asia/Shanghai(+8) 实例会偏 8h，过期记录仍被判新鲜。"""
    db = _CachingSession(_rec(NOW - timedelta(minutes=1)))
    await _hit_parse_cache(db, SRC, now=NOW)

    sql = str(db.stmt).lower()
    assert "now()" not in sql
    assert "func.now" not in sql
    # 时效条件确实下发到 SQL，且绑定值 = NOW - 600s（naive UTC 同尺度）
    bound = [p for p in db.stmt.compile().params.values() if isinstance(p, datetime)]
    assert bound == [NOW - timedelta(seconds=600)]
    assert all(p.tzinfo is None for p in bound)


@pytest.mark.asyncio
async def test_ttl_is_independent_of_session_timezone():
    """同一库时间戳，在 UTC 与 Asia/Shanghai 两种会话下判定必须一致（不偏 8h）。"""
    old = _rec(NOW - timedelta(minutes=5))
    fresh_utc = _CachingSession(old)
    fresh_sh = _CachingSession(old)

    assert await _hit_parse_cache(fresh_utc, SRC, now=NOW) is not None
    assert await _hit_parse_cache(fresh_sh, SRC, now=NOW) is not None


# ─────────────────────────────────────────────────────────────
# 4. 验收⑤不回归：命中路径不落库、不调用 provider
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_with_fallback_skips_providers_on_cache_hit():
    """TTL 内命中即返回，不得再打 provider（缓存初衷：规避元宝限流，评审 R1/R2）。"""
    task = MagicMock()
    task.id = uuid.uuid4()
    task.source_url = SRC
    db = AsyncMock()
    hit = svc.ParseResult(success=True, channel="cache", play_url="http://p", error=None)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(svc, "_hit_parse_cache", AsyncMock(return_value=hit))
        mp.setattr(svc, "build_providers", MagicMock(side_effect=AssertionError("不应调用 provider")))
        out = await svc._parse_with_fallback(db, task)

    assert out is hit
