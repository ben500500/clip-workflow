"""11-10 反推／解析链路三条修法（ISSUE #372）单元测试。

背景（163 现网实测，见 `docs/项目进度总览-20261109.md` 8-11/8-12）：短剧导流页那类
视频号分享链接，智令 doc/107「解析成功」回来的不是视频流，而是它自己域名的**站点根**
（实测 `https://vnd2.17zhilian.cn/`）。旧判据只写「以 http 开头」，于是首页地址一路被
当直链收下：下载原片把 10871 字节的 HTML 存成「下载成功」（`AS-BB8563FD`）、反推必然
「未检测到视频」、补投再解析一次再拿回同一个根路径。轮询 FAIL 时 errMsg 又是空的，
库里只剩「任务处理失败」一句废话；另外 upload 型僵尸 processing 行没有全表触发口，
现网攒了 6 条永远「生成中」只能人工进库判。

本文件钉住三条修法：

1. 直链**形状闸门**：站点根／网页文件／封面图拒收，**没扩展名的播放入口必须放行**
   （`finder.video.qq.com/live?sig=…` 那类在用的链路不能被误杀）；闸门带开关，可退回旧行为。
   doc/107 收单（`resolve_direct_url`）与下载原片那条路（`provider_registry._normalize`）
   两处都要装。
2. 轮询 FAIL 且上游没人话时，把原始响应（脱敏、截断）补进 error，让这条失败事后可查，
   也让 RETRYABLE／NON_RETRYABLE 标记有机会命中。
3. `sweep_zombie_prompt_tasks` 全表收口：判据与单条刷新一致，**只管没有 provider_task_id
   的行**（有 pid 的会连带走补投、等于无人值守花钱，故意不开这个口子），0 元、不发外部请求。

外部接口全部 mock，不打真实网络。第 3 组用 SQLite 临时库跑真 UPDATE——要害就是 WHERE
三条条件到底筛掉了谁，光断言 SQL 文本看不出来。
运行：cd backend && python -m pytest tests/unit/test_wechat_dl_direct_url_gate.py -v
"""

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 2026-11-11 评审（测试席 P1）：这里原来是 5 行裸 `os.environ.setdefault`，会把值**永久**
# 留在整个 pytest 进程的 os.environ 里——后面任何模块重建 Settings 时读到的都是本文件的
# sqlite 临时库和假密钥（谁先被收集谁定规矩，改一下收集顺序结果就变，而且没人看得见）。
# app.config 是模块级单例（config.py:552 `settings = Settings()`），下面这几个 import 已经把
# Settings 构造完了，所以导入完就把环境**还原**，污染面从"整个会话"收成"本模块导入期"；
# 每条用例再由 `_unit_env` 夹具临时补回，防的是以后有人改成惰性重建 Settings。
_UNIT_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:////tmp/_unit_url_shape_gate.db",
    "JWT_SECRET": "u" * 64,
    "MINIO_ACCESS_KEY": "test",
    "MINIO_SECRET_KEY": "testtest",
    "WECHAT_DL_ZHILING_KEY": "fake-key-for-unit-only",
}
_saved_env = {k: os.environ.get(k) for k in _UNIT_ENV}
for _k, _v in _UNIT_ENV.items():
    os.environ.setdefault(_k, _v)

from wechat_download import prompt_service as ps  # noqa: E402
from wechat_download import provider_registry as pr  # noqa: E402
from wechat_download import services_client as sc  # noqa: E402
from wechat_download.prompt_client import FAIL_DEFAULT_REASON, PromptStatus  # noqa: E402
from wechat_download.services_client import ZhilingServiceError  # noqa: E402
from wechat_download.url_gate import (  # noqa: E402
    direct_url_reject_reason,
    url_shape_text,
)

for _k, _prev in _saved_env.items():
    if _prev is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _prev


