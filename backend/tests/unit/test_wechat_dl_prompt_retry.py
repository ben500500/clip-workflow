"""反推提示词失败任务一键重试端点测试（POST /wechat-dl/reverse-prompt/{id}/retry）。

直接调用端点协程 + monkeypatch 服务函数，不建 FastAPI 应用、不落库。覆盖：
1. failed 链接任务 → 复制原 source_url/max_duration 新建任务并返回；
2. 非 failed 任务 → 400；
3. failed 上传任务 → 400（原始文件已清理，需重新上传）；
4. 不存在/无权限 → 404。

运行：cd backend && python -m pytest tests/unit/test_wechat_dl_prompt_retry.py -v
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# app.config 是模块级单例，导入即校验必填项 —— 必须在 import 业务模块前置好测试 env
# （与 test_wechat_dl_upload.py / test_board_metrics_import.py 同一模式）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_prompt_retry.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from wechat_download import api as api_mod
from wechat_download.models import PT_FAILED, PT_SUCCESS


def _task(status=PT_FAILED, source_type="url", source_url="https://weixin.qq.com/sph/abc",
          max_duration=300):
    t = type("T", (), {})()
    t.id = uuid.uuid4()
    t.status = status
    t.source_type = source_type
    t.source_url = source_url
    t.max_duration = max_duration
    return t


def _user():
    u = type("U", (), {})()
    u.id = uuid.uuid4()
    return u


@pytest.mark.asyncio
async def test_retry_failed_url_task_creates_new(monkeypatch):
    old = _task()
    new = _task(status="processing")
    new.source_url = old.source_url

    monkeypatch.setattr(api_mod, "get_prompt_task", AsyncMock(return_value=old))
    monkeypatch.setattr(api_mod, "can_access_prompt_task", lambda task, user: True)
    create_mock = AsyncMock(return_value=new)
    monkeypatch.setattr(api_mod, "create_prompt_task", create_mock)
    monkeypatch.setattr(api_mod, "serialize_prompt_task", lambda t: t)

    user = _user()
    result = await api_mod.retry_reverse_prompt_task(old.id, current_user=user, db=AsyncMock())

    assert result is new
    create_mock.assert_awaited_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["source_url"] == old.source_url
    assert kwargs["max_duration"] == old.max_duration
    assert kwargs["created_by"] == user.id


@pytest.mark.asyncio
async def test_retry_rejects_non_failed_task(monkeypatch):
    monkeypatch.setattr(api_mod, "get_prompt_task", AsyncMock(return_value=_task(status=PT_SUCCESS)))
    monkeypatch.setattr(api_mod, "can_access_prompt_task", lambda task, user: True)
    with pytest.raises(HTTPException) as ei:
        await api_mod.retry_reverse_prompt_task(uuid.uuid4(), current_user=_user(), db=AsyncMock())
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_retry_rejects_upload_task(monkeypatch):
    monkeypatch.setattr(api_mod, "get_prompt_task",
                        AsyncMock(return_value=_task(source_type="upload")))
    monkeypatch.setattr(api_mod, "can_access_prompt_task", lambda task, user: True)
    with pytest.raises(HTTPException) as ei:
        await api_mod.retry_reverse_prompt_task(uuid.uuid4(), current_user=_user(), db=AsyncMock())
    assert ei.value.status_code == 400
    assert "重新上传" in ei.value.detail


@pytest.mark.asyncio
async def test_retry_404_when_missing_or_denied(monkeypatch):
    monkeypatch.setattr(api_mod, "get_prompt_task", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as ei:
        await api_mod.retry_reverse_prompt_task(uuid.uuid4(), current_user=_user(), db=AsyncMock())
    assert ei.value.status_code == 404

    monkeypatch.setattr(api_mod, "get_prompt_task", AsyncMock(return_value=_task()))
    monkeypatch.setattr(api_mod, "can_access_prompt_task", lambda task, user: False)
    with pytest.raises(HTTPException) as ei2:
        await api_mod.retry_reverse_prompt_task(uuid.uuid4(), current_user=_user(), db=AsyncMock())
    assert ei2.value.status_code == 404
