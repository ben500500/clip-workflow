"""ISSUE #361 任务 A 集成：/api/wechat-dl/reverse-prompt* 端点 + 落库 + 轮询。

智令 doc/120/119 全部 mock（不打真实网络、不扣费），但走**真实 FastAPI app +
真实 SQLAlchemy 会话 + 真实 wechat_dl_prompt_tasks 表**（SQLite 临时库），
验证端到端接线：

1. POST 建任务 → 201，落库 processing 并保存 provider_task_id；
2. GET /{id} → 顺带向上游查询一次，SUCCESS 时写 content、FAIL 时写 error；
3. GET 列表 → 只返回自己可见的任务（operator 口径）；
4. 未登录 → 401（鉴权不因新增端点而漏挂）。

运行：cd backend && python -m pytest tests/integration/test_reverse_prompt_api.py -v
"""

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

try:  # 允许在未安装 pytest 的环境下直接 python 运行
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

_TMPDIR = Path(tempfile.mkdtemp(prefix="reverse-prompt-"))
_DB_PATH = _TMPDIR / "reverse_prompt.db"
_DB_URL = f"sqlite+aiosqlite:///{_DB_PATH}"

_TEST_ENV = {
    "DATABASE_URL": _DB_URL,
    "JWT_SECRET": "t" * 64,
    "MINIO_ACCESS_KEY": "test",
    "MINIO_SECRET_KEY": "testtest",
    "WECHAT_DL_ZHILING_KEY": "fake-key",
}


class _EnvOverride:
    def __init__(self, values):
        self._values = values
        self._saved = {}

    def __enter__(self):
        for k, v in self._values.items():
            self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k, prev in self._saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        return False


for _k, _v in _TEST_ENV.items():
    if _k != "DATABASE_URL":
        os.environ.setdefault(_k, _v)


def _cleanup_tmpdir():
    shutil.rmtree(_TMPDIR, ignore_errors=True)


import atexit  # noqa: E402

atexit.register(_cleanup_tmpdir)

from sqlalchemy.dialects.postgresql import UUID as _PGUUID  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):  # pragma: no cover - 编译期钩子
    return "CHAR(36)"


with _EnvOverride(_TEST_ENV):
    import app.database as dbmod
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.auth import get_password_hash
    from app.database import Base
    from app.main import app
    from app.models.models import User

_test_engine = create_async_engine(_DB_URL)
_BACKEND_ENGINE = dbmod.engine
_BACKEND_SESSION_FACTORY = dbmod.async_session_factory

PASSWORD = "pw123456"
OPERATOR = "prompt_op"


def _run(coro):
    return asyncio.run(coro)