@pytest.fixture(autouse=True)
def _unit_env(monkeypatch):
    """按用例临时补回必填配置（monkeypatch 会自动还原，不在进程里留痕）。"""
    for _k, _v in _UNIT_ENV.items():
        monkeypatch.setenv(_k, os.environ.get(_k) or _v)

# 事故里智令真实回的形状（站点根，没有任何视频路径）
SITE_ROOT = "https://vnd2.17zhilian.cn/"
# 现网**在用**的无扩展名播放入口（models.py 对 play_url 的注释、test_wechat_dl_parse_cache 同款）
STREAM_ENTRY = "https://finder.video.qq.com/live?sig=abc123"


def _svc_with(body):
    """只替掉 `_request`（返回已 unwrap 的 data）：不发网络请求，其余走真实代码。"""
    c = sc.ZhilingServiceClient()
    c.key = "fake-key-for-unit-only"
    c._request = AsyncMock(return_value=body)
    c._client = MagicMock()
    c._client.aclose = AsyncMock()
    return c


# ─────────────────────────────────────────────────────────────
# 1a. 闸门本身：判据要窄不要宽（宽了就是今天这个事故，窄了别误杀在用的直链）
# ─────────────────────────────────────────────────────────────

def test_gate_rejects_site_root():
    reason = direct_url_reject_reason(SITE_ROOT)
    assert reason and "站点首页" in reason
    assert direct_url_reject_reason("http://vnd2.17zhilian.cn") == reason
    # 白话里要带下一步干什么，一线看得懂（这条错误会直接显示在任务列表）
    assert "上传文件反推" in reason


def test_gate_accepts_extensionless_stream_entry():
    """防误杀：真直链有一大类没有扩展名，按「必须带 .mp4」一刀切会打死 16 条在用链接。"""
    assert direct_url_reject_reason(STREAM_ENTRY) is None
    assert direct_url_reject_reason("https://cdn.x/a.mp4?sign=1&t=2") is None
    assert direct_url_reject_reason("https://cdn.x/video/12345") is None


def test_gate_rejects_document_and_image_urls():
    assert "网页文件" in direct_url_reject_reason("https://a.com/page.html")
    assert "网页文件" in direct_url_reject_reason("https://a.com/p/index.PHP?x=1")
    assert "封面图" in direct_url_reject_reason("https://mmecimage.cn/p/wxampicformat,jpg")
    assert "封面图" in direct_url_reject_reason("https://x/picformat!a.jpg")
    assert "http(s)" in direct_url_reject_reason("ftp://a.com/b.mp4")
    assert direct_url_reject_reason(None) and direct_url_reject_reason("   ")


def test_url_shape_text_does_not_leak_signed_query():
    """报错文本会进 error 列、会上界面：签名查询串不许跟着外泄。"""
    text = url_shape_text("https://cdn.x/a.mp4?sign=SECRET123&token=abc")
    assert text == "https://cdn.x/a.mp4"
    assert "SECRET123" not in text


# ─────────────────────────────────────────────────────────────
# 1b. doc/107 收单：在**花钱解析的这一层**就拒
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_direct_url_refuses_site_root():
    """现网事故主场景：智令 code=200 回站点根，必须当场白话拒收，不再往下游递。"""
    body = {"code": 200, "msg": "success", "data": {"play_url": SITE_ROOT}}
    with pytest.raises(ZhilingServiceError) as exc:
        await _svc_with(body).resolve_direct_url("https://weixin.qq.com/sph/AJFwAUW6YY")
    text = str(exc.value)
    assert "视频直链不可用" in text and "站点首页" in text
    assert "code=200" in text          # 带上游状态位，便于找供应商对质
    assert "fake-key-for-unit-only" not in text  # 报错里不许出现密钥
    assert "msg=success" in text or "success" in text  # 外层那句 success 也留着（就是它骗了旧判据）


