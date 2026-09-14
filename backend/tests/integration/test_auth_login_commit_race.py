"""Issue #350 回归：登录响应先于 session 提交 → 登录后立即发起的请求 401。

缺陷时序（修复前）：
    login() 内 create_user_session() 只 flush 不 commit
      → 返回 LoginResponse → **响应字节发到客户端**
      → get_db() 的 yield 之后才 commit → user_sessions 行这时才落库
    app/auth.py:get_current_user 用该行做会话黑名单校验，查不到即判
    「会话已失效，请重新登录」(401)。
    本仓 FastAPI>=0.106 起，yield 依赖的退出在响应发出**之后**执行，故必然命中。

本用例在**没有 pytest-asyncio** 的环境下也真实执行：用 asyncio.run() 驱动，
每个用例都是普通 `def test_xxx()`（不是 async def），pytest 无需任何 async 插件。

运行：cd backend && python -m pytest tests/integration/test_auth_login_commit_race.py -v
   或  cd backend && python tests/integration/test_auth_login_commit_race.py

依赖真实栈：真实 FastAPI app + 真实 SQLAlchemy AsyncSession + 真实 HTTP（httpx ASGITransport）。
数据库用 aiosqlite 临时文件（PostgreSQL 专属 UUID 类型由 @compiles 落到 CHAR(36)）。
"""
import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:  # 允许在未安装 pytest 的环境下直接 python 运行本文件
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

# ── 测试环境：SQLite(async) + 最小必填配置（须在建 app 之前设置）──
_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ.setdefault("JWT_SECRET", "t" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from sqlalchemy import DateTime as _DateTime
from sqlalchemy.dialects.postgresql import UUID as _PGUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import TypeDecorator


class _NaiveUtcDateTime(TypeDecorator):
    """SQLite 不保存 tzinfo；读出后补 UTC，还原 PostgreSQL TIMESTAMPTZ 语义。

    生产（PG）里 expires_at 是 aware UTC，代码用
    `expires_at < utcnow().replace(tzinfo=utc)` 比较；
    SQLite 会读成 naive → 触发 offset-naive/aware TypeError。
    这是测试替身的差异，不是被测逻辑的缺陷，故在此归一化。
    """

    impl = _DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            from datetime import timezone

            return value.replace(tzinfo=timezone.utc)
        return value


@compiles(_PGUUID, "sqlite")
def _pg_uuid_on_sqlite(type_, compiler, **kw):  # pragma: no cover - 编译期钩子
    """让 PostgreSQL 专属 UUID 类型可在 SQLite 上建表（CHAR(36) 存字符串）。"""
    return "CHAR(36)"


import app.database as dbmod
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 测试专用引擎（生产引擎带 server_settings/pool_size 等 PG 专属参数，SQLite 不接受）
_test_engine = create_async_engine(f"sqlite+aiosqlite:///{_TMP_DB}")
dbmod.engine = _test_engine
dbmod.async_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)

from httpx import ASGITransport, AsyncClient

from app.api.auth import REFRESH_COOKIE_NAME
from app.auth import get_password_hash
from app.database import Base
from app.main import app
from app.models.models import User, UserSession

# SQLite 不保存 tzinfo：让 expires_at 读出即带 UTC，还原 PG TIMESTAMPTZ 语义。
# 必须在 create_all 之前生效（DDL 与 result 处理都取自列类型）。
UserSession.__table__.c.expires_at.type = _NaiveUtcDateTime()

USERNAME = "benny"
PASSWORD = "pw123456"


# ─────────────────────────────────────────────────────────────
# 驱动工具：无 pytest-asyncio 也能真跑
# ─────────────────────────────────────────────────────────────

def _run(coro):
    """用 asyncio.run() 驱动协程——不依赖任何 pytest async 插件。"""
    return asyncio.run(coro)


async def _bootstrap():
    """建表 + 造一个可登录用户（整体重建，保证用例间互不干扰）。"""
    # 同一 pytest 进程里若有其它 sqlite 测试模块，它们也会改 dbmod.engine；
    # 每次 bootstrap 都把 app 的会话工厂重新指回本模块的测试引擎，
    # 使本模块与执行顺序无关。
    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    # wechat_download 用独立 Base，不在主 Base.metadata 中，需一并建表
    from wechat_download.base import WechatDownloadBase

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(WechatDownloadBase.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(WechatDownloadBase.metadata.create_all)
    async with dbmod.async_session_factory() as s:
        s.add(
            User(
                id=uuid.uuid4(),
                username=USERNAME,
                password_hash=get_password_hash(PASSWORD),
                display_name="Benny",
                role="admin",
                data_scope="all",
                is_active=True,
            )
        )
        await s.commit()


async def _count_sessions_independent() -> int:
    """用**独立连接**数 user_sessions——等价于另一个并发请求/进程来读。"""
    async with dbmod.async_session_factory() as s:
        return (await s.execute(select(func.count()).select_from(UserSession))).scalar()


async def _login(client: AsyncClient):
    return await client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )


