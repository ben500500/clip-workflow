"""ISSUE #361 验收②：operator 访问无主项目剧集的 video-url 必须 200（P0 回归）。

现象（修复前，线上已复现）：
    项目「视频号导入」（created_by = NULL）下剧集的
    `GET /api/episodes/{id}/video-url` 对 operator（role=operator，
    data_scope=own）返回 404；admin/material/publisher（scope=all）正常。
    根因：隔离口径 `project.created_by != current_user.id` 把无主项目判为
    「不匹配任何用户」。

本用例走**真实 FastAPI app + 真实 SQLAlchemy 会话 + 真实 HTTP 端点**
（httpx ASGITransport，SQLite 临时库），从登录拿到 token 后请求 video-url，
断言：
1. operator + 无主项目 → 200，且拿到 presigned url（MinIO 以打桩替代）；
2. operator + 自己的项目 → 200（不回归）；
3. operator + 别人的项目 → 404（不越权）；
4. admin + 无主项目 → 200（原有行为不回归）。

运行：cd backend && python -m pytest tests/integration/test_episode_video_url_public_project.py -v
"""

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

try:  # 允许在未安装 pytest 的环境下直接 python 运行
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

_TMPDIR = Path(tempfile.mkdtemp(prefix="public-project-"))
_DB_PATH = _TMPDIR / "public_project.db"
_DB_URL = f"sqlite+aiosqlite:///{_DB_PATH}"

_TEST_ENV = {
    "DATABASE_URL": _DB_URL,
    "JWT_SECRET": "t" * 64,
    "MINIO_ACCESS_KEY": "test",
    "MINIO_SECRET_KEY": "testtest",
}


class _EnvOverride:
    """临时设置环境变量并在退出时逐项还原（无原值时 pop），不污染同进程其它模块。"""

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

# SQLite 兼容：PostgreSQL 专属 UUID 类型落到 CHAR(36)
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
    from app.models.models import Episode, Project, User

_test_engine = create_async_engine(_DB_URL)
_BACKEND_ENGINE = dbmod.engine
_BACKEND_SESSION_FACTORY = dbmod.async_session_factory

PASSWORD = "pw123456"
OPERATOR = "op_user"
ADMIN = "admin_user"


def _run(coro):
    return asyncio.run(coro)


def _assert_safe_test_database():
    """硬断言：必须是落在本文件临时目录的 sqlite，避免误 drop 真实库。"""
    if _test_engine.url.get_backend_name() != "sqlite":
        raise RuntimeError("拒绝在非 sqlite 后端 drop_all")
    resolved = Path(_test_engine.url.database or "").resolve()
    if _TMPDIR.resolve() not in resolved.parents:
        raise RuntimeError(f"测试库必须落在 {_TMPDIR} 下，实际 {resolved}")


async def _bootstrap():
    """建表 + 造 3 个用户 / 3 个项目：无主、operator 自有、他人所有。"""
    import wechat_download.models  # noqa: F401  触发独立 Base 注册
    from wechat_download.base import WechatDownloadBase

    dbmod.engine = _test_engine
    dbmod.async_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    _assert_safe_test_database()
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(WechatDownloadBase.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(WechatDownloadBase.metadata.create_all)

    ids = {}
    async with dbmod.async_session_factory() as s:
        op = User(
            id=uuid.uuid4(), username=OPERATOR, password_hash=get_password_hash(PASSWORD),
            display_name="Op", role="operator", data_scope="own", is_active=True,
        )
        admin = User(
            id=uuid.uuid4(), username=ADMIN, password_hash=get_password_hash(PASSWORD),
            display_name="Admin", role="admin", data_scope="all", is_active=True,
        )
        s.add_all([op, admin])
        await s.flush()

        # ① 无主项目（复刻「视频号导入」：created_by IS NULL）
        orphan = Project(id=uuid.uuid4(), name="视频号导入", status="draft", created_by=None)
        # ② operator 自己创建
        own = Project(id=uuid.uuid4(), name="op 自己的项目", status="draft", created_by=op.id)
        # ③ 别人创建
        other = Project(id=uuid.uuid4(), name="他人项目", status="draft", created_by=admin.id)
        s.add_all([orphan, own, other])
        await s.flush()

        for key, proj in (("orphan", orphan), ("own", own), ("other", other)):
            ep = Episode(
                id=uuid.uuid4(), project_id=proj.id, title=f"剧集-{key}",
                source_file_key=f"raw-footage/{proj.id}/x.mp4", status="uploaded",
            )
            s.add(ep)
            await s.flush()
            ids[key] = str(ep.id)
        await s.commit()
    return ids


async def _login(client, username):
    r = await client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json().get("access_token")
    assert token, r.text
    return token


async def _get_video_url(episode_id):
    """登录 → 请求 video-url，返回 (status_code, body)。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await _get_video_url_with(client, episode_id)


async def _get_video_url_with(client, episode_id):
    async def _call(token):
        return await client.get(
            f"/api/episodes/{episode_id}/video-url",
            headers={"Authorization": f"Bearer {token}"},
        )

    return _call


# ─────────────────────────────────────────────────────────────
# 用例
# ─────────────────────────────────────────────────────────────

def _video_url(ids, username, key):
    """统一跑一次：返回 (status, body)。presigned 生成为打桩，避免依赖 MinIO。"""
    import app.api.projects as projects_api
    from unittest.mock import AsyncMock

    async def _scenario():
        episode_id = ids[key]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _login(client, username)
            return await client.get(
                f"/api/episodes/{episode_id}/video-url",
                headers={"Authorization": f"Bearer {token}"},
            )

    original = projects_api.get_presigned_url
    projects_api.get_presigned_url = AsyncMock(return_value="http://minio.local/presigned.mp4")
    try:
        resp = _run(_scenario())
    finally:
        projects_api.get_presigned_url = original
    return resp


def test_acceptance_operator_can_access_orphan_project_episode_video_url():
    """验收②核心：无主项目（created_by IS NULL）→ operator 200（修复前 404）。"""
    ids = _run(_bootstrap())
    resp = _video_url(ids, OPERATOR, "orphan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"] == "http://minio.local/presigned.mp4"


def test_operator_own_project_still_ok():
    """不回归：operator 自己的项目照常 200。"""
    ids = _run(_bootstrap())
    assert _video_url(ids, OPERATOR, "own").status_code == 200


def test_operator_other_project_still_404():
    """不越权：别人的项目（有 main）对 operator 依旧 404。"""
    ids = _run(_bootstrap())
    assert _video_url(ids, OPERATOR, "other").status_code == 404


def test_admin_orphan_project_ok():
    """原有行为不回归：admin（scope=all）访问无主项目一直正常。"""
    ids = _run(_bootstrap())
    assert _video_url(ids, ADMIN, "orphan").status_code == 200


def test_derived_endpoint_episodes_list_isolated_consistently():
    """口径一致性：项目列表对 operator 也应看到无主项目（不再是 0 条）。"""
    ids = _run(_bootstrap())

    async def _scenario():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _login(client, OPERATOR)
            return await client.get(
                "/api/projects?page=1&page_size=50",
                headers={"Authorization": f"Bearer {token}"},
            )

    resp = _run(_scenario())
    assert resp.status_code == 200, resp.text
    names = [p["name"] for p in resp.json()["items"]]
    assert "视频号导入" in names          # 无主 = 公共
    assert "op 自己的项目" in names        # 自己创建
    assert "他人项目" not in names         # 不越权
    assert ids  # 保持 ids 被使用