@pytest.mark.asyncio
async def test_resolve_direct_url_accepts_real_direct_and_stream_entry():
    for url in ("https://cdn.17zhiling.com/v/a.mp4?sign=1", STREAM_ENTRY):
        body = {"code": 200, "data": {"play_url": url}}
        assert await _svc_with(body).resolve_direct_url("https://weixin.qq.com/sph/x") == url


@pytest.mark.asyncio
async def test_resolve_direct_url_keeps_searching_after_a_rejected_candidate():
    """同层里给多个地址时：站点根被拒后要接着找下一个候选，不能见一个拒就收摊。"""
    body = {"code": 200, "msg": "ok", "url": SITE_ROOT, "play_url": "https://cdn.x/b.mp4"}
    assert await _svc_with(body).resolve_direct_url("https://x") == "https://cdn.x/b.mp4"


@pytest.mark.asyncio
async def test_resolve_direct_url_reports_missing_url_without_body_dump():
    """响应里根本没有 http 地址：报错说清「没有」，并且不把整包 body 塞进 error 列。"""
    body = {"code": 500, "msg": "转发请求失败", "data": {"key": "SECRET-VALUE"}}
    with pytest.raises(ZhilingServiceError) as exc:
        await _svc_with(body).resolve_direct_url("https://x")
    text = str(exc.value)
    assert "响应里没有 http 地址" in text and "code=500" in text
    assert "SECRET-VALUE" not in text


@pytest.mark.asyncio
async def test_direct_url_shape_gate_switch_off_restores_old_behaviour(monkeypatch):
    """闸门是**可关的运维阀门**：万一误杀在用的直链，关掉就退回「以 http 开头就收」。"""
    monkeypatch.setattr(sc.settings, "WECHAT_DL_DIRECT_URL_SHAPE_GATE", False)
    body = {"code": 200, "data": {"play_url": SITE_ROOT}}
    assert await _svc_with(body).resolve_direct_url("https://x") == SITE_ROOT


def test_shape_gate_knob_is_registered():
    """新旋钮得有默认值：只写在 .env.example 而没登记进 Settings，读的时候直接 AttributeError。"""
    assert sc.settings.WECHAT_DL_DIRECT_URL_SHAPE_GATE is True
    assert pr.settings.WECHAT_DL_DIRECT_URL_SHAPE_GATE is True


# ─────────────────────────────────────────────────────────────
# 1c. 下载原片那条路（走 provider_registry._normalize，不是 resolve_direct_url）
# ─────────────────────────────────────────────────────────────

def test_normalize_rejects_site_root_with_actionable_error():
    """`AS-BB8563FD` 那 10KB 的 HTML 就是这么被存成「下载成功」的——渠道归一化层先拦下。"""
    res = pr.HttpApiAdapter("unitchan", "https://api.unit.test")._normalize(
        {"code": 0, "msg": "ok", "data": {"url": SITE_ROOT}}, raw="{}"
    )
    assert res.success is False
    assert "无可用视频直链" in res.error and "站点首页" in res.error
    assert "code=0" in res.error


def test_normalize_still_accepts_working_shapes():
    ad = pr.HttpApiAdapter("unitchan", "https://api.unit.test")
    for url in ("https://cdn.x/a.mp4", STREAM_ENTRY):
        res = ad._normalize({"code": 0, "url": url}, raw="{}")
        assert res.success is True and res.play_url == url


def test_normalize_gate_off_still_refuses_cover_image(monkeypatch):
    """开关只管形状，不管图片：关了是放行「形状怪的真视频」，不是放行封面图。"""
    ad = pr.HttpApiAdapter("unitchan", "https://api.unit.test")
    image = "https://mmecimage.cn/p/wxampicformat,jpg"

    monkeypatch.setattr(pr.settings, "WECHAT_DL_DIRECT_URL_SHAPE_GATE", False)
    assert ad._normalize({"code": 0, "url": SITE_ROOT}, raw="{}").success is True
    assert ad._normalize({"code": 0, "url": image}, raw="{}").success is False

    monkeypatch.setattr(pr.settings, "WECHAT_DL_DIRECT_URL_SHAPE_GATE", True)
    assert ad._normalize({"code": 0, "url": image}, raw="{}").success is False
    # 图片判据在前、形状闸门在后：闸门关掉也不会让封面图变成「视频直链」
    assert "站点首页" not in ad._normalize({"code": 0, "url": image}, raw="{}").error


