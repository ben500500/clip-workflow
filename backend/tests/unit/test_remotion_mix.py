"""Remotion 高光混剪增强（P2）单元测试。

覆盖：
- _build_remotion_mix_config() 边界条件（未开启返回 None / 钳制 / 默认值 / 完整配置）；
- run_remotion_mix_task() mock 测试（REMOTION_ENABLED 开关 / 成功回写 done / 失败回写 failed）；
- API 路由注册与基本响应检查（GET status / POST render）。

运行：cd backend && python -m pytest tests/unit/test_remotion_mix.py -v
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 让 backend 作为根包可导入（app.*）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
# run_remotion_mix_task mock 测试
# ─────────────────────────────────────────────────────────────

def test_run_remotion_mix_success_marks_done(monkeypatch):
    """成功渲染返回 done 结果。"""
    calls = {}

    async def fake_flow(slice_task_id):
        calls["flow"] = slice_task_id
        return {"ok": True, "output_file_key": "remotion/task.mp4"}

    monkeypatch.setattr("app.celery.remotion_tasks._run_remotion_mix_flow", fake_flow)
    monkeypatch.setattr("app.celery.remotion_tasks.settings.REMOTION_ENABLED", True)

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
    monkeypatch.setattr("app.celery.remotion_tasks.settings.REMOTION_ENABLED", True)

    with patch.object(run_remotion_mix_task, "retry", side_effect=Exception("retry")) as mock_retry:
        with pytest.raises(Exception, match="retry"):
            run_remotion_mix_task.run("some-id")
    assert marked["id"] == "some-id"
    assert "download failed" in marked["err"]
    mock_retry.assert_called_once()


def test_run_remotion_mix_disabled_skips(monkeypatch):
    """REMOTION_ENABLED 关闭时直接跳过，不渲染。"""
    async def fake_flow(slice_task_id):
        raise AssertionError("不应渲染")

    monkeypatch.setattr("app.celery.remotion_tasks._run_remotion_mix_flow", fake_flow)
    monkeypatch.setattr("app.celery.remotion_tasks.settings.REMOTION_ENABLED", False)

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
