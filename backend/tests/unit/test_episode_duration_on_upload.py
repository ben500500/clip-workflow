"""上传建剧集必须把 ffprobe 已探到的时长落库（剧集列表「时长没有显示出来」的根因）。

现象：剧集列表时长列全是 `-`。生产库实测 73 条 episodes 只有 24 条有 duration，
且 24 条全来自 API 直建（显式传 duration）；真实上传的项目 0 覆盖。
根因不在前端显示，而在服务端：`upload.py` 三处建剧集入口本来就调用
`probe_media()` 取了 width/height/fps，却把同一个返回值里的 `duration` 丢掉了；
`batch_slice_service._upload_and_create_episode` 则完全没探测。

本用例钉住「探测到的 duration 必须落到 Episode.duration」这条链路，
不连数据库、不碰 MinIO。
"""

import os
import sys
import uuid
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_episode_duration.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.services import batch_slice_service

PROBE = {"width": 1080, "height": 1920, "fps": 30.0, "duration": 123.456}


def _fake_session(captured):
    """async_session_factory() → 异步上下文管理器，add() 把对象交给断言。"""

    class _S:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def add(self, obj):
            captured.append(obj)

        async def commit(self):
            pass

        async def flush(self):
            pass

        async def refresh(self, obj):
            obj.id = uuid.uuid4()

    return lambda: _S()


def test_batch_upload_records_probed_duration(tmp_path):
    src = tmp_path / "第1集.mp4"
    src.write_bytes(b"\x00" * 64)
    item = SimpleNamespace(
        source_path=str(src), batch_id=uuid.uuid4(), seq=1, title="第1集"
    )
    captured = []

    with patch("app.services.minio_service.ensure_bucket", new=AsyncMock(return_value=True)), \
         patch("app.services.minio_service.upload_file_from_path", new=AsyncMock(return_value=True)), \
         patch("app.utils.source_media.probe_media", return_value=PROBE), \
         patch.object(batch_slice_service, "async_session_factory", _fake_session(captured)):
        episode_id = asyncio.run(
            batch_slice_service._upload_and_create_episode(item, uuid.uuid4())
        )

    assert episode_id
    episode = captured[0]
    # 核心断言：duration 不能再被丢掉
    assert episode.duration == 123.456
    assert episode.fps == 30.0
    assert episode.resolution == "1080x1920"
    assert episode.status == "uploaded"


def test_batch_upload_survives_probe_failure(tmp_path):
    """探测失败（返回 None）不得阻断建剧集，duration 留空即可。"""
    src = tmp_path / "坏文件.mp4"
    src.write_bytes(b"\x00" * 8)
    item = SimpleNamespace(source_path=str(src), batch_id=uuid.uuid4(), seq=2, title="坏文件")
    captured = []

    with patch("app.services.minio_service.ensure_bucket", new=AsyncMock(return_value=True)), \
         patch("app.services.minio_service.upload_file_from_path", new=AsyncMock(return_value=True)), \
         patch("app.utils.source_media.probe_media", return_value=None), \
         patch.object(batch_slice_service, "async_session_factory", _fake_session(captured)):
        episode_id = asyncio.run(
            batch_slice_service._upload_and_create_episode(item, uuid.uuid4())
        )

    assert episode_id
    assert captured[0].duration is None


def test_upload_sources_always_store_duration():
    """静态守卫：所有服务端建剧集入口必须落 duration（构造参数或后续赋值）。

    用 ast 解析而不是正则，避免缩进/换行变化造成假红。规则：
    · 每个 `Episode(...)` 构造调用所在函数体内，要么构造参数含 `duration=`，
      要么有 `<某变量>.duration = ...` 的赋值；
    · 命中不了就是又有人只取分辨率帧率、把同一个 probe 返回值里的 duration 丢掉。
    """
    import ast
    import inspect

    from app.api import upload as upload_api
    from app.services import batch_slice_service as bss

    for module in (upload_api, bss):
        tree = ast.parse(inspect.getsource(module))
        offenders = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "Episode"
            ]
            if not calls:
                continue
            kwargs = {kw.arg for c in calls for kw in c.keywords if kw.arg}
            assigns_duration = any(
                isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Attribute)
                and n.targets[0].attr == "duration"
                for n in ast.walk(fn)
            )
            if "duration" not in kwargs and not assigns_duration:
                offenders.append(f"{module.__name__}.{fn.name}")
        assert not offenders, f"以下建剧集入口没有落 duration: {offenders}"