# ─────────────────────────────────────────────────────────────
# 2. FAIL 且上游没人话：原始响应（脱敏＋截断）补进 error
# ─────────────────────────────────────────────────────────────

def test_failed_reason_text_prefers_the_real_reason():
    st = PromptStatus(status=ps.PT_FAILED, error="视频无法下载", raw={"code": 200})
    assert ps._failed_reason_text(st) == "视频无法下载"


def test_failed_reason_text_appends_raw_when_only_the_fallback_remains():
    """errMsg 空 + msg="success"：以前就只剩「任务处理失败」，现在要把原文带上。"""
    st = PromptStatus(
        status=ps.PT_FAILED, error=FAIL_DEFAULT_REASON, schedule="FAIL",
        raw={"code": 200, "msg": "success", "data": {"schedule": "FAIL", "errMsg": ""}},
    )
    out = ps._failed_reason_text(st)
    assert out.startswith(FAIL_DEFAULT_REASON)
    assert "上游未给原因，原始响应" in out
    assert '"schedule": "FAIL"' in out  # 真因线索（哪怕只剩状态位）留在库里可查
    assert ps._failed_reason_text(PromptStatus(status=ps.PT_FAILED, raw=None)) == FAIL_DEFAULT_REASON


def test_raw_brief_scrubs_sensitive_keys_and_truncates():
    out = ps._raw_brief({"key": "SECRET-KEY-VALUE", "authorization": "Bearer x", "code": 200})
    assert "SECRET-KEY-VALUE" not in out and "Bearer x" not in out
    assert "***" in out and '"code": 200' in out
    assert len(ps._raw_brief({"blob": "z" * 5000})) <= ps._RAW_BRIEF_LIMIT
    assert ps._raw_brief(None) == ""


def test_composed_error_can_reach_the_disposal_markers():
    """补进来的原文让标记判据有机会命中——这正是 11-09 那批「不知道该不该补投」的根。"""
    st = PromptStatus(
        status=ps.PT_FAILED, error=FAIL_DEFAULT_REASON,
        raw={"code": 200, "data": {"schedule": "FAIL", "reason": "视频理解服务返回空结果"}},
    )
    assert ps._is_retryable_failure(ps._failed_reason_text(st)) is True

    # 什么线索都没有时仍判「不值得自动花钱」，不会因为多了段 JSON 就误放开
    st2 = PromptStatus(status=ps.PT_FAILED, error=FAIL_DEFAULT_REASON,
                       raw={"code": 200, "data": {"schedule": "FAIL"}})
    assert ps._is_retryable_failure(ps._failed_reason_text(st2)) is False


def _prompt_row(**kw):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.source_url = kw.get("source_url", "https://weixin.qq.com/sph/abc")
    t.source_type = kw.get("source_type", "url")
    t.provider_task_id = kw.get("provider_task_id")
    t.status = kw.get("status", ps.PT_PROCESSING)
    t.content = None
    t.error = None
    t.max_duration = 180
    t.retry_count = 0
    t.created_at = datetime.utcnow()
    return t