# ─────────────────────────────────────────────────────────────
# 最小 ASGI 客户端：真实走 ASGI 协议，收到响应即返回，
# **不等** app 生命周期收尾（这正是生产 uvicorn 的行为，也是竞态的触发条件）。
# httpx 的 ASGITransport 会 await 整个 app() 才返回，会把竞态掩盖掉，故不用它。
# ─────────────────────────────────────────────────────────────

async def _asgi_request(method, path, *, body=b"", headers=None, cookies=None) -> dict:
    """发送一个 ASGI HTTP 请求，返回 {status, headers, body}。

    关键：函数在收到 `http.response.body(more_body=False)` 后**立刻 return**，
    不等 app() 协程结束 → 精确复刻「客户端已拿到响应、而 get_db 尾部 commit 未跑」的窗口。
    """
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw_headers.append(
            (b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode())
        )
    raw_headers.append((b"content-type", b"application/json"))
    raw_headers.append((b"content-length", str(len(body)).encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "server": ("test", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }

    sent_body = False

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        # 客户端拿到响应后即断开，不再等待 app 收尾
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    result: dict = {"status": None, "headers": [], "body": b""}
    got_body = asyncio.Event()
    send_gate = asyncio.Event()   # 允许「收到终帧后要做的下一件事」先跑完
    body_delivered = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.start":
            result["status"] = message["status"]
            result["headers"] = message.get("headers", [])
        elif message["type"] == "http.response.body":
            result["body"] += message.get("body", b"")
            if not message.get("more_body", False):
                got_body.set()
                body_delivered.set()
                # 关键：终帧已发到「客户端」，此时先让 on_final_body 抢占事件循环
                # （真实客户端此刻就会发下一个请求），之后再继续 app 的收尾工作。
                await send_gate.wait()

    task = asyncio.create_task(app(scope, receive, send))
    await got_body.wait()
    result["_task"] = task
    result["_send_gate"] = send_gate
    result["_body_delivered"] = body_delivered
    return result


async def _send_and_wait_next(resp, coro_factory):
    """在「登录终帧已发出、收尾未执行」的窗口内发起下一个请求。

    真实客户端（脚本/前端）收到 200 就会立刻发下一个请求，不等服务端收尾；
    这里用独立 task + 独立 DB 连接复刻该并发窗口。
    """
    waiter = asyncio.create_task(coro_factory())
    # 让下一个请求先把独立连接上的读做完
    await asyncio.sleep(0)
    result = await waiter
    # 放行登录协程继续收尾（get_db 尾部 commit）
    resp["_send_gate"].set()
    return result


def _json(resp: dict):
    import json as _jsonlib

    return _jsonlib.loads(resp["body"].decode() or "{}")


# ─────────────────────────────────────────────────────────────
# 用例 1（核心验收）：登录后**同步立即**调 /api/auth/me 必须 200，不得 sleep
# ─────────────────────────────────────────────────────────────
def test_me_immediately_after_login_is_200_without_sleep():
    """修复前：401 会话已失效；修复后：200。全程无 sleep / 无重试。

    时序被精确复刻：客户端一收到登录响应（http.response.body 终帧）就立刻
    发 /api/auth/me，此时若 session 行尚未提交 → get_current_user 查不到 → 401。
    """

    import json as _jsonlib

    async def _case():
        await _bootstrap()
        login = await _asgi_request(
            "POST",
            "/api/auth/login",
            body=_jsonlib.dumps({"username": USERNAME, "password": PASSWORD}).encode(),
        )
        assert login["status"] == 200, login["body"]
        token = _json(login)["access_token"]

        # ← 关键：不 sleep、不重试。在「登录响应终帧已发出 / get_db 收尾提交尚未执行」
        #    的窗口内，用独立连接发起第一个受保护请求（等价于真实客户端的下一跳）。
        me = await _send_and_wait_next(
            login,
            lambda: _asgi_request(
                "GET", "/api/auth/me", headers={"authorization": f"Bearer {token}"}
            ),
        )
        return login, me

    _, me = _run(_case())
    assert me["status"] == 200, (
        f"登录后立即请求 /api/auth/me 应为 200，实际 {me['status']} "
        f"{me['body'][:200].decode(errors='replace')}"
    )
    assert _json(me)["username"] == USERNAME


# ─────────────────────────────────────────────────────────────
# 用例 2：响应最后一字节发出时，session 行对独立连接已可见（时序断言）
# ─────────────────────────────────────────────────────────────
def test_session_row_visible_to_independent_connection_when_response_sent():
    """直接钉住根因时序：响应发完的瞬间，独立连接必须能查到刚建的 session 行。

    修复前实测 visible=0（commit 在响应之后才跑）→ 失败；
    修复后 visible=1（login 内显式 commit 已落库）→ 通过。
    """
    seen = {}

    async def _case():
        await _bootstrap()

        async def wrapped(scope, receive, send):
            async def logging_send(message):
                # 最后一个 body 分片 = 响应已完整发出
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    seen["visible"] = await _count_sessions_independent()
                await send(message)

            return await app(scope, receive, logging_send)

        transport = ASGITransport(app=wrapped)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _login(client)
            assert resp.status_code == 200, resp.text

    _run(_case())
    assert seen["visible"] == 1, (
        "登录响应已发出时，user_sessions 行对独立连接仍不可见 "
        f"(visible={seen.get('visible')})：session 提交晚于响应 → 首个请求必 401"
    )


# ─────────────────────────────────────────────────────────────
# 用例 3：登录 → 立即调写路径（/api/wechat-dl/import）必须 200，不得 sleep
# ─────────────────────────────────────────────────────────────
def test_write_path_immediately_after_login_is_200():
    """同一 token 紧接着调写路径，鉴权依赖同样要能读到 session 行。

    本用例聚焦「鉴权是否通过」，故把 Celery 投递打成替身：
    测试环境无 Redis/Celery broker，真实投递会报连接错误，与 #350 无关。
    """

    async def _case():
        await _bootstrap()
        transport = ASGITransport(app=app)
        with patch("app.celery.tasks.celery_app.send_task",
                   lambda *a, **k: SimpleNamespace(id="stub-celery-id")):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                login_resp = await _login(client)
                assert login_resp.status_code == 200, login_resp.text
                token = login_resp.json()["access_token"]

                resp = await client.post(
                    "/api/wechat-dl/import",
                    json={"source_url": "https://channels.weixin.qq.com/x"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                return resp

    resp = _run(_case())
    # 鉴权必须先通过（401 即回归）；下游缺失不影响判据
    assert resp.status_code != 401, f"登录后立即发写请求被鉴权打回: {resp.text}"
    assert resp.status_code in (200, 201), resp.text


# ─────────────────────────────────────────────────────────────
# 用例 4：get_db 尾部 commit 成为幂等空操作（不产生二次提交/不回滚已提交数据）
# ─────────────────────────────────────────────────────────────
def test_tail_commit_is_idempotent_noop_after_explicit_commit():
    """login 内显式 commit 后，get_db 尾部再 commit 不得报错、不得丢刚提交的行。"""

    async def _case():
        await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _login(client)
            assert resp.status_code == 200, resp.text
        # 整条请求（含 get_db 尾部 commit）已结束，行仍应在
        return await _count_sessions_independent()

    assert _run(_case()) == 1


# ─────────────────────────────────────────────────────────────
# 用例 5：refresh 行为不变——登录后立即 refresh 仍能拿到新 access_token
# ─────────────────────────────────────────────────────────────
def test_refresh_immediately_after_login_still_works():
    async def _case():
        await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_resp = await _login(client)
            assert login_resp.status_code == 200, login_resp.text
            refresh_cookie = login_resp.cookies.get(REFRESH_COOKIE_NAME)
            assert refresh_cookie, "登录必须下发 refresh_token Cookie"
            return await client.post(
                "/api/auth/refresh", cookies={REFRESH_COOKIE_NAME: refresh_cookie}
            )

    resp = _run(_case())
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token")


# ─────────────────────────────────────────────────────────────
# 用例 6：logout 行为不变——登录后立即登出，会话被吊销
# ─────────────────────────────────────────────────────────────
def test_logout_immediately_after_login_revokes_session():
    async def _case():
        await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_resp = await _login(client)
            assert login_resp.status_code == 200, login_resp.text
            token = login_resp.json()["access_token"]
            refresh_cookie = login_resp.cookies.get(REFRESH_COOKIE_NAME)

            logout_resp = await client.post(
                "/api/auth/logout",
                cookies={REFRESH_COOKIE_NAME: refresh_cookie},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert logout_resp.status_code == 200, logout_resp.text

            async with dbmod.async_session_factory() as s:
                rows = (await s.execute(select(UserSession))).scalars().all()
                return [r.is_revoked for r in rows]

    assert _run(_case()) == [True]


# ─────────────────────────────────────────────────────────────
# 用例 7：失败登录不得落 session 行（提交边界不影响回滚语义）
# ─────────────────────────────────────────────────────────────
def test_failed_login_creates_no_session():
    async def _case():
        await _bootstrap()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/login", json={"username": USERNAME, "password": "wrong"}
            )
            assert resp.status_code == 401, resp.text
        return await _count_sessions_independent()

    assert _run(_case()) == 0


if __name__ == "__main__":
    # 无需 pytest 也能直接跑：python tests/integration/test_auth_login_commit_race.py
    _here = sys.modules[__name__]
    _tests = sorted(
        (n, f) for n, f in vars(_here).items()
        if n.startswith("test_") and callable(f)
    )
    _failed = 0
    for _name, _fn in _tests:
        try:
            if _fn.__code__.co_argcount:
                _fn(None)  # pytest.mark 参数化用例此处不跑
            else:
                _fn()
            print(f"PASS  {_name}")
        except Exception as _exc:  # noqa: BLE001
            _failed += 1
            print(f"FAIL  {_name}: {_exc}")
    print(f"\n{len(_tests) - _failed} passed, {_failed} failed, {len(_tests)} collected")
    sys.exit(1 if _failed else 0)
