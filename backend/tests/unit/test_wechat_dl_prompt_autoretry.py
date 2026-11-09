"""反推提示词 11-09 现网修复批次（ISSUE #372）单元测试。

背景（163 现网实测）：反推任务成批 failed，库里只写「任务处理失败」，白拿 doc/119
原始响应才发现真因在 `data.errMsg`（「视频理解服务返回空结果」），上游 2.7~3.2 秒就
吐空；同一条链接换个时刻再投就成功。而默认 maxDuration=600 意味着**每条失败也扣
0.324 元**，当天 7 条空手而归就是 2.268 元。所以这一批改了五件事，本文件逐条钉住：

1. FAIL 原因取 errMsg（不是 msg），界面另给一句人话处置建议；
2. 计时上限默认 180（=0.097 元/条），留空不再按 600 投；
3. 可重试的终态失败自动补投**一次**，名额用 UPDATE ... WHERE retry_count = 0 原子认领；
4. 补投前先按 doc/107 换直链（0.01 元换掉一次 0.097 元空跑），解析不通退回原链接；
5. 没有 provider_task_id 的僵尸 processing 行到期收口，不再永远「生成中」。

外部接口全部 mock，不打真实网络、不落库。
运行：cd backend && python -m pytest tests/unit/test_wechat_dl_prompt_autoretry.py -v
"""

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_prompt_autoretry.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from wechat_download import prompt_client as pc  # noqa: E402
from wechat_download import prompt_service as ps  # noqa: E402
from wechat_download.models import PT_FAILED, PT_PROCESSING, PT_SUCCESS  # noqa: E402


# ─────────────────────────────────────────────────────────────
# 替身
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
    c = pc.PromptClient()
    c.key = "test-key"
    c._client = MagicMock()
    c._client.post = AsyncMock(return_value=resp)
    c._client.get = AsyncMock(return_value=resp)
    c._client.aclose = AsyncMock()
    return c


def _task(**kw):
    """真整数 retry_count / created_at（MagicMock 会被判成「已补投过」，用例打不开）。"""
    t = MagicMock()
    t.id = kw.get("id") or uuid.uuid4()
    t.created_by = kw.get("created_by")
    t.source_url = kw.get("source_url", "https://weixin.qq.com/sph/abc")
    t.source_type = kw.get("source_type", "url")
    t.provider_task_id = kw.get("provider_task_id")
    t.status = kw.get("status", PT_PROCESSING)
    t.content = kw.get("content")
    t.error = kw.get("error")
    t.max_duration = kw.get("max_duration")
    t.retry_count = kw.get("retry_count", 0)
    t.created_at = kw.get("created_at", datetime.utcnow())
    return t