@pytest.mark.asyncio
async def test_refresh_prompt_task_stores_raw_when_errmsg_is_empty(monkeypatch):
    """终态入库口径：error 带原文、不超列宽（500），且补投判断吃的是这份带原文的 error。"""
    calls = {"submit": 0}

    async def _submit(*a, **k):
        calls["submit"] += 1
        return "p2"

    fake = MagicMock()
    fake.query = AsyncMock(return_value=PromptStatus(
        status=ps.PT_FAILED, error=FAIL_DEFAULT_REASON, schedule="FAIL",
        raw={"code": 200, "msg": "success", "data": {"schedule": "FAIL", "errMsg": "",
                                                      "reason": "视频理解服务返回空结果"}},
    ))
    fake.submit = AsyncMock(side_effect=_submit)
    fake.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: fake)

    svc = MagicMock()
    svc.resolve_direct_url = AsyncMock(return_value="https://cdn.x/d.mp4")
    svc.close = AsyncMock()
    monkeypatch.setattr(ps, "ZhilingServiceClient", lambda: svc)

    db = AsyncMock()
    claimed = MagicMock()
    claimed.rowcount = 1  # UPDATE ... WHERE retry_count = 0 原子认领成功
    db.execute = AsyncMock(return_value=claimed)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    task = _prompt_row(provider_task_id="p1")
    out = await ps.refresh_prompt_task(db, task)

    assert len(out.error) <= 500
    assert "上游未给原因，原始响应" in out.error

    # 原文里出现了「空结果」→ 标记命中 → 走自动补投（11-09 那批就卡在这一步判不出来）
    assert calls["submit"] == 1
    assert out.retry_count == 1
    assert out.status == ps.PT_PROCESSING
    assert "系统已自动补投一次" in out.error and "上次失败" in out.error


# ─────────────────────────────────────────────────────────────
# 3. 全表僵尸收口（真 SQLite：要害是 WHERE 三条条件筛掉谁）
# ─────────────────────────────────────────────────────────────

from sqlalchemy.dialects.postgresql import UUID as _PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):  # pragma: no cover - 编译期钩子
    return "CHAR(36)"


@pytest_asyncio.fixture
async def db(tmp_path):
    from wechat_download.base import WechatDownloadBase

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'zombie.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(WechatDownloadBase.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _add(db, *, status, provider_task_id, age_minutes):
    from wechat_download.models import WechatDlPromptTask

    now = datetime.utcnow()
    t = WechatDlPromptTask(
        id=uuid.uuid4(),
        source_type="url" if provider_task_id else "upload",
        source_url="https://weixin.qq.com/sph/abc" if provider_task_id
        else "https://cdn.17zhiling.com/temp/a.mp4",
        provider_task_id=provider_task_id,
        status=status,
        created_at=now - timedelta(minutes=age_minutes),
        updated_at=now - timedelta(minutes=age_minutes),
    )
    db.add(t)
    await db.commit()
    return t


@pytest.mark.asyncio
async def test_sweep_converges_only_no_pid_overdue_processing(db, monkeypatch):
    """四行只该收一行：超时无 pid 的 processing。新鲜行、有 pid 的行、终态行都不许动。"""
    from wechat_download.models import PT_FAILED, PT_PROCESSING, PT_SUCCESS

    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS", 3600)

    zombie = await _add(db, status=PT_PROCESSING, provider_task_id=None, age_minutes=120)
    fresh = await _add(db, status=PT_PROCESSING, provider_task_id=None, age_minutes=5)
    with_pid = await _add(db, status=PT_PROCESSING, provider_task_id="p-old", age_minutes=600)
    done = await _add(db, status=PT_SUCCESS, provider_task_id="p-ok", age_minutes=600)

    assert await ps.sweep_zombie_prompt_tasks(db) == 1

    await db.refresh(zombie)
    for t in (fresh, with_pid, done):
        await db.refresh(t)

    assert zombie.status == PT_FAILED
    assert "没有拿到上游任务号" in zombie.error
    assert "没有扣费" in zombie.error and "重新发起一次" in zombie.error  # 白话说清这条没花钱、下一步干什么

    # 有 pid 的过期行**故意不管**：全表口去刷它就会连带走补投＝无人值守花钱
    assert fresh.status == PT_PROCESSING and with_pid.status == PT_PROCESSING
    assert done.status == PT_SUCCESS


