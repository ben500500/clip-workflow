"""智令「其他服务」任务测试（ISSUE #370）。

覆盖 issue 点名的四类断言：
1. TTS 参数校验（>5000 字 / builtin 缺 voiceId / cloned 缺 modelId）；
2. 三种查询状态映射各一例（102 字符串 schedule / 105 整数 schedule / 108 字符串 status）；
3. retry 仅 failed 可重试；
4. ai_eraser 直链解析失败 → 任务置 failed 且 error 指路。

另有 direct url 判定与 create 成功路径，避免「只测失败面」的假绿。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_zhiling_services.py -v
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# app.config 是模块级单例，导入即校验必填项 —— 与 test_wechat_dl_prompt_retry.py 同模式
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_zhiling_services.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")
os.environ.setdefault("WECHAT_DL_ZHILING_KEY", "fake-key")

from wechat_download import api as api_mod
from wechat_download import services_service as svc
from wechat_download.models import ZS_FAILED, ZS_PROCESSING, ZS_SUCCESS
from wechat_download.services_client import (
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_SUCCESS,
    ZhilingServiceClient,
    ZhilingServiceError,
)


# ─────────────────────────── ① TTS 参数校验 ───────────────────────────

def test_tts_rejects_text_over_limit():
    err = svc.validate_submit(
        task_type="tts", source_url=None, text="字" * 5001,
        options={"voice_type": "builtin", "voice_id": "306"},
    )
    assert err and "5000" in err


def test_tts_builtin_requires_voice_id():
    err = svc.validate_submit(
        task_type="tts", source_url=None, text="你好",
        options={"voice_type": "builtin"},
    )
    assert err == "内置音色需选择音色（voiceId）"


def test_tts_cloned_requires_model_id():
    err = svc.validate_submit(
        task_type="tts", source_url=None, text="你好",
        options={"voice_type": "cloned"},
    )
    assert err == "自定义音色需填写 modelId"


def test_tts_ok_with_builtin_voice():
    assert svc.validate_submit(
        task_type="tts", source_url=None, text="你好",
        options={"voice_type": "builtin", "voice_id": "306", "format": "mp3"},
    ) is None


def test_voice_clone_requires_name_and_audio_url():
    assert svc.validate_submit(
        task_type="voice_clone", source_url="", text=None, options={"model_name": "我的音色"},
    ) == "请填写音频 URL（mp3/wav）"
    assert svc.validate_submit(
        task_type="voice_clone", source_url="https://cdn.x/a.mp3", text=None, options={},
    ) == "请填写音色模型名称"


def test_unknown_task_type_rejected():
    assert "不支持" in (svc.validate_submit(
        task_type="nope", source_url="https://a.b/c.mp4", text=None, options={},
    ) or "")


# ─────────────────────────── ② 查询状态映射 ───────────────────────────

def _client_with_body(body: dict):
    """构造一个 _request 直接返回解析后 body['data'] 的客户端。"""
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value=body)
    # 记录查询路径，断言参数名没有写错（tts 必须 recordId）
    c._get_status = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_asr_schedule_string_success():
    """doc/102：schedule 是字符串 SUCCESS，content/srtContent 落到正文字段。"""
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value={"schedule": "SUCCESS", "content": "文案正文", "srtContent": "1\n00:00:01,000"})
    st = await c.query_asr("t1")
    await c.close()
    assert st.status == STATUS_SUCCESS
    assert st.result_text == "文案正文"
    assert st.srt_text.startswith("1")


@pytest.mark.asyncio
async def test_asr_schedule_waiting_is_processing():
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value={"schedule": "WAIT_HANDLE"})
    st = await c.query_asr("t1")
    await c.close()
    assert st.status == STATUS_PROCESSING


@pytest.mark.asyncio
async def test_asr_schedule_fail_carries_msg():
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value={"schedule": "FAIL", "msg": "链接无法识别"})
    st = await c.query_asr("t1")
    await c.close()
    assert st.status == STATUS_FAILED
    assert st.error == "链接无法识别"


@pytest.mark.asyncio
async def test_eraser_schedule_int_success_and_progress():
    """doc/105：schedule 是整数，2 成功 / 1 处理中 / 3 失败。"""
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value={"schedule": 2, "progress": 1, "resultUrl": "https://cdn.x/out.mp4"})
    st = await c.query_eraser("t2")
    await c.close()
    assert st.status == STATUS_SUCCESS
    assert st.result_url == "https://cdn.x/out.mp4"

    c2 = ZhilingServiceClient()
    c2._request = AsyncMock(return_value={"schedule": 1, "progress": 0.42})
    st2 = await c2.query_eraser("t2")
    await c2.close()
    assert st2.status == STATUS_PROCESSING
    assert st2.progress == pytest.approx(0.42)

    c3 = ZhilingServiceClient()
    c3._request = AsyncMock(return_value={"schedule": 3, "msg": "源文件已失效"})
    st3 = await c3.query_eraser("t2")
    await c3.close()
    assert st3.status == STATUS_FAILED
    assert st3.error == "源文件已失效"


@pytest.mark.asyncio
async def test_tts_status_string_completed_and_failed():
    """doc/108：data.status 是 processing / completed / failed。"""
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value={"status": "completed", "url": "https://cdn.x/a.mp3", "audioFormat": "mp3"})
    st = await c.query_tts("r1")
    await c.close()
    assert st.status == STATUS_SUCCESS
    assert st.result_url == "https://cdn.x/a.mp3"

    c2 = ZhilingServiceClient()
    c2._request = AsyncMock(return_value={"status": "processing"})
    st2 = await c2.query_tts("r1")
    await c2.close()
    assert st2.status == STATUS_PROCESSING

    c3 = ZhilingServiceClient()
    c3._request = AsyncMock(return_value={"status": "failed", "msg": "音色不可用"})
    st3 = await c3.query_tts("r1")
    await c3.close()
    assert st3.status == STATUS_FAILED
    assert st3.error == "音色不可用"


@pytest.mark.asyncio
async def test_tts_query_uses_record_id_param():
    """参数名必须是 recordId（照抄官方文档），写错必 400。"""
    c = ZhilingServiceClient()
    c._request = AsyncMock(return_value={"status": "processing"})
    await c.query_tts("rec-1")
    await c.close()
    args, kwargs = c._request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/voiceclone/tts/status"
    assert kwargs["params"] == {"key": "fake-key", "recordId": "rec-1"}


# ─────────────────────────── ③ retry 仅 failed ───────────────────────────

def _task(status=ZS_FAILED, task_type="ai_eraser",
          input_url="https://cdn.x/a.mp4", input_text=None, params=None):
    t = type("T", (), {})()
    t.id = uuid.uuid4()
    t.status = status
    t.task_type = task_type
    t.input_url = input_url
    t.input_text = input_text
    t.params = params or {"direct_url": input_url}
    return t


def _user():
    u = type("U", (), {})()
    u.id = uuid.uuid4()
    return u


@pytest.mark.asyncio
async def test_retry_copies_params_for_failed_task(monkeypatch):
    old = _task()
    new = _task(status=ZS_PROCESSING)
    monkeypatch.setattr(api_mod, "get_service_task", AsyncMock(return_value=old))
    monkeypatch.setattr(api_mod, "can_access_service_task", lambda t, u: True)
    create = AsyncMock(return_value=new)
    monkeypatch.setattr(api_mod, "create_service_task", create)
    monkeypatch.setattr(api_mod, "serialize_service_task", lambda t: t)

    user = _user()
    out = await api_mod.retry_zhiling_service_task(old.id, current_user=user, db=AsyncMock())
    assert out is new
    kwargs = create.call_args.kwargs
    assert kwargs["task_type"] == old.task_type
    assert kwargs["source_url"] == old.input_url
    assert kwargs["options"] == old.params
    assert kwargs["created_by"] == user.id


@pytest.mark.asyncio
async def test_retry_rejects_non_failed(monkeypatch):
    monkeypatch.setattr(api_mod, "get_service_task", AsyncMock(return_value=_task(status=ZS_SUCCESS)))
    monkeypatch.setattr(api_mod, "can_access_service_task", lambda t, u: True)
    with pytest.raises(HTTPException) as ei:
        await api_mod.retry_zhiling_service_task(uuid.uuid4(), current_user=_user(), db=AsyncMock())
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_retry_404_when_missing_or_denied(monkeypatch):
    monkeypatch.setattr(api_mod, "get_service_task", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as ei:
        await api_mod.retry_zhiling_service_task(uuid.uuid4(), current_user=_user(), db=AsyncMock())
    assert ei.value.status_code == 404


# ─────────────────────────── ④ create 路径 + 直链解析失败 ───────────────────────────

class _FakeDB:
    """最小 AsyncSession 替身：只关心 add/commit/refresh 调用不报错。"""

    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return obj


def _patch_client(monkeypatch, **methods):
    """把 services_service 里新建的 client 换成带指定异步方法的假 client。"""
    client = MagicMock()
    client.close = AsyncMock()
    for name in ("resolve_direct_url", "submit_eraser", "submit_copy_extract",
                 "submit_tts", "create_voice_model", "query_asr", "query_eraser", "query_tts"):
        setattr(client, name, AsyncMock())
    for k, v in methods.items():
        setattr(client, k, v)
    monkeypatch.setattr(svc, "ZhilingServiceClient", lambda: client)
    return client


def test_is_direct_video_url():
    assert svc.is_direct_video_url("https://cdn.x/a.mp4")
    assert svc.is_direct_video_url("https://cdn.x/a.MOV?sign=1&t=2")
    assert not svc.is_direct_video_url("https://weixin.qq.com/sph/abc")
    assert not svc.is_direct_video_url("ftp://cdn.x/a.mp4")


@pytest.mark.asyncio
async def test_ai_eraser_direct_url_skips_resolve(monkeypatch):
    """直链提交时不走 doc/107 解析（省 0.01 元/次）。"""
    client = _patch_client(monkeypatch, submit_eraser=AsyncMock(return_value="task-1"))
    db = _FakeDB()
    task = await svc.create_service_task(
        db, created_by=None, task_type="ai_eraser", source_url="https://cdn.x/a.mp4",
    )
    client.resolve_direct_url.assert_not_awaited()
    client.submit_eraser.assert_awaited_once_with("https://cdn.x/a.mp4", hd=False)
    assert task.status == ZS_PROCESSING
    assert task.provider_task_id == "task-1"


@pytest.mark.asyncio
async def test_hd_restore_uses_hd_endpoint(monkeypatch):
    client = _patch_client(monkeypatch, submit_eraser=AsyncMock(return_value="task-2"))
    await svc.create_service_task(
        _FakeDB(), created_by=None, task_type="hd_restore", source_url="https://cdn.x/a.mp4",
    )
    client.submit_eraser.assert_awaited_once_with("https://cdn.x/a.mp4", hd=True)


@pytest.mark.asyncio
async def test_ai_eraser_resolve_failure_marks_failed(monkeypatch):
    """分享链接解析直链失败 → 任务 failed，error 里写清「视频直链解析失败」。"""
    _patch_client(
        monkeypatch,
        resolve_direct_url=AsyncMock(side_effect=ZhilingServiceError("未返回视频直链")),
    )
    task = await svc.create_service_task(
        _FakeDB(), created_by=None, task_type="ai_eraser",
        source_url="https://weixin.qq.com/sph/abc",
    )
    assert task.status == ZS_FAILED
    assert "视频直链解析失败" in (task.error or "")


@pytest.mark.asyncio
async def test_ai_eraser_share_url_resolved_then_stored(monkeypatch):
    client = _patch_client(
        monkeypatch,
        resolve_direct_url=AsyncMock(return_value="https://cdn.x/direct.mp4"),
        submit_eraser=AsyncMock(return_value="task-3"),
    )
    task = await svc.create_service_task(
        _FakeDB(), created_by=None, task_type="ai_eraser",
        source_url="https://weixin.qq.com/sph/abc",
    )
    client.submit_eraser.assert_awaited_once_with("https://cdn.x/direct.mp4", hd=False)
    assert task.params["direct_url"] == "https://cdn.x/direct.mp4"
    assert task.status == ZS_PROCESSING


@pytest.mark.asyncio
async def test_voice_clone_is_synchronous_success(monkeypatch):
    _patch_client(
        monkeypatch,
        create_voice_model=AsyncMock(return_value={"model_id": "m-9", "model_name": "我的音色"}),
    )
    task = await svc.create_service_task(
        _FakeDB(), created_by=None, task_type="voice_clone",
        source_url="https://cdn.x/voice.mp3", options={"model_name": "我的音色"},
    )
    assert task.status == ZS_SUCCESS
    assert task.voice_model_id == "m-9"


@pytest.mark.asyncio
async def test_copy_extract_passes_need_srt(monkeypatch):
    client = _patch_client(monkeypatch, submit_copy_extract=AsyncMock(return_value="task-4"))
    task = await svc.create_service_task(
        _FakeDB(), created_by=None, task_type="copy_extract",
        source_url="https://v.douyin.com/abc", options={"need_srt": False},
    )
    client.submit_copy_extract.assert_awaited_once_with("https://v.douyin.com/abc", need_srt=False)
    assert task.params["need_srt"] is False


@pytest.mark.asyncio
async def test_tts_submit_forwards_voice_params(monkeypatch):
    client = _patch_client(monkeypatch, submit_tts=AsyncMock(return_value="rec-9"))
    task = await svc.create_service_task(
        _FakeDB(), created_by=None, task_type="tts", text="你好",
        options={"voice_type": "builtin", "voice_id": "306", "format": "mp3"},
    )
    kwargs = client.submit_tts.call_args.kwargs
    assert kwargs["voice_type"] == "builtin"
    assert kwargs["voice_id"] == "306"
    assert kwargs["model_id"] is None
    assert kwargs["audio_format"] == "mp3"
    assert task.provider_task_id == "rec-9"


# ─────────────────────────── 懒同步落库映射 ───────────────────────────

@pytest.mark.asyncio
async def test_refresh_maps_success_fields(monkeypatch):
    from wechat_download.services_client import ZhilingStatus

    client = _patch_client(monkeypatch)
    client.query_asr = AsyncMock(return_value=ZhilingStatus(
        status=STATUS_SUCCESS, result_text="正文", srt_text="1\n00:00:00,000",
    ))
    t = _task(status=ZS_PROCESSING, task_type="copy_extract")
    t.provider_task_id = "t1"
    db = _FakeDB()
    await svc.refresh_service_task(db, t)
    assert t.status == ZS_SUCCESS
    assert t.result_text == "正文"
    assert t.srt_text.startswith("1")
    assert db.commits == 1


@pytest.mark.asyncio
async def test_refresh_keeps_processing_on_upstream_error(monkeypatch):
    """查询抖动不写 failed：下一次轮询大概率就好了，写死反而误伤。"""
    client = _patch_client(monkeypatch)
    client.query_eraser = AsyncMock(side_effect=ZhilingServiceError("http 502"))
    t = _task(status=ZS_PROCESSING, task_type="ai_eraser")
    t.provider_task_id = "t2"
    await svc.refresh_service_task(_FakeDB(), t)
    assert t.status == ZS_PROCESSING


@pytest.mark.asyncio
async def test_refresh_skips_terminal_task(monkeypatch):
    client = _patch_client(monkeypatch)
    t = _task(status=ZS_SUCCESS, task_type="tts")
    t.provider_task_id = "r1"
    await svc.refresh_service_task(_FakeDB(), t)
    client.query_tts.assert_not_awaited()