async def _bootstrap():
    import wechat_download.models  # noqa: F401
    from wechat_download.base import WechatDownloadBase

    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(WechatDownloadBase.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(WechatDownloadBase.metadata.create_all)
    async with dbmod.async_session_factory() as s:
        s.add(User(
            id=uuid.uuid4(), username=OPERATOR, password_hash=get_password_hash(PASSWORD),
            display_name="Op", role="operator", data_scope="own", is_active=True,
        ))
        await s.commit()


async def _client_and_token():
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    r = await client.post("/api/auth/login", json={"username": OPERATOR, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client, r.json()["access_token"]


def _fake_prompt_client(*, submit_result=None, submit_error=None, query_result=None):
    """构造 PromptClient 替身（submit / query / close 全打桩）。"""
    fake = MagicMock()
    if submit_error is not None:
        fake.submit = AsyncMock(side_effect=submit_error)
    else:
        fake.submit = AsyncMock(return_value=submit_result or "provider-task-1")
    fake.query = AsyncMock(return_value=query_result)
    fake.close = AsyncMock()
    return fake


def test_create_then_poll_to_success():
    """端到端：POST 建任务 201 → GET 轮询到 SUCCESS 拿到 markdown content。"""
    _run(_bootstrap())
    from wechat_download.prompt_client import PromptStatus

    fake = _fake_prompt_client(
        submit_result="provider-task-1",
        query_result=PromptStatus(status="success", content="# 提示词\n雨中奔跑的女孩"),
    )

    async def _scenario():
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/wechat-dl/reverse-prompt",
            json={"source_url": "https://v.douyin.com/abc", "max_duration": 300},
            headers=h,
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "processing"
        assert body["provider_task_id"] == "provider-task-1"
        assert body["max_duration"] == 300

        # 轮询：后端顺带查一次上游并把 content 落库
        got = await client.get(f"/api/wechat-dl/reverse-prompt/{body['id']}", headers=h)
        assert got.status_code == 200, got.text
        gb = got.json()
        assert gb["status"] == "success"
        assert gb["content"] == "# 提示词\n雨中奔跑的女孩"

        # 落库确认（另开 session 读，等价于另一个请求来读）
        listed = await client.get("/api/wechat-dl/reverse-prompt?limit=50", headers=h)
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert len(items) == 1
        assert items[0]["content"].startswith("# 提示词")

        # 二次轮询不应再打上游（终态不重复查询）
        await client.get(f"/api/wechat-dl/reverse-prompt/{body['id']}", headers=h)
        assert fake.query.await_count == 1
        await client.aclose()

    with patch("wechat_download.prompt_service.PromptClient", lambda: fake), \
         patch("wechat_download.prompt_client.PromptClient", lambda: fake):
        _run(_scenario())


def test_submit_failure_is_fail_soft_201_with_failed_status():
    """外部提交失败（额度耗尽）不抬 500：仍 201，任务落库 failed + error。"""
    _run(_bootstrap())
    from wechat_download.prompt_client import PromptError

    fake = _fake_prompt_client(submit_error=PromptError("额度耗尽，请充值"))

    async def _scenario():
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/wechat-dl/reverse-prompt",
            json={"source_url": "https://v.douyin.com/abc"},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert "额度耗尽" in body["error"]

        # 再查一次：无 provider_task_id，不发起上游查询，状态保持 failed
        got = await client.get(f"/api/wechat-dl/reverse-prompt/{body['id']}", headers=h)
        assert got.status_code == 200
        assert got.json()["status"] == "failed"
        await client.aclose()

    with patch("wechat_download.prompt_service.PromptClient", lambda: fake), \
         patch("wechat_download.prompt_client.PromptClient", lambda: fake):
        _run(_scenario())


def test_requires_auth_and_validates_input():
    """未登录 401；空链接 400。"""
    _run(_bootstrap())

    async def _scenario():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            anon = await client.post(
                "/api/wechat-dl/reverse-prompt", json={"source_url": "https://x/1"}
            )
            assert anon.status_code in (401, 403), anon.text

            _, token = await _client_and_token()
            h = {"Authorization": f"Bearer {token}"}
            empty = await client.post(
                "/api/wechat-dl/reverse-prompt", json={"source_url": "   "}, headers=h
            )
            assert empty.status_code == 400, empty.text

    _run(_scenario())


def test_other_users_task_is_404_for_operator():
    """可见口径：operator 查他人任务 404（不泄露存在性）。"""
    _run(_bootstrap())

    from wechat_download.models import WechatDlPromptTask

    async def _scenario():
        # 直接造一条 created_by 为他人 的任务
        async with dbmod.async_session_factory() as s:
            t = WechatDlPromptTask(
                id=uuid.uuid4(), created_by=uuid.uuid4(),
                source_url="https://x/other", status="processing",
            )
            s.add(t)
            await s.commit()
            other_id = str(t.id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            _, token = await _client_and_token()
            h = {"Authorization": f"Bearer {token}"}
            resp = await client.get(f"/api/wechat-dl/reverse-prompt/{other_id}", headers=h)
            assert resp.status_code == 404, resp.text

    _run(_scenario())