@pytest.mark.asyncio
async def test_sweep_follows_the_giveup_knob_and_makes_no_external_calls(db, monkeypatch):
    """容忍时长跟着旋钮变；0 元＝一个外部请求都不发（谁都不许构造上游客户端）。"""
    from wechat_download.models import PT_PROCESSING

    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS", 600)

    def _no_client():
        raise AssertionError("全表收口不许碰上游客户端（会扣费）")

    monkeypatch.setattr(ps, "PromptClient", _no_client)
    monkeypatch.setattr(ps, "ZhilingServiceClient", _no_client)
    monkeypatch.setattr(ps, "UploadClient", _no_client)

    row = await _add(db, status=PT_PROCESSING, provider_task_id=None, age_minutes=30)
    assert await ps.sweep_zombie_prompt_tasks(db) == 1
    await db.refresh(row)
    assert row.status != PT_PROCESSING

    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_POLL_GIVEUP_SECONDS", 3600)
    row2 = await _add(db, status=PT_PROCESSING, provider_task_id=None, age_minutes=30)
    assert await ps.sweep_zombie_prompt_tasks(db) == 0
    await db.refresh(row2)
    assert row2.status == PT_PROCESSING


@pytest.mark.asyncio
async def test_sweep_is_idempotent_when_nothing_qualifies(db, monkeypatch):
    """台账空转时不 commit、不抬错（列表口每次都跑这一条，不能每刷一次页面写一堆无意义事务）。"""
    db.commit = AsyncMock(side_effect=AssertionError("空结果不该 commit"))
    assert await ps.sweep_zombie_prompt_tasks(db) == 0


@pytest.mark.asyncio
async def test_startup_sweep_is_fail_soft(monkeypatch):
    """进程启动不能因为收口失败而崩：表还没建／DB 抖动都得只是记日志。"""
    import app.main as main

    monkeypatch.setattr(main, "async_session_factory", lambda: AsyncMock())

    async def _boom(_db):
        raise RuntimeError("表不存在")

    monkeypatch.setattr(ps, "sweep_zombie_prompt_tasks", _boom)
    await main._sweep_wechat_dl_zombies_at_startup()  # 不抛＝PASS

    def _no_session():
        raise RuntimeError("连接池没起来")

    monkeypatch.setattr(main, "async_session_factory", _no_session)
    await main._sweep_wechat_dl_zombies_at_startup()


@pytest.mark.asyncio
async def test_list_endpoint_sweeps_first_and_survives_sweep_failure(monkeypatch):
    """列表口是另一处**触发**（一线刷页面就会跑到）：先收口，收口炸了也照样出列表。"""
    from wechat_download import api as wd_api

    order = []

    async def _sweep_ok(_db):
        order.append("sweep")
        return 2

    async def _sweep_boom(_db):
        raise RuntimeError("全表扫不动")

    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = []

    async def _execute(stmt):
        order.append("query")
        return res

    db.execute = AsyncMock(side_effect=_execute)
    db.rollback = AsyncMock()

    monkeypatch.setattr(wd_api, "sweep_zombie_prompt_tasks", _sweep_ok)
    out = await wd_api.list_reverse_prompt_tasks(limit=50, current_user=None, db=db)
    assert out == {"items": [], "total": 0}
    assert order == ["sweep", "query"]  # 收口在列表查询之前，刷出来的状态就是收口后的

    order.clear()
    monkeypatch.setattr(wd_api, "sweep_zombie_prompt_tasks", _sweep_boom)
    out2 = await wd_api.list_reverse_prompt_tasks(limit=50, current_user=None, db=db)
    assert out2["total"] == 0                      # 宁可留着僵尸让人看到，也不能让列表 500
    assert db.rollback.await_count == 1            # 收口炸在事务里 → 先回滚再查，不带脏事务往下走
    assert order == ["query"]
