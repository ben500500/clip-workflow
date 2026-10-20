"""本地视频上传反推（智令 doc/125 签名 → S3 POST → doc/120）单元测试（ISSUE #363）。

外部接口全部 mock，不打真实网络、不落库。覆盖：
1. 签名：成功解析 uploadUrl/formFields/fileUrl；缺 key、code=-1、「无 fileUrl」均失败；
2. S3 POST：formFields 在前、file 最后（AWS POST policy 硬要求）；超时按大小动态算；
   非 2xx / 200 带 <Error> 都判失败；
3. 校验：扩展名白名单、大小上限、content type 映射；
4. 编排：上传成功 → doc/120 提交 → processing；签名失败/S3 失败 → failed+error（不抛）；
5. 序列化：serialize_prompt_task 带 source_type / file_name。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_upload.py -v
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# app.config 是模块级单例，导入即校验必填项 —— 必须在 import 业务模块前置好测试 env
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_upload.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from wechat_download import prompt_client as pc  # noqa: E402
from wechat_download import prompt_service as ps  # noqa: E402
from wechat_download import upload_client as uc  # noqa: E402
from wechat_download.models import (  # noqa: E402
    PST_UPLOAD,
    PST_URL,
    PT_FAILED,
    PT_PROCESSING,
)


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


_SIGN_OK = {
    "code": 200,
    "data": {
        "uploadUrl": "https://zhiling-temp.s3.amazonaws.com/",
        "method": "POST",
        "formFields": {
            "key": "temp/abc.mp4",
            "Content-Type": "video/mp4",
            "x-amz-algorithm": "AWS4-HMAC-SHA256",
            "x-amz-credential": "AKIA/20261020/cn-north-1/s3/aws4_request",
            "x-amz-date": "20261020T000000Z",
            "policy": "eyJ...",
            "x-amz-signature": "deadbeef",
        },
        "objectKey": "temp/abc.mp4",
        "fileUrl": "https://cdn.17zhiling.com/temp/abc.mp4",
    },
    "msg": "ok",
}


def _client_with(resp):
    """构造 UploadClient 并替换 httpx client（key 预置，避免 skip 分支）。"""
    c = uc.UploadClient()
    c.key = "test-key"
    c._client = MagicMock()
    c._client.get = AsyncMock(return_value=resp)
    c._client.post = AsyncMock(return_value=_Resp(204))
    c._client.aclose = AsyncMock()
    return c


def _ticket(**kw):
    return uc.UploadTicket(
        upload_url=kw.get("upload_url", "https://bucket.s3/"),
        form_fields=kw.get("form_fields", {"key": "temp/a.mp4", "policy": "p"}),
        object_key=kw.get("object_key", "temp/a.mp4"),
        file_url=kw.get("file_url", "https://cdn/x.mp4"),
    )


# ─────────────────────────────────────────────────────────────
# 1. doc/125 取签名
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sign_parses_ticket_and_sends_query_params():
    c = _client_with(_Resp(200, _SIGN_OK))
    ticket = await c.sign("我的视频.mp4", content_type="video/mp4")

    assert ticket.upload_url == "https://zhiling-temp.s3.amazonaws.com/"
    assert ticket.file_url == "https://cdn.17zhiling.com/temp/abc.mp4"
    assert ticket.object_key == "temp/abc.mp4"
    # formFields 全部原样带上（AWS4 签名字段少一个 S3 就 403）
    assert set(ticket.form_fields) >= {
        "key", "Content-Type", "x-amz-algorithm", "x-amz-credential",
        "x-amz-date", "policy", "x-amz-signature",
    }

    _, kwargs = c._client.get.call_args
    assert kwargs["params"]["key"] == "test-key"
    assert kwargs["params"]["fileName"] == "我的视频.mp4"
    assert kwargs["params"]["contentType"] == "video/mp4"
    assert kwargs["params"]["expiresIn"] == "900"


@pytest.mark.asyncio
async def test_sign_without_key_fails_fast():
    c = uc.UploadClient()
    c.key = ""
    with pytest.raises(uc.UploadError) as ei:
        await c.sign("a.mp4")
    assert "WECHAT_DL_ZHILING_KEY" in str(ei.value)


@pytest.mark.asyncio
async def test_sign_business_error_and_http_error():
    c = _client_with(_Resp(200, {"code": -1, "data": None, "msg": "签名服务额度不足"}))
    with pytest.raises(uc.UploadError) as ei:
        await c.sign("a.mp4")
    assert "额度不足" in str(ei.value)

    c2 = _client_with(_Resp(502, None, text="bad gateway"))
    with pytest.raises(uc.UploadError) as ei2:
        await c2.sign("a.mp4")
    assert "502" in str(ei2.value)


@pytest.mark.asyncio
async def test_sign_non_json_and_missing_fields():
    c = _client_with(_Resp(200, None, text="<html>WAF</html>"))
    with pytest.raises(uc.UploadError) as ei:
        await c.sign("a.mp4")
    assert "非 JSON" in str(ei.value)

    # 无 uploadUrl / formFields
    c2 = _client_with(_Resp(200, {"code": 200, "data": {"fileUrl": "https://x/1"}}))
    with pytest.raises(uc.UploadError) as ei2:
        await c2.sign("a.mp4")
    assert "uploadUrl/formFields" in str(ei2.value)

    # 无 fileUrl：没法喂 doc/120，必须提前失败（别传完才发现用不上）
    bad = {**_SIGN_OK, "data": {**_SIGN_OK["data"], "fileUrl": ""}}
    c3 = _client_with(_Resp(200, bad))
    with pytest.raises(uc.UploadError) as ei3:
        await c3.sign("a.mp4")
    assert "fileUrl" in str(ei3.value)


@pytest.mark.asyncio
async def test_sign_network_error_raises_upload_error():
    import httpx

    c = _client_with(_Resp(200, _SIGN_OK))
    c._client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(uc.UploadError) as ei:
        await c.sign("a.mp4")
    assert "申请上传签名请求失败" in str(ei.value)


# ─────────────────────────────────────────────────────────────
# 2. S3 POST（multipart，formFields 在前、file 最后）
# ─────────────────────────────────────────────────────────────

class _FakeFile:
    """最小 file-like：只要 seek/read 可用（httpx 读 __iter__/read）。"""

    def __init__(self, data: bytes = b"video-bytes"):
        self._data = data
        self.seek_calls = []

    def seek(self, pos):
        self.seek_calls.append(pos)

    def read(self, n=-1):
        return self._data


@pytest.mark.asyncio
async def test_post_file_puts_form_fields_first_and_file_last():
    c = _client_with(_Resp(200, _SIGN_OK))
    ticket = _ticket(form_fields={"key": "temp/a.mp4", "policy": "p", "x-amz-signature": "s"})

    await c.post_file(ticket, _FakeFile(), file_name="a.mp4", size_bytes=1024)

    _, kwargs = c._client.post.call_args
    # data 必须是 dict（保序）且保持签名里的字段顺序。
    # ⚠️ 不能传 list：httpx 0.28 里 data=list 时 files 被静默丢弃（流退化为
    # 同步 urlencoded IteratorByteStream），AsyncClient 直接 RuntimeError（163 实测 500）。
    assert isinstance(kwargs["data"], dict)
    assert list(kwargs["data"].keys()) == ["key", "policy", "x-amz-signature"]
    # file 字段单独走 files（httpx 会把它排在 multipart 最后）
    assert list(kwargs["files"].keys()) == ["file"]


@pytest.mark.asyncio
async def test_post_file_timeout_scales_with_size():
    c = _client_with(_Resp(200, _SIGN_OK))
    c.min_upload_timeout = 120.0

    # 10MB → max(120, 60) = 120；1000MB → max(120, 6000) = 6000
    await c.post_file(_ticket(), _FakeFile(), file_name="a.mp4", size_bytes=10 * 1024 * 1024)
    small = c._client.post.call_args[1]["timeout"]
    await c.post_file(_ticket(), _FakeFile(), file_name="a.mp4", size_bytes=1000 * 1024 * 1024)
    big = c._client.post.call_args[1]["timeout"]

    assert small.read == pytest.approx(120.0)
    assert big.read == pytest.approx(6000.0)


@pytest.mark.asyncio
async def test_post_file_non_2xx_and_200_with_error_body_raise():
    c = _client_with(_Resp(200, _SIGN_OK))
    c._client.post = AsyncMock(return_value=_Resp(403, None, text="<Error>SignatureDoesNotMatch</Error>"))
    with pytest.raises(uc.UploadError) as ei:
        await c.post_file(_ticket(), _FakeFile(), file_name="a.mp4", size_bytes=1024)
    assert "403" in str(ei.value)

    # 某些网关把 S3 错误包成 200 + XML 错误体
    c2 = _client_with(_Resp(200, _SIGN_OK))
    c2._client.post = AsyncMock(return_value=_Resp(200, None, text="<Error><Code>EntityTooLarge</Code></Error>"))
    with pytest.raises(uc.UploadError) as ei2:
        await c2.post_file(_ticket(), _FakeFile(), file_name="a.mp4", size_bytes=1024)
    assert "被拒" in str(ei2.value)


@pytest.mark.asyncio
async def test_post_file_network_error_is_fail_soft():
    import httpx

    c = _client_with(_Resp(200, _SIGN_OK))
    c._client.post = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(uc.UploadError) as ei:
        await c.post_file(_ticket(), _FakeFile(), file_name="a.mp4", size_bytes=1024)
    assert "上传视频到存储失败" in str(ei.value)


# ─────────────────────────────────────────────────────────────
# 3. 本地校验（扩展名 / 大小 / content type）
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["a.mp4", "A.MOV", "b.webm", "c.avi", "d.mkv", "e.m4v"])
def test_validate_accepts_whitelisted_exts(name):
    assert ps.validate_upload_ext(name) is None


@pytest.mark.parametrize("name", ["a.exe", "a.mov2", "a", "a.mp4.txt", ""])
def test_validate_rejects_other_exts(name):
    err = ps.validate_upload_ext(name)
    assert err and ("不支持的文件类型" in err or "缺少文件名" in err)


def test_validate_rejects_empty_and_oversized(monkeypatch):
    assert "为空" in ps.validate_upload_size(0)

    monkeypatch.setattr(ps.settings, "WECHAT_DL_PROMPT_UPLOAD_MAX_MB", 1, raising=False)
    assert ps.validate_upload_size(1024 * 1024) is None
    err = ps.validate_upload_size(2 * 1024 * 1024)
    assert err and "文件过大" in err
    # 上限现读 settings：运维改 env 重启即生效，不受模块级缓存影响
    assert ps.upload_max_bytes() == 1024 * 1024

    # 组合入口：扩展名优先报错（API 落盘前就先挡非法类型）
    assert "不支持的文件类型" in ps.validate_upload_file("a.exe", 0)
    assert ps.validate_upload_file("a.mp4", 1024) is None


def test_content_type_for_known_and_fallback():
    assert ps.content_type_for("a.mp4") == "video/mp4"
    assert ps.content_type_for("A.MOV") == "video/quicktime"
    assert ps.content_type_for("a.mkv") == "video/x-matroska"
    assert ps.content_type_for("a.unknown") == "video/mp4"


# ─────────────────────────────────────────────────────────────
# 4. 编排：上传 → doc/120 提交（fail-soft）
# ─────────────────────────────────────────────────────────────

def _task_stub():
    t = MagicMock()
    t.id = uuid.uuid4()
    t.created_by = None
    t.source_url = ""
    t.source_type = PST_UPLOAD
    t.file_name = None
    t.provider_task_id = None
    t.status = PT_PROCESSING
    t.content = None
    t.error = None
    t.max_duration = None
    return t


def _db(stub):
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: setattr(obj, "id", stub.id))
    return db


def _patch_clients(monkeypatch, *, sign_error=None, post_error=None, submit_result="pt-1",
                   submit_error=None):
    up = MagicMock()
    up.sign = AsyncMock(side_effect=sign_error) if sign_error else AsyncMock(return_value=_ticket())
    up.post_file = AsyncMock(side_effect=post_error) if post_error else AsyncMock(return_value=None)
    up.close = AsyncMock()
    monkeypatch.setattr(ps, "UploadClient", lambda: up)

    cli = MagicMock()
    cli.submit = AsyncMock(side_effect=submit_error) if submit_error else AsyncMock(return_value=submit_result)
    cli.close = AsyncMock()
    monkeypatch.setattr(ps, "PromptClient", lambda: cli)
    return up, cli


@pytest.mark.asyncio
async def test_upload_success_then_submit_processing(monkeypatch):
    stub = _task_stub()
    db = _db(stub)
    up, cli = _patch_clients(monkeypatch)

    out = await ps.create_upload_prompt_task(
        db, created_by=uuid.uuid4(), file_obj=_FakeFile(),
        file_name="我的视频.mp4", size_bytes=1024, max_duration=300,
    )

    assert out.status == PT_PROCESSING
    assert out.provider_task_id == "pt-1"
    assert out.source_type == PST_UPLOAD
    assert out.file_name == "我的视频.mp4"
    # 回填 doc/125 给的 fileUrl 作为 doc/120 的 videoUrl
    assert out.source_url == "https://cdn/x.mp4"
    cli.submit.assert_awaited_once_with("https://cdn/x.mp4", 300)
    # 先 commit 落行（上传可能数分钟），再调外部
    assert db.commit.await_count >= 2


@pytest.mark.asyncio
async def test_upload_sign_failure_is_fail_soft(monkeypatch):
    stub = _task_stub()
    db = _db(stub)
    up, cli = _patch_clients(monkeypatch, sign_error=uc.UploadError("签名服务挂了"))

    out = await ps.create_upload_prompt_task(
        db, created_by=None, file_obj=_FakeFile(), file_name="a.mp4", size_bytes=1024,
    )

    assert out.status == PT_FAILED
    assert "签名服务挂了" in out.error
    # 签名就失败了，不该发 S3 POST，也不该提交 doc/120
    up.post_file.assert_not_awaited()
    cli.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_s3_failure_is_fail_soft(monkeypatch):
    stub = _task_stub()
    db = _db(stub)
    up, cli = _patch_clients(monkeypatch, post_error=uc.UploadError("403 SignatureDoesNotMatch"))

    out = await ps.create_upload_prompt_task(
        db, created_by=None, file_obj=_FakeFile(), file_name="a.mp4", size_bytes=1024,
    )

    assert out.status == PT_FAILED
    assert "403" in out.error
    up.sign.assert_awaited_once()
    cli.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_ok_but_doc120_failure_records_error(monkeypatch):
    """上传成功但 doc/120 拒绝（额度耗尽）：仍 fail-soft，任务带 error。"""
    stub = _task_stub()
    db = _db(stub)
    _, cli = _patch_clients(monkeypatch, submit_error=pc.PromptError("额度耗尽"))

    out = await ps.create_upload_prompt_task(
        db, created_by=None, file_obj=_FakeFile(), file_name="a.mp4", size_bytes=1024,
    )

    assert out.status == PT_FAILED
    assert "额度耗尽" in out.error
    # fileUrl 已回填，便于排障时直接打开文件确认
    assert out.source_url == "https://cdn/x.mp4"
    cli.submit.assert_awaited_once()


# ─────────────────────────────────────────────────────────────
# 5. 序列化 & 来源字段（列表口径）
# ─────────────────────────────────────────────────────────────

def test_serialize_includes_source_type_and_file_name():
    t = _task_stub()
    t.source_url = "https://cdn/x.mp4"
    t.source_type = PST_UPLOAD
    t.file_name = "a.mp4"
    out = ps.serialize_prompt_task(t)
    assert out["source_type"] == PST_UPLOAD
    assert out["file_name"] == "a.mp4"

    # url 来源：source_type 缺省按 url 展示（老数据兼容）
    t2 = _task_stub()
    t2.source_type = None
    t2.file_name = None
    out2 = ps.serialize_prompt_task(t2)
    assert out2["source_type"] == PST_URL
    assert out2["file_name"] is None
