"""视频反推提示词（智令 doc/120 提交 + doc/119 轮询）单元测试（ISSUE #361 任务 A）。

外部接口一律 mock，不打真实网络、不落库。覆盖：
1. 提交成功 → 拿 taskId 置 processing；提交业务异常（code=-1 额度耗尽）→ failed+error；
2. 轮询 schedule 归一化：WAIT_HANDLE/PROCESSING 保持 processing，
   SUCCESS 写 content，FAIL 写 error；未知 schedule 不误判终态；
3. 终态任务不再发起外部查询（不重复计费）；
4. fail-soft：网络异常不抛 500，转 failed+error；
5. 可见口径与下载任务一致（operator 仅见自己的 + 无主公共任务）。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_prompt.py -v
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wechat_download import prompt_client as pc
from wechat_download import prompt_service as ps
from wechat_download.models import PT_FAILED, PT_PROCESSING, PT_SUCCESS


# ─────────────────────────────────────────────────────────────
# 测试替身
# ─────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text or (str(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _client_with(resp):
    """构造 PromptClient 并替换其 httpx client（key 预置，避免 skip 分支）。"""
    c = pc.PromptClient()
    c.key = "test-key"
    c._client = MagicMock()
    c._client.post = AsyncMock(return_value=resp)
    c._client.get = AsyncMock(return_value=resp)
    c._client.aclose = AsyncMock()
    return c


# ─────────────────────────────────────────────────────────────
# 1. 提交（doc/120）
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_returns_task_id_from_data():
    c = _client_with(_Resp(200, {"code": 200, "data": "task-abc", "msg": "ok"}))
    assert await c.submit("https://v.douyin.com/xxx") == "task-abc"

    _, kwargs = c._client.post.call_args
    # form-urlencoded：key / videoUrl / maxDuration 三件套，且 maxDuration 转成字符串
    assert kwargs["data"]["key"] == "test-key"
    assert kwargs["data"]["videoUrl"] == "https://v.douyin.com/xxx"
    assert kwargs["data"]["maxDuration"] == str(c.default_max_duration)


@pytest.mark.asyncio
async def test_submit_clamps_max_duration_to_official_limit():
    c = _client_with(_Resp(200, {"code": 200, "data": "t1"}))
    await c.submit("https://x/1", max_duration=9999)
    assert c._client.post.call_args[1]["data"]["maxDuration"] == "600"

    await c.submit("https://x/1", max_duration=0)
    assert c._client.post.call_args[1]["data"]["maxDuration"] == "1"


@pytest.mark.asyncio
async def test_submit_business_error_raises_prompt_error_with_msg():
    """code=-1 为业务异常（含额度耗尽），原因必须来自 msg。"""
    c = _client_with(_Resp(200, {"code": -1, "data": None, "msg": "额度不足，请充值"}))
    with pytest.raises(pc.PromptError) as ei:
        await c.submit("https://x/1")
    assert "额度不足" in str(ei.value)


@pytest.mark.asyncio
async def test_submit_http_error_and_non_json_raise_prompt_error():
    import httpx

    c = _client_with(_Resp(502, None, text="bad gateway"))
    with pytest.raises(pc.PromptError):
        await c.submit("https://x/1")

    c2 = _client_with(_Resp(200, None, text="<html>WAF</html>"))
    with pytest.raises(pc.PromptError) as ei:
        await c2.submit("https://x/1")
    assert "非 JSON" in str(ei.value)

    c3 = _client_with(_Resp(200, {"code": 200}))
    c3._client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(pc.PromptError):
        await c3.submit("https://x/1")


@pytest.mark.asyncio
async def test_submit_without_key_fails_fast():
    c = pc.PromptClient()
    c.key = ""
    with pytest.raises(pc.PromptError) as ei:
        await c.submit("https://x/1")
    assert "WECHAT_DL_ZHILING_KEY" in str(ei.value)


# ─────────────────────────────────────────────────────────────
# 2. 轮询（doc/119）schedule 归一化
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("schedule", ["WAIT_HANDLE", "PROCESSING", "wait_handle"])
async def test_query_processing_schedules_are_not_terminal(schedule):
    c = _client_with(_Resp(200, {"code": 200, "data": {"schedule": schedule}}))
    st = await c.query("task-abc")
    assert st.status == PT_PROCESSING
    assert st.content is None


@pytest.mark.asyncio
async def test_query_success_returns_markdown_content():
    md = "# 提示词\n一个女孩在雨中奔跑"
    c = _client_with(_Resp(200, {"code": 200, "data": {"schedule": "SUCCESS", "content": md}}))
    st = await c.query("task-abc")
    assert st.status == PT_SUCCESS
    assert st.content == md


@pytest.mark.asyncio
async def test_query_fail_and_empty_content_are_failed():
    c = _client_with(_Resp(200, {"code": 200, "data": {"schedule": "FAIL", "msg": "视频无法下载"}}))
    st = await c.query("task-abc")
    assert st.status == PT_FAILED
    assert "视频无法下载" in st.error

    c2 = _client_with(_Resp(200, {"code": 200, "data": {"schedule": "SUCCESS", "content": ""}}))
    st2 = await c2.query("task-abc")
    assert st2.status == PT_FAILED
    assert st2.error


@pytest.mark.asyncio
async def test_query_business_error_code_minus_one_is_failed():
    c = _client_with(_Resp(200, {"code": -1, "msg": "余额不足"}))
    st = await c.query("task-abc")
    assert st.status == PT_FAILED
    assert "余额不足" in st.error


@pytest.mark.asyncio
async def test_query_never_raises_on_network_error():
    """fail-soft：轮询网络异常返回 failed 而不是抛异常给 API 层。"""
    import httpx

    c = _client_with(_Resp(200, {"code": 200, "data": {}}))
    c._client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    st = await c.query("task-abc")
    assert st.status == PT_FAILED
    assert "查询反推状态失败" in st.error


@pytest.mark.asyncio
async def test_query_unknown_schedule_not_treated_as_terminal():
    c = _client_with(_Resp(200, {"code": 200, "data": {"schedule": "WHATEVER"}}))
    assert (await c.query("task-abc")).status == PT_PROCESSING


# ─────────────────────────────────────────────────────────────
# 3. 服务层：建行 + 提交 + 轮询落库（AsyncSession 替身）
# ─────────────────────────────────────────────────────────────

def _task(**kw):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.created_by = kw.get("created_by")
    t.source_url = kw.get("source_url", "https://x/1")
    t.provider_task_id = kw.get("provider_task_id")
    t.status = kw.get("status", PT_PROCESSING)
    t.content = kw.get("content")
    t.error = kw.get("error")
    t.max_duration = kw.get("max_duration")
    return t


def _db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_create_task_records_failure_without_raising(monkeypatch):
    """提交失败 → 任务落库 failed + error，不抛错（API 才能返回 201 任务体）。"""
    task = _task()
    db = _db()

    def _add(obj):
        obj.id = task.id

    db.add.side_effect = _add

    fake = MagicMock()
    fake.submit = AsyncMock(side_effect=pc.PromptError("额度耗尽"))
    fake.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    out = await ps.create_prompt_task(db, created_by=uuid.uuid4(), source_url="https://x/1")

    assert out.status == PT_FAILED
    assert "额度耗尽" in out.error
    # 先提交事务（外部请求前），保证失败记录可见
    assert db.commit.await_count >= 1


@pytest.mark.asyncio
async def test_create_task_stores_provider_task_id_on_success(monkeypatch):
    task = _task()
    db = _db()
    db.add.side_effect = lambda obj: setattr(obj, "id", task.id)

    fake = MagicMock()
    fake.submit = AsyncMock(return_value="task-xyz")
    fake.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    out = await ps.create_prompt_task(db, created_by=None, source_url="https://x/1", max_duration=300)

    assert out.provider_task_id == "task-xyz"
    assert out.status == PT_PROCESSING


@pytest.mark.asyncio
async def test_refresh_success_writes_content_and_terminal_skips_query(monkeypatch):
    fake = MagicMock()
    fake.query = AsyncMock(return_value=pc.PromptStatus(status=PT_SUCCESS, content="# md"))
    fake.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    task = _task(provider_task_id="t-1", status=PT_PROCESSING)
    db = _db()
    out = await ps.refresh_prompt_task(db, task)
    assert out.status == PT_SUCCESS
    assert out.content == "# md"
    assert out.error is None

    # 终态任务不再发起外部查询（不重复扣费）
    done = _task(provider_task_id="t-1", status=PT_SUCCESS, content="x")
    await ps.refresh_prompt_task(db, done)
    assert fake.query.await_count == 1

    # 无 provider_task_id（提交就失败）也不查询
    noid = _task(provider_task_id=None, status=PT_PROCESSING)
    await ps.refresh_prompt_task(db, noid)
    assert fake.query.await_count == 1


@pytest.mark.asyncio
async def test_refresh_processing_keeps_task_open(monkeypatch):
    fake = MagicMock()
    fake.query = AsyncMock(return_value=pc.PromptStatus(status=PT_PROCESSING, schedule="PROCESSING"))
    fake.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    task = _task(provider_task_id="t-1", status=PT_PROCESSING)
    out = await ps.refresh_prompt_task(_db(), task)
    assert out.status == PT_PROCESSING
    assert out.content is None
    assert out.error is None


# ─────────────────────────────────────────────────────────────
# 4. 可见口径（与下载任务一致：operator 只见自己 + 无主公共）
# ─────────────────────────────────────────────────────────────

def _user(role, data_scope, uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.role = role
    u.data_scope = data_scope
    return u


def test_visible_scope_matches_download_tasks():
    op = _user("operator", "own")
    admin = _user("admin", "all")

    assert ps.can_access_prompt_task(_task(created_by=op.id), op) is True
    assert ps.can_access_prompt_task(_task(created_by=uuid.uuid4()), op) is False
    # 无主（历史/系统任务）= 公共，与 ISSUE #361 任务 C 口径一致
    assert ps.can_access_prompt_task(_task(created_by=None), op) is True
    assert ps.can_access_prompt_task(_task(created_by=uuid.uuid4()), admin) is True
    assert ps.can_access_prompt_task(_task(created_by=op.id), None) is False


@pytest.mark.asyncio
async def test_list_stmt_filters_non_all_scope_users():
    op = _user("operator", "own")
    stmt = await ps.prompt_task_scope_stmt(op, 50)
    sql = str(stmt).upper()
    assert "CREATED_BY IS NULL" in sql or "created_by IS NULL" in str(stmt)
    assert "wechat_dl_prompt_tasks" in str(stmt)

    # scope=all 不追加 WHERE（SELECT 列表里本来就有 created_by 列，只看过滤条件）
    admin = _user("admin", "all")
    stmt_all = await ps.prompt_task_scope_stmt(admin, 50)
    assert "where" not in str(stmt_all).lower()

    op_sql = str(stmt)
    assert "where" in op_sql.lower()
