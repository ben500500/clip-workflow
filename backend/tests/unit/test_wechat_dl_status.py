"""wechat_download 两处遗留缺陷的单元测试。

覆盖：
1. 时间戳时区偏差 8h：
   - _iso_utc() naive UTC → 带 Z 的 ISO 串（前端 dayjs 据此换算本地时间）；
   - _serialize_task() 的 created_at/updated_at 一律带 UTC 标记。
2. 任务状态落库 / 卡死回收 / 放宽重试：
   - _set_status()/_fail() 即时 commit（外部 GET /tasks 才能查到中间态）；
   - _is_stale_pending() 判定边界（非终态 + 超时；终态/新鲜任务不误判）；
   - retry_task() 允许 failed 与超时 pending 重试，拒绝 completed 与在执行中的任务；
   - beat 守护任务 recover_stale 注册与回写字段。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_status.py -v
"""

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wechat_download import service as svc
from wechat_download.service import (
    ST_COMPLETED,
    ST_DOWNLOADING,
    ST_FAILED,
    ST_PARSING,
    ST_PENDING,
    _fail,
    _is_stale_pending,
    _iso_utc,
    _serialize_task,
    _set_status,
    retry_task,
)


# ─────────────────────────────────────────────────────────────
# 1. 时间戳时区：naive UTC → 带 Z 的 ISO 串
# ─────────────────────────────────────────────────────────────

def test_iso_utc_marks_naive_utc():
    """naive（库中 utcnow 写入）必须补 Z；任务 89847c6e 实例 04:47:51 → 前端 12:47:51。"""
    assert _iso_utc(datetime(2026, 9, 11, 4, 47, 51)) == "2026-09-11T04:47:51Z"


def test_iso_utc_respects_aware_input():
    from datetime import timezone
    assert _iso_utc(datetime(2026, 9, 11, 4, 47, 51, tzinfo=timezone.utc)) == "2026-09-11T04:47:51Z"
    # 已是 +08:00 的 aware 输入统一折算为 UTC 后输出
    assert _iso_utc(datetime(2026, 9, 11, 12, 47, 51,
                             tzinfo=timezone(timedelta(hours=8)))) == "2026-09-11T04:47:51Z"


def test_iso_utc_none():
    assert _iso_utc(None) is None


def test_serialize_task_timestamps_carry_utc_marker():
    task = MagicMock()
    task.id = uuid.uuid4()
    task.created_by = None
    task.auth_id = None
    task.episode_id = None
    task.project_id = None
    task.created_at = datetime(2026, 9, 11, 4, 47, 51)
    task.updated_at = datetime(2026, 9, 11, 5, 0, 0)

    data = _serialize_task(task)

    assert data["created_at"] == "2026-09-11T04:47:51Z"
    assert data["updated_at"] == "2026-09-11T05:00:00Z"


# ─────────────────────────────────────────────────────────────
# 2. 状态即时落库（commit）
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_status_commits_immediately():
    """中间态必须 commit，否则外部 GET /tasks 查不到（worker 崩溃即永久 pending）。"""
    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()

    with patch.object(svc, "_publish_progress", AsyncMock()) as pub:
        await _set_status(db, task, ST_DOWNLOADING, 35, "正在拉流下载视频...")

    db.commit.assert_awaited_once()
    pub.assert_awaited_once()
    assert task.status == ST_DOWNLOADING
    assert task.progress == 35


@pytest.mark.asyncio
async def test_fail_commits_immediately():
    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()

    with patch.object(svc, "_publish_progress", AsyncMock()):
        await _fail(db, task, "拉流下载失败")

    db.commit.assert_awaited_once()
    assert task.status == ST_FAILED
    assert task.error_message == "拉流下载失败"


@pytest.mark.asyncio
async def test_set_status_commit_failure_does_not_break_pipeline():
    """commit 失败只回滚+降级 flush，绝不把异常抛给下载主流程。"""
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=RuntimeError("db down"))
    task = MagicMock()
    task.id = uuid.uuid4()

    with patch.object(svc, "_publish_progress", AsyncMock()) as pub:
        await _set_status(db, task, ST_PARSING, 5, "解析中")

    db.rollback.assert_awaited_once()
    db.flush.assert_awaited_once()
    pub.assert_awaited_once()