def _db(claimed=True):
    """AsyncSession 替身。`claimed` 控制原子认领那条 UPDATE 影响 0 行还是 1 行。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    res = MagicMock()
    res.rowcount = 1 if claimed else 0
    db.execute = AsyncMock(return_value=res)
    return db


def _query_client(st):
    fake = MagicMock()
    fake.query = AsyncMock(return_value=st)
    fake.close = AsyncMock()
    return fake


# ─────────────────────────────────────────────────────────────
# 1. FAIL 原因：errMsg 才是真因（外层 msg 是 "success"）
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_fail_prefers_errmsg_over_outer_success_msg():
    """现网就栽在这里：官方 FAIL 响应里 msg="success"、原因在 errMsg。"""
    body = {
        "code": 200,
        "msg": "success",
        "data": {"schedule": "FAIL", "errMsg": "视频理解服务返回空结果", "id": "t-1"},
    }
    st = await _client_with(_Resp(200, body)).query("t-1")
    assert st.status == PT_FAILED
    assert st.error == "视频理解服务返回空结果"
    assert "success" not in (st.error or "")


@pytest.mark.asyncio
async def test_query_fail_falls_back_to_msg_when_no_errmsg():
    """老/异常响应形状（只有 msg）也要拿到原因，不许退化成「任务处理失败」。"""
    st = await _client_with(_Resp(200, {"code": 200, "data": {"schedule": "FAIL", "msg": "视频无法下载"}})).query("t")
    assert st.status == PT_FAILED and st.error == "视频无法下载"

    # 两个都没有才用兜底文案
    st2 = await _client_with(_Resp(200, {"code": 200, "data": {"schedule": "FAIL"}})).query("t")
    assert st2.error == "任务处理失败"


@pytest.mark.asyncio
async def test_query_fail_ignores_success_shaped_msg_only():
    """errMsg 空串 + msg="success"：不能被 "success" 当成原因写进库。"""
    st = await _client_with(_Resp(200, {"code": 200, "data": {"schedule": "FAIL", "errMsg": "", "msg": "success"}})).query("t")
    assert st.error == "任务处理失败"


# ─────────────────────────────────────────────────────────────
# 2. 计时上限默认 180（留空不再按 600 投）
# ─────────────────────────────────────────────────────────────

def test_default_max_duration_is_180():
    assert ps.settings.WECHAT_DL_PROMPT_MAX_DURATION == 180


@pytest.mark.asyncio
async def test_submit_without_max_duration_charges_180_not_600():
    c = _client_with(_Resp(200, {"code": 200, "data": "t1"}))
    await c.submit("https://x/1")
    assert c._client.post.call_args[1]["data"]["maxDuration"] == "180"


@pytest.mark.asyncio
async def test_submit_still_clamps_to_official_max_600():
    """默认降档不等于封上限：显式选 600/300 仍然照投（长视频要能花钱买时长）。"""
    c = _client_with(_Resp(200, {"code": 200, "data": "t1"}))
    await c.submit("https://x/1", max_duration=300)
    assert c._client.post.call_args[1]["data"]["maxDuration"] == "300"

    await c.submit("https://x/1", max_duration=9999)
    assert c._client.post.call_args[1]["data"]["maxDuration"] == "600"


# ─────────────────────────────────────────────────────────────
# 3. 白话建议 + 序列化
# ─────────────────────────────────────────────────────────────

def test_explain_prompt_error_is_actionable_per_reason():
    empty = ps.explain_prompt_error("视频理解服务返回空结果")
    assert empty and "补投" in empty

    quota = ps.explain_prompt_error("查询反推状态异常（code=-1）: 余额不足")
    assert quota and "额度" in quota

    no_key = ps.explain_prompt_error("未配置 WECHAT_DL_ZHILING_KEY，无法调用反推提示词接口")
    assert no_key and "管理员" in no_key

    dead = ps.explain_prompt_error("自动补投未成功（视频无法下载）；原始失败：视频理解服务返回空结果")
    assert dead and "换一条" in dead

    # 没失败就不该有话；没见过的原因也要给一句兜底，而不是空白
    assert ps.explain_prompt_error(None) is None
    assert ps.explain_prompt_error("看不懂的 upstream 黑话") is not None


def test_explain_prompt_error_changes_once_the_retry_is_spent():
    """同一句 errMsg，补投前说「会自动补投」，补投后再这么说就是骗人。"""
    reason = "视频理解服务返回空结果"
    first = ps.explain_prompt_error(reason, retry_count=0)
    second = ps.explain_prompt_error(reason, retry_count=1)
    assert "系统会自动补投一次" in first
    assert "自动补投一次" not in second
    assert "人工点「重投」" in second

    direct_first = ps.explain_prompt_error("视频无法下载", retry_count=0)
    direct_second = ps.explain_prompt_error("视频无法下载", retry_count=1)
    assert "再试一次" in direct_first and "已试过" in direct_second


def test_serialize_prompt_task_carries_hint_and_retry_count():
    t = _task(status=PT_FAILED, error="视频理解服务返回空结果", retry_count=1)
    out = ps.serialize_prompt_task(t)
    assert out["error"] == "视频理解服务返回空结果"  # 原文留给对账/找供应商
    assert "补投" in out["error_hint"]
    assert out["retry_count"] == 1

    # 非整数（脏数据/老替身）显示 0，不在前端玩魔术
    t2 = _task(retry_count=None)
    assert ps.serialize_prompt_task(t2)["retry_count"] == 0


def test_is_retryable_failure_only_known_transient_reasons():
    assert ps._is_retryable_failure("视频理解服务返回空结果") is True
    assert ps._is_retryable_failure("上游处理超时") is True
    # 钱不够／没配 key／链接非法：补投也是白花，绝不自动重投
    assert ps._is_retryable_failure("查询反推状态异常（code=-1）: 余额不足") is False
    assert ps._is_retryable_failure("未配置 WECHAT_DL_ZHILING_KEY") is False
    # 判不准的原因一律不自动花钱
    assert ps._is_retryable_failure("某种没见过的上游黑话") is False
    assert ps._is_retryable_failure(None) is False


# ─────────────────────────────────────────────────────────────
# 4. 自动补投一次（含换直链）
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fail_auto_retries_once_via_direct_url(monkeypatch):
    """errMsg「空结果」→ 先 doc/107 解析直链，再用直链重投，任务回到 processing。"""
    submitted = {}

    async def _submit(url, max_duration=None):
        submitted["url"] = url
        submitted["max_duration"] = max_duration
        return "provider-2"

    prompt_client = MagicMock()
    prompt_client.submit = AsyncMock(side_effect=_submit)
    prompt_client.query = AsyncMock(return_value=pc.PromptStatus(
        status=PT_FAILED, error="视频理解服务返回空结果", schedule="FAIL",
    ))
    prompt_client.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: prompt_client)

    svc = MagicMock()
    svc.resolve_direct_url = AsyncMock(return_value="https://cdn.x/direct.mp4")
    svc.close = AsyncMock()
    monkeypatch.setattr(ps, "ZhilingServiceClient", lambda: svc)

    task = _task(provider_task_id="provider-1", max_duration=180)
    db = _db()
    out = await ps.refresh_prompt_task(db, task)

    assert submitted["url"] == "https://cdn.x/direct.mp4"
    assert submitted["max_duration"] == 180
    assert out.status == PT_PROCESSING
    assert out.provider_task_id == "provider-2"
    assert out.retry_count == 1
    # 补投这轮 error 里保留上次原因（成功后 SUCCESS 分支自然清空），不是「悄悄当没发生过」
    assert "视频理解服务返回空结果" in out.error
    # 关键顺序：认领名额（UPDATE）之后、跨网络 IO 之前必须先 commit
    assert db.commit.await_count >= 2


@pytest.mark.asyncio
async def test_auto_retry_skips_resolve_when_source_is_already_direct(monkeypatch):
    """输入本来就是直链／上传件时不再花 0.01 元解析（解析它也解析不出东西）。"""
    prompt_client = MagicMock()
    prompt_client.submit = AsyncMock(return_value="p2")
    prompt_client.query = AsyncMock(return_value=pc.PromptStatus(status=PT_FAILED, error="视频理解服务返回空结果"))
    prompt_client.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: prompt_client)

    svc = MagicMock()
    svc.resolve_direct_url = AsyncMock(return_value="https://should-not-be-called/direct.mp4")
    svc.close = AsyncMock()
    monkeypatch.setattr(ps, "ZhilingServiceClient", lambda: svc)

    direct = _task(provider_task_id="p1", source_url="https://cdn.x/a.mp4")
    out = await ps.refresh_prompt_task(_db(), direct)
    assert svc.resolve_direct_url.await_count == 0
    assert prompt_client.submit.await_args[0][0] == "https://cdn.x/a.mp4"
    assert out.status == PT_PROCESSING

    # 上传件同理（source_url 是智令 temp 桶 fileUrl，再解析等于白花一次）
    uploaded = _task(provider_task_id="p1", source_type="upload", source_url="https://s3.x/tmp/a.mp4?a=1")
    out2 = await ps.refresh_prompt_task(_db(), uploaded)
    assert svc.resolve_direct_url.await_count == 0
    assert out2.status == PT_PROCESSING


@pytest.mark.asyncio
async def test_auto_retry_falls_back_to_original_url_when_resolve_fails(monkeypatch):
    """解析失败只是「省不到那 0.01 元」，不该把补投一起弄失败。"""
    from wechat_download.services_client import ZhilingServiceError

    prompt_client = MagicMock()
    prompt_client.submit = AsyncMock(return_value="p2")
    prompt_client.query = AsyncMock(return_value=pc.PromptStatus(status=PT_FAILED, error="视频理解服务返回空结果"))
    prompt_client.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: prompt_client)

    svc = MagicMock()
    svc.resolve_direct_url = AsyncMock(side_effect=ZhilingServiceError("视频直链解析失败"))
    svc.close = AsyncMock()
    monkeypatch.setattr(ps, "ZhilingServiceClient", lambda: svc)

    out = await ps.refresh_prompt_task(_db(), _task(provider_task_id="p1"))
    assert prompt_client.submit.await_args[0][0] == "https://weixin.qq.com/sph/abc"
    assert out.status == PT_PROCESSING


@pytest.mark.asyncio
async def test_auto_retry_never_double_spends_when_slot_taken(monkeypatch):
    """并发轮询：UPDATE 认领 0 行（别人已补投）就一句外部请求都不许发。"""
    prompt_client = MagicMock()
    prompt_client.submit = AsyncMock(return_value="p2")
    prompt_client.query = AsyncMock(return_value=pc.PromptStatus(status=PT_FAILED, error="视频理解服务返回空结果"))
    prompt_client.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: prompt_client)

    svc = MagicMock()
    svc.resolve_direct_url = AsyncMock(return_value="https://cdn.x/d.mp4")
    svc.close = AsyncMock()
    monkeypatch.setattr(ps, "ZhilingServiceClient", lambda: svc)

    out = await ps.refresh_prompt_task(_db(claimed=False), _task(provider_task_id="p1"))
    assert out.status == PT_FAILED
    prompt_client.submit.assert_not_awaited()
    svc.resolve_direct_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_retry_not_spent_on_permanent_failure(monkeypatch):
    """额度耗尽这种补投也做不出来的原因，绝不自动再扣一次。"""
    prompt_client = MagicMock()
    prompt_client.submit = AsyncMock(return_value="p2")
    prompt_client.query = AsyncMock(return_value=pc.PromptStatus(
        status=PT_FAILED, error="查询反推状态异常（code=-1）: 余额不足",
    ))
    prompt_client.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: prompt_client)

    out = await ps.refresh_prompt_task(_db(), _task(provider_task_id="p1"))
    assert out.status == PT_FAILED
    assert "余额不足" in out.error
    prompt_client.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_retry_honours_switch_and_retry_cap(monkeypatch):
    """开关关掉＝回到「只记 failed」；已经补投过一次的（retry_count=1）不再补。"""
    def _fake():
        f = MagicMock()
        f.submit = AsyncMock(return_value="p2")
        f.query = AsyncMock(return_value=pc.PromptStatus(status=PT_FAILED, error="视频理解服务返回空结果"))
        f.close = AsyncMock()
        return f

    monkeypatch.setattr(ps, "PromptClient", _fake)
    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_AUTO_RETRY", False)
    out = await ps.refresh_prompt_task(_db(), _task(provider_task_id="p1"))
    assert out.status == PT_FAILED

    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_AUTO_RETRY", True)
    used = _task(provider_task_id="p1", retry_count=1)
    out2 = await ps.refresh_prompt_task(_db(), used)
    assert out2.status == PT_FAILED


@pytest.mark.asyncio
async def test_auto_retry_submit_error_keeps_task_failed_with_both_reasons(monkeypatch):
    """补投提交也被拒：停在 failed，error 里同时留「这次为什么没投出去」和上次的原因。"""
    prompt_client = MagicMock()
    prompt_client.submit = AsyncMock(side_effect=pc.PromptError("提交反推任务失败（code=-1）: 额度不足"))
    prompt_client.query = AsyncMock(return_value=pc.PromptStatus(status=PT_FAILED, error="视频理解服务返回空结果"))
    prompt_client.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: prompt_client)

    svc = MagicMock()
    svc.resolve_direct_url = AsyncMock(return_value="https://cdn.x/d.mp4")
    svc.close = AsyncMock()
    monkeypatch.setattr(ps, "ZhilingServiceClient", lambda: svc)

    out = await ps.refresh_prompt_task(_db(), _task(provider_task_id="p1"))
    assert out.status == PT_FAILED
    assert "自动补投未成功" in out.error and "视频理解服务返回空结果" in out.error
    assert out.retry_count == 1  # 名额已用掉，不会再自己烧第三次


# ─────────────────────────────────────────────────────────────
# 5. 僵尸 processing 行收口（没有 provider_task_id）
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zombie_processing_row_without_provider_id_converges(monkeypatch):
    """建行后进程被切 → 永远没有 provider_task_id。旧写法直接 return，界面一直「生成中」。"""
    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS", 3600)
    fake = _query_client(pc.PromptStatus(status=PT_SUCCESS, content="x"))
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    fresh = _task(provider_task_id=None)
    out = await ps.refresh_prompt_task(_db(), fresh)
    assert out.status == PT_PROCESSING  # 刚建的行为不变（提交可能还在跑，尤其上传件）
    assert fake.query.await_count == 0

    stale = _task(provider_task_id=None, created_at=datetime.utcnow() - timedelta(hours=2))
    out2 = await ps.refresh_prompt_task(_db(), stale)
    assert out2.status == PT_FAILED
    assert "没有拿到上游任务号" in out2.error
    assert fake.query.await_count == 0


@pytest.mark.asyncio
async def test_transient_giveup_text_does_not_tell_users_to_use_retry_failed(monkeypatch):
    """收口文案是给一线看的，不该出现内部参数名（也不该再让它以为没扣过钱）。"""
    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS", 3600)
    fake = _query_client(pc.PromptStatus(status=PT_PROCESSING, transient=True, error="转发请求失败"))
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    task = _task(provider_task_id="p1", created_at=datetime.utcnow() - timedelta(minutes=90))
    out = await ps.refresh_prompt_task(_db(), task)
    assert out.status == PT_FAILED
    assert "retry_failed" not in out.error
    assert "再扣一次钱" in out.error
    # 抖动收口不属于「自动补投」：任务可能还在上游跑着，这里重投是真双扣
    assert out.retry_count == 0
