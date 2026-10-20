"""ISSUE #363 集成：POST /api/wechat-dl/reverse-prompt/upload（本地视频上传反推）。

智令 doc/125 签名、S3 POST、doc/120 提交全部 mock（不打真实网络、不扣费），
但走**真实 FastAPI app + 真实 SQLAlchemy 会话 + 真实 wechat_dl_prompt_tasks 表**
（SQLite 临时库），验证端到端接线：

1. 上传成功 → 201，source_type=upload / file_name 落库，provider_task_id 已保存；
2. 签名失败 / S3 失败 → 仍 201，任务 failed + error（fail-soft，不抬 500）；
3. 非法扩展名 → 400，且**不建任务**（脏数据零容忍）；
4. 超限 → 413（Content-Length 早退 + 落盘累计两条路径）；
5. 未登录 → 401；
6. 列表/详情序列化带 source_type / file_name。

运行：cd backend && python -m pytest tests/integration/test_reverse_prompt_upload_api.py -v
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

_TMPDIR = Path(tempfile.mkdtemp(prefix="reverse-prompt-upload-"))
_DB_PATH = _TMPDIR / "reverse_prompt_upload.db"
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

PASSWORD = "pw123456"
OPERATOR = "prompt_upload_op"

# 一个最小的「假视频」：内容不重要（S3 已 mock），扩展名与大小才是校验对象
VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048


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
    client = AsyncClient(transport=transport, base_url="http://test", timeout=30)
    r = await client.post("/api/auth/login", json={"username": OPERATOR, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client, r.json()["access_token"]


async def _count_tasks() -> int:
    from sqlalchemy import func, select

    from wechat_download.models import WechatDlPromptTask

    async with dbmod.async_session_factory() as s:
        return (await s.execute(select(func.count()).select_from(WechatDlPromptTask))).scalar_one()


def _ticket():
    from wechat_download.upload_client import UploadTicket

    return UploadTicket(
        upload_url="https://zhiling-temp.s3.amazonaws.com/",
        form_fields={
            "key": "temp/abc.mp4", "Content-Type": "video/mp4",
            "x-amz-algorithm": "AWS4-HMAC-SHA256", "policy": "eyJ...",
            "x-amz-signature": "deadbeef",
        },
        object_key="temp/abc.mp4",
        file_url="https://cdn.17zhiling.com/temp/abc.mp4",
    )


def _fake_upload_client(*, sign_error=None, post_error=None):
    fake = MagicMock()
    fake.sign = AsyncMock(side_effect=sign_error) if sign_error else AsyncMock(return_value=_ticket())
    fake.post_file = AsyncMock(side_effect=post_error) if post_error else AsyncMock(return_value=None)
    fake.close = AsyncMock()
    return fake


def _fake_prompt_client(*, submit_result="provider-task-up-1", submit_error=None):
    """doc/120 提交 + doc/119 轮询替身（详情接口会顺带查询一次，query 不能漏桩）。"""
    from wechat_download.prompt_client import PromptStatus

    fake = MagicMock()
    fake.submit = AsyncMock(side_effect=submit_error) if submit_error else AsyncMock(return_value=submit_result)
    fake.query = AsyncMock(return_value=PromptStatus(status="processing", schedule="PROCESSING"))
    fake.close = AsyncMock()
    return fake


class _Patched:
    """同时替换 upload_client 与 prompt_client 两个入口（服务层按名查找）。"""

    def __init__(self, upload, prompt):
        self._upload = upload
        self._prompt = prompt

    def __enter__(self):
        self._stack = [
            patch("wechat_download.prompt_service.UploadClient", lambda: self._upload),
            patch("wechat_download.prompt_service.PromptClient", lambda: self._prompt),
        ]
        for p in self._stack:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._stack):
            p.stop()
        return False


def test_upload_success_creates_upload_task():
    """上传成功 → 201，source_type=upload + file_name 落库，fileUrl 喂给 doc/120。"""
    _run(_bootstrap())
    up = _fake_upload_client()
    cli = _fake_prompt_client()

    async def _scenario():
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/wechat-dl/reverse-prompt/upload",
            files={"file": ("我的视频.mp4", VIDEO_BYTES, "video/mp4")},
            data={"max_duration": "300"},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["source_type"] == "upload"
        assert body["file_name"] == "我的视频.mp4"
        assert body["status"] == "processing"
        assert body["provider_task_id"] == "provider-task-up-1"
        assert body["source_url"] == "https://cdn.17zhiling.com/temp/abc.mp4"
        assert body["max_duration"] == 300

        # S3 POST 的 multipart：formFields 在前、file 最后（AWS POST policy 硬要求）
        _, kwargs = up.post_file.call_args
        assert kwargs["file_name"] == "我的视频.mp4"
        assert kwargs["size_bytes"] == len(VIDEO_BYTES)
        cli.submit.assert_awaited_once_with("https://cdn.17zhiling.com/temp/abc.mp4", 300)

        # 列表 / 详情都带来源字段
        listed = await client.get("/api/wechat-dl/reverse-prompt?limit=50", headers=h)
        assert listed.status_code == 200, listed.text
        item = listed.json()["items"][0]
        assert item["source_type"] == "upload"
        assert item["file_name"] == "我的视频.mp4"

        got = await client.get(f"/api/wechat-dl/reverse-prompt/{body['id']}", headers=h)
        assert got.status_code == 200
        assert got.json()["source_type"] == "upload"
        await client.aclose()

    with _Patched(up, cli):
        _run(_scenario())


def test_sign_failure_is_fail_soft_201_failed():
    """doc/125 签名失败 → 不抬 500，201 + failed + error（与链接方式同口径）。"""
    _run(_bootstrap())
    from wechat_download.upload_client import UploadError

    up = _fake_upload_client(sign_error=UploadError("签名服务不可用"))
    cli = _fake_prompt_client()

    async def _scenario():
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/wechat-dl/reverse-prompt/upload",
            files={"file": ("a.mp4", VIDEO_BYTES, "video/mp4")},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert "签名服务不可用" in body["error"]
        assert body["source_type"] == "upload"
        assert body["file_name"] == "a.mp4"

        # 失败任务在列表里可见（用户能看见原因）
        listed = await client.get("/api/wechat-dl/reverse-prompt?limit=50", headers=h)
        assert any(i["id"] == body["id"] and i["status"] == "failed" for i in listed.json()["items"])
        up.post_file.assert_not_awaited()
        cli.submit.assert_not_awaited()
        await client.aclose()

    with _Patched(up, cli):
        _run(_scenario())


def test_s3_upload_failure_is_fail_soft_201_failed():
    """S3 POST 403 → 201 + failed，且不提交 doc/120（不给智令送一个不存在的地址）。"""
    _run(_bootstrap())
    from wechat_download.upload_client import UploadError

    up = _fake_upload_client(post_error=UploadError("上传视频到存储 http 403: SignatureDoesNotMatch"))
    cli = _fake_prompt_client()

    async def _scenario():
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        resp = await client.post(
            "/api/wechat-dl/reverse-prompt/upload",
            files={"file": ("a.mp4", VIDEO_BYTES, "video/mp4")},
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert "403" in body["error"]
        cli.submit.assert_not_awaited()
        await client.aclose()

    with _Patched(up, cli):
        _run(_scenario())


def test_invalid_extension_400_and_no_task_created():
    """非法扩展名 → 400，且不落任何任务行（不产生脏数据）。"""
    _run(_bootstrap())
    up = _fake_upload_client()
    cli = _fake_prompt_client()

    async def _scenario():
        before = await _count_tasks()
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        for name in ("evil.exe", "notes.txt", "noext"):
            resp = await client.post(
                "/api/wechat-dl/reverse-prompt/upload",
                files={"file": (name, VIDEO_BYTES, "application/octet-stream")},
                headers=h,
            )
            assert resp.status_code == 400, f"{name}: {resp.text}"
            assert "不支持的文件类型" in resp.json()["detail"]
        assert await _count_tasks() == before
        up.sign.assert_not_awaited()
        await client.aclose()

    with _Patched(up, cli):
        _run(_scenario())


def test_oversize_413_via_content_length():
    """超限走 Content-Length 早退 → 413（不落盘、不建任务）。"""
    _run(_bootstrap())
    up = _fake_upload_client()
    cli = _fake_prompt_client()

    async def _scenario():
        from app.config import settings

        before = await _count_tasks()
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}
        with patch.object(settings, "WECHAT_DL_PROMPT_UPLOAD_MAX_MB", 1, create=True):
            resp = await client.post(
                "/api/wechat-dl/reverse-prompt/upload",
                files={"file": ("big.mp4", b"\x00" * (2 * 1024 * 1024), "video/mp4")},
                headers=h,
            )
        assert resp.status_code == 413, resp.text
        assert "MB" in resp.json()["detail"]
        assert await _count_tasks() == before
        up.sign.assert_not_awaited()
        await client.aclose()

    with _Patched(up, cli):
        _run(_scenario())


class _UnknownSizeFile:
    """file-like 但 size 报 0：让 httpx 不生成 Content-Length，走流式累计校验分支。

    真实场景是浏览器/网关的 chunked 上传（无 Content-Length）。这里读不到 EOF，
    因为后端一旦超限就 413 提前返回 —— 读端被取消后本对象不会再被消费。
    """

    def __init__(self, chunk: bytes, chunks: int):
        self._chunk = chunk
        self._left = chunks
        self.name = "big.mp4"

    def seek(self, *_args):
        return 0

    def tell(self):
        return 0

    def read(self, n=-1):
        if self._left <= 0:
            return b""  # 理论上到不了：超限早已 413
        self._left -= 1
        return self._chunk

    def close(self):
        return None


def test_oversize_413_when_streaming_without_content_length():
    """没有 Content-Length 时，边写边计量也必须在超限处 413（内存/磁盘不被打爆）。"""
    _run(_bootstrap())
    up = _fake_upload_client()
    cli = _fake_prompt_client()

    async def _scenario():
        from app.config import settings

        before = await _count_tasks()
        client, token = await _client_and_token()
        h = {"Authorization": f"Bearer {token}"}

        # 3MB 流、上限 1MB：内容长度未知 → 只能靠后端边收边算
        src = _UnknownSizeFile(b"\x00" * (256 * 1024), 12)
        with patch.object(settings, "WECHAT_DL_PROMPT_UPLOAD_MAX_MB", 1, create=True):
            req = client.build_request(
                "POST", "/api/wechat-dl/reverse-prompt/upload",
                files={"file": (src.name, src, "video/mp4")},
                headers=h,
            )
            # httpx 对 file-like 会把 size 报成 0 → 退化为 Content-Length=0 的空文件体。
            # 那正是"声明值与真实体不符"的现实形态：后端不信任声明值，靠落盘累计计数兜底。
            resp = await client.send(req)
        assert resp.status_code == 413, resp.text
        assert "MB" in resp.json()["detail"]
        assert await _count_tasks() == before
        up.sign.assert_not_awaited()
        await client.aclose()

    with _Patched(up, cli):
        _run(_scenario())


def test_requires_auth():
    """未登录 → 401（鉴权不因新增端点而漏挂）。"""
    _run(_bootstrap())

    async def _scenario():
        before = await _count_tasks()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/wechat-dl/reverse-prompt/upload",
                files={"file": ("a.mp4", VIDEO_BYTES, "video/mp4")},
            )
            assert resp.status_code in (401, 403), resp.text
        assert await _count_tasks() == before

    _run(_scenario())