# ─────────────────────────────────────────────────────────────
# 3. 卡死判定 _is_stale_pending
# ─────────────────────────────────────────────────────────────

class _Task:
    def __init__(self, status, created_at, updated_at=None):
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at


NOW = datetime(2026, 9, 11, 12, 0, 0)


def test_stale_pending_two_weeks_is_retryable():
    """生产实例 1b2eb0ae：卡两周的 pending 必须被判为可回收。"""
    assert _is_stale_pending(_Task(ST_PENDING, NOW - timedelta(weeks=2)), NOW)


def test_stale_midway_status_is_retryable():
    """中间态（downloading）超时同样视为孤儿（worker 中途崩溃）。"""
    t = _Task(ST_DOWNLOADING, NOW - timedelta(hours=5), NOW - timedelta(hours=3))
    assert _is_stale_pending(t, NOW)


def test_fresh_pending_not_stale():
    assert not _is_stale_pending(_Task(ST_PENDING, NOW - timedelta(minutes=5)), NOW)


def test_recently_updated_not_stale_even_with_old_created_at():
    """长下载任务：created_at 很旧但 updated_at 新鲜 → 不得误杀。"""
    t = _Task(ST_DOWNLOADING, NOW - timedelta(hours=5), NOW - timedelta(minutes=1))
    assert not _is_stale_pending(t, NOW)


def test_terminal_statuses_never_stale():
    assert not _is_stale_pending(_Task(ST_COMPLETED, NOW - timedelta(days=30)), NOW)
    assert not _is_stale_pending(_Task(ST_FAILED, NOW - timedelta(days=30)), NOW)


def test_missing_timestamps_not_stale():
    assert not _is_stale_pending(_Task(ST_PENDING, None), NOW)


def test_threshold_configurable(monkeypatch):
    monkeypatch.setattr(svc.settings, "WECHAT_DL_STALE_TIMEOUT_SECONDS", 60)
    assert _is_stale_pending(_Task(ST_PENDING, NOW - timedelta(seconds=61)), NOW)
    assert not _is_stale_pending(_Task(ST_PENDING, NOW - timedelta(seconds=30)), NOW)


# ─────────────────────────────────────────────────────────────
# 4. retry_task 放宽
# ─────────────────────────────────────────────────────────────

class _RetryTask:
    def __init__(self, status, created_at):
        self.id = uuid.uuid4()
        self.status = status
        self.progress = 80.0
        self.message = "旧消息"
        self.error_message = "旧错误"
        self.celery_task_id = None
        self.created_at = created_at
        self.updated_at = created_at


async def _run_retry(task):
    db = AsyncMock()
    sent = MagicMock(id="celery-1")
    celery_app = MagicMock()
    celery_app.send_task.return_value = sent

    with patch.object(svc, "get_task", AsyncMock(return_value=task)), \
         patch.dict(sys.modules, {"app.celery.tasks": MagicMock(celery_app=celery_app)}):
        result = await retry_task(db, task.id)

    return result, db, celery_app


@pytest.mark.asyncio
async def test_retry_allows_failed_task():
    task = _RetryTask(ST_FAILED, datetime.utcnow())
    result, db, celery_app = await _run_retry(task)

    assert result["ok"] is True
    assert task.status == ST_PENDING  # 已重置
    assert task.progress == 0.0
    assert task.error_message is None
    # 先 commit 再投递（避免 worker 读不到未提交行）
    assert db.commit.await_count == 2
    celery_app.send_task.assert_called_once()


@pytest.mark.asyncio
async def test_retry_allows_stale_pending_task():
    """核心放宽点：卡死的 pending 不再是「不可重试」，无需人工改库。"""
    task = _RetryTask(ST_PENDING, datetime.utcnow() - timedelta(weeks=2))
    result, _, celery_app = await _run_retry(task)

    assert result["ok"] is True
    celery_app.send_task.assert_called_once()


@pytest.mark.asyncio
async def test_retry_rejects_fresh_in_progress_task():
    """正在跑的任务不得被重投（避免双跑同一 task_id）。"""
    task = _RetryTask(ST_DOWNLOADING, datetime.utcnow() - timedelta(minutes=2))
    result, _, celery_app = await _run_retry(task)

    assert result["ok"] is False
    celery_app.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_retry_rejects_completed_task():
    task = _RetryTask(ST_COMPLETED, datetime.utcnow() - timedelta(days=30))
    result, _, celery_app = await _run_retry(task)

    assert result["ok"] is False
    assert "已完成" in result["message"]
    celery_app.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_retry_missing_task():
    db = AsyncMock()
    with patch.object(svc, "get_task", AsyncMock(return_value=None)):
        result = await retry_task(db, uuid.uuid4())
    assert result["ok"] is False


