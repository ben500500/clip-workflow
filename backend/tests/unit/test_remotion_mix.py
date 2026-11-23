"""Remotion 高光混剪增强（P2）单元测试。

覆盖：
- _build_remotion_mix_config() 边界条件（未开启返回 None / 钳制 / 默认值 / 完整配置）；
- run_remotion_mix_task() mock 测试（REMOTION_ENABLED 开关 / 成功回写 done / 失败回写 failed）；
- API 路由注册与基本响应检查（GET status / POST render）。

运行：cd backend && python -m pytest tests/unit/test_remotion_mix.py -v
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 让 backend 作为根包可导入（app.*）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

def _enable_remotion(monkeypatch, enabled: bool):
    """patch 实体开关查询（system_configs 驱动，2026-11-20 起）。"""
    async def fake(db):
        return enabled
    monkeypatch.setattr("app.services.remotion_renderer.is_remotion_enabled", fake)

from app.api import slice_helpers
from app.api.slice_helpers import SliceRunRequest, _build_remotion_mix_config
from app.celery.remotion_tasks import run_remotion_mix_task
from app.api import remotion as remotion_api


# ─────────────────────────────────────────────────────────────
# _build_remotion_mix_config 边界条件
# ─────────────────────────────────────────────────────────────

def _req(**overrides):
    base = dict(
        mode="fast",
        remotion_mix_enabled=False,
        remotion_template="highlight",
        remotion_transition_frames=None,
        remotion_intro=None,
        remotion_outro=None,
        remotion_subtitle_style=None,
        remotion_output_tier=None,
    )
    base.update(overrides)
    return SliceRunRequest(**base)


def test_config_disabled_returns_none():
    """未开启 remotion_mix_enabled 时返回 None（零侵入基础混剪）。"""
    assert _build_remotion_mix_config(_req(remotion_mix_enabled=False)) is None


def test_config_enabled_defaults():
    """开启后返回基础 config，缺省字段收敛为合理默认。"""
    cfg = _build_remotion_mix_config(_req(remotion_mix_enabled=True))
    assert cfg is not None
    assert cfg["enabled"] is True
    assert cfg["template"] == "highlight"
    assert cfg["transition_frames"] == 12  # 默认 12
    assert cfg["output_tier"] == "720p"  # 默认 720p


def test_config_negative_transition_frames_clamped():
    """负转场帧数钳制为 0。"""
    cfg = _build_remotion_mix_config(
        _req(remotion_mix_enabled=True, remotion_transition_frames=-5)
    )
    assert cfg["transition_frames"] == 0


def test_config_invalid_tier_falls_back_720p():
    """非法 output_tier 回退 720p。"""
    cfg = _build_remotion_mix_config(
        _req(remotion_mix_enabled=True, remotion_output_tier="8k")
    )
    assert cfg["output_tier"] == "720p"
    cfg2 = _build_remotion_mix_config(
        _req(remotion_mix_enabled=True, remotion_output_tier="1080p")
    )
    assert cfg2["output_tier"] == "1080p"


def test_config_full_intro_outro_subtitle():
    """完整配置：intro/outro/subtitle_style 全部透传。"""
    cfg = _build_remotion_mix_config(
        _req(
            remotion_mix_enabled=True,
            remotion_intro={"title": "高光混剪", "episode": "第1集", "cover_file_key": "c/1.jpg"},
            remotion_outro={"text": "关注我们"},
            remotion_subtitle_style={"fontRatio": 0.2, "color": "#FFFFFF"},
            remotion_output_tier="1080p",
        )
    )
    assert cfg["intro"] == {"title": "高光混剪", "episode": "第1集", "cover_file_key": "c/1.jpg"}
    assert cfg["outro"] == {"text": "关注我们"}
    assert cfg["subtitle_style"] == {"fontRatio": 0.2, "color": "#FFFFFF"}
    assert cfg["output_tier"] == "1080p"


def test_config_skips_empty_intro_outro():
    """空片头/片尾字段不输出到 config。"""
    cfg = _build_remotion_mix_config(
        _req(
            remotion_mix_enabled=True,
            remotion_intro={"title": "", "episode": ""},
            remotion_outro={"text": ""},
        )
    )
    assert "intro" not in cfg
    assert "outro" not in cfg


def test_config_font_ratio_clamped():
    """fontRatio 边界钳制到 [0.05, 0.5]。"""
    cfg = _build_remotion_mix_config(
        _req(remotion_mix_enabled=True, remotion_subtitle_style={"fontRatio": 99.0})
    )
    assert cfg["subtitle_style"]["fontRatio"] == 0.5


# ─────────────────────────────────────────────────────────────
# 片头片尾自定义（2026-11-20）：时长钳制 / 背景色 / 封面开关 / 默认不配置
# ─────────────────────────────────────────────────────────────

def test_intro_outro_custom_duration_and_background():
    """片头片尾自定义时长（钳制）与背景色透传。"""
    cfg = _build_remotion_mix_config(
        _req(
            remotion_mix_enabled=True,
            remotion_intro={"title": "T", "duration_seconds": 99, "background": "#101010"},
            remotion_outro={"text": "END", "duration_seconds": 1, "subtitle": "关注我"},
        )
    )
    assert cfg["intro"]["duration_seconds"] == 6.0, "片头时长钳制上限 6s"
    assert cfg["intro"]["background"] == "#101010"
    assert cfg["outro"]["duration_seconds"] == 2.0, "片尾时长钳制下限 2s"
    assert cfg["outro"]["subtitle"] == "关注我"


def test_no_intro_outro_by_default():
    """片头片尾默认不配置：config 不含 intro/outro → 渲染直接进入正片。"""
    cfg = _build_remotion_mix_config(_req(remotion_mix_enabled=True))
    assert "intro" not in cfg and "outro" not in cfg


def test_build_props_maps_intro_outro_to_contract():
    """renderer 把 snake 配置映射为前端契约（durationSeconds 驼峰）。"""
    from app.services.remotion_renderer import _build_props

    cfg = {
        "enabled": True,
        "template": "highlight",
        "transition_frames": 12,
        "output_tier": "720p",
        "intro": {"title": "T", "duration_seconds": 4.0, "background": "#101010", "cover_name": "cover_1.jpg"},
        "outro": {"text": "END", "subtitle": "关注", "duration_seconds": 3.0},
    }
    props = _build_props([{"start": 1.0, "end": 5.0}], cfg, "source.mp4")
    assert props["intro"]["durationSeconds"] == 4.0
    assert props["intro"]["cover"] == "cover_1.jpg"
    assert "duration_seconds" not in props["intro"]
    assert props["outro"]["durationSeconds"] == 3.0
    assert props["outro"]["subtitle"] == "关注"
    # 帧数估算与组件 computeMixLayout 一致：片头 4s×30 + 段 4s×30 + 片尾 3s×30 = 330
    assert props["durationInFrames"] == (4 + 4 + 3) * 30


# ─────────────────────────────────────────────────────────────
# run_remotion_mix_task mock 测试
# ─────────────────────────────────────────────────────────────

def test_run_remotion_mix_success_marks_done(monkeypatch):
    """成功渲染返回 done 结果。"""
    calls = {}

    async def fake_flow(slice_task_id):
        calls["flow"] = slice_task_id
        return {"ok": True, "output_file_key": "remotion/task.mp4"}

    monkeypatch.setattr("app.celery.remotion_tasks._run_remotion_mix_flow", fake_flow)
    _enable_remotion(monkeypatch, True)

    res = run_remotion_mix_task.run("some-id")
    assert res["ok"] is True
    assert res["output_file_key"] == "remotion/task.mp4"
    assert calls["flow"] == "some-id"


def test_run_remotion_mix_failure_retries(monkeypatch):
    """渲染失败回写 failed 并触发 retry。"""
    async def fake_flow(slice_task_id):
        return {"ok": False, "error": "download failed"}

    marked = {}

    async def fake_mark(slice_task_id, error):
        marked["id"], marked["err"] = slice_task_id, error

    monkeypatch.setattr("app.celery.remotion_tasks._run_remotion_mix_flow", fake_flow)
    monkeypatch.setattr("app.celery.remotion_tasks._mark_remotion_failed", fake_mark)
    _enable_remotion(monkeypatch, True)

    with patch.object(run_remotion_mix_task, "retry", side_effect=Exception("retry")) as mock_retry:
        with pytest.raises(Exception, match="retry"):
            run_remotion_mix_task.run("some-id")
    assert marked["id"] == "some-id"
    assert "download failed" in marked["err"]
    mock_retry.assert_called_once()


def test_run_remotion_mix_disabled_skips(monkeypatch):
    """REMOTION_ENABLED 关闭时直接跳过，不渲染。

    2026-11-23（S0'）：11-23 的"专项评审修正"给关闸分支加了"把 processing 的
    slice_task 置 failed"（静默返回会让任务永久卡死），于是本用例会走到真库
    ——本文件第 21 行把 DATABASE_URL 指到假 PG，一跑就是 InvalidPassword。
    单测不该连库：用假 session 让那条查询返回空（task=None），只验控制流
    "开关关了就 skipped、不渲染"。
    """
    async def fake_flow(slice_task_id):
        raise AssertionError("不应渲染")

    monkeypatch.setattr("app.celery.remotion_tasks._run_remotion_mix_flow", fake_flow)
    _enable_remotion(monkeypatch, False)

    class _FakeResult:
        def scalar_one_or_none(self):
            return None

    class _FakeSession:
        async def execute(self, *_a, **_k):
            return _FakeResult()

        async def commit(self):  # noqa: D401 —— 空实现，仅满足协议
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    # 注意靶点：任务体在**函数内** `from app.database import async_session_factory`，
    # 拿到的是 closure 里的局部名；patch remotion_tasks 的模块属性打不中它，
    # 必须 patch **来源模块** app.database。
    monkeypatch.setattr("app.database.async_session_factory", lambda: _FakeSession())

    res = run_remotion_mix_task.run("some-id")
    assert res.get("skipped") is True


# ─────────────────────────────────────────────────────────────
# API 路由基本检查
# ─────────────────────────────────────────────────────────────

def test_remotion_api_routes_registered():
    """remotion router 注册了 status 与 render 两个路由。"""
    paths = [r.path for r in remotion_api.router.routes]
    assert "/v1/remotion/status/{slice_task_id}" in paths
    assert "/v1/remotion/render/{slice_task_id}" in paths


def test_remotion_api_uses_protected_prefix_in_main():
    """main.py 将 remotion 挂到 protected routers（prefix=/api，需鉴权）。"""
    # 读取 main.py 源码，断言 remotion 被 import 且加入 protected routers（避免重依赖导入阻塞）
    main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
    src = main_py.read_text(encoding="utf-8")
    assert "remotion" in src
    assert "_protected_routers" in src
    # 确认 remotion 加入受保护路由列表（前缀 /api + 鉴权）
    assert "remotion,\n" in src or "remotion," in src


def test_remotion_status_response_model_fields():
    """status 响应模型包含渲染状态字段。"""
    fields = remotion_api.RemotionStatusResponse.model_fields
    assert "remotion_status" in fields
    assert "remotion_output_file_key" in fields
    assert "remotion_enabled" in fields