# ─────────────────────────────────────────────────────────────
# 5. beat 守护任务注册
# ─────────────────────────────────────────────────────────────

def test_stale_recovery_task_registered_and_scheduled():
    from app.celery.tasks import celery_app
    from wechat_download.tasks import task_wechat_dl_recover_stale  # noqa: F401

    assert "wechat_dl.recover_stale" in celery_app.tasks
    entry = celery_app.conf.beat_schedule["wechat-dl-stale-recovery"]
    assert entry["task"] == "wechat_dl.recover_stale"
    assert entry["schedule"] == svc.settings.WECHAT_DL_STALE_INTERVAL_SECONDS
    assert celery_app.conf.task_routes["wechat_dl.recover_stale"]["queue"] == "wechat_dl"


# ─────────────────────────────────────────────────────────────
# 6. recover_stale_tasks 回收行为
# ─────────────────────────────────────────────────────────────

class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    """极简 AsyncSession 替身：记录 execute/commit/rollback 调用。"""

    def __init__(self, rows, commit_error=None):
        self.rows = rows
        self.executed = []
        self.commits = 0
        self.commit_error = commit_error

    async def execute(self, stmt):
        self.executed.append(stmt)
        return _FakeResult(self.rows)

    async def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_session_factory(session):
    def _factory():
        return session
    return _factory


@pytest.mark.asyncio
async def test_recover_stale_marks_failed_and_commits():
    """孤儿任务（如卡两周的 1b2eb0ae）被回写 failed，重试入口随之可用。"""
    stale = _Task(ST_PENDING, datetime.utcnow() - timedelta(weeks=2))
    stale.id = uuid.uuid4()
    session = _FakeSession([stale])

    with patch.dict(sys.modules,
                    {"app.database": MagicMock(async_session_factory=_fake_session_factory(session))}):
        recovered = await svc.recover_stale_tasks()

    assert len(recovered) == 1
    assert recovered[0]["task_id"] == str(stale.id)
    assert recovered[0]["prev_status"] == ST_PENDING
    assert stale.status == ST_FAILED
    assert "超时未完成" in stale.error_message
    assert session.commits == 1


@pytest.mark.asyncio
async def test_recover_stale_noop_when_nothing_stale():
    session = _FakeSession([])

    with patch.dict(sys.modules,
                    {"app.database": MagicMock(async_session_factory=_fake_session_factory(session))}):
        recovered = await svc.recover_stale_tasks()

    assert recovered == []
    assert session.commits == 0  # 无命中不产生写事务


@pytest.mark.asyncio
async def test_recover_stale_commit_failure_is_swallowed():
    """回收失败不得抛出（beat 任务需保持存活，等下一轮巡检）。"""
    stale = _Task(ST_DOWNLOADING, datetime.utcnow() - timedelta(hours=5))
    stale.id = uuid.uuid4()
    session = _FakeSession([stale], commit_error=RuntimeError("db down"))

    with patch.dict(sys.modules,
                    {"app.database": MagicMock(async_session_factory=_fake_session_factory(session))}):
        recovered = await svc.recover_stale_tasks()

    assert recovered == []


def test_beat_task_wrapper_returns_summary():
    from wechat_download import tasks as tasks_mod
    from wechat_download.tasks import task_wechat_dl_recover_stale

    with patch.object(tasks_mod, "recover_stale_tasks",
                      AsyncMock(return_value=[{"task_id": "t1", "prev_status": ST_PENDING}])):
        result = task_wechat_dl_recover_stale()

    assert result["ok"] is True
    assert result["affected"] == 1


def test_beat_task_wrapper_swallows_error():
    from wechat_download import tasks as tasks_mod
    from wechat_download.tasks import task_wechat_dl_recover_stale

    with patch.object(tasks_mod, "recover_stale_tasks", AsyncMock(side_effect=RuntimeError("boom"))):
        result = task_wechat_dl_recover_stale()

    assert result["ok"] is False
    assert "boom" in result["error"]
