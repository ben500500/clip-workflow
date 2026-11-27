"""切片历史 Tooltip 字段序列化单测，不访问数据库。"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.api.slice_helpers import SliceTaskResponse, _serialize_task
from app.models.models import SliceTask


TASK_FIELDS = {
    "id": uuid4(),
    "episode_id": uuid4(),
    "mode": "fast",
    "status": "completed",
    "progress": 100.0,
    "error_message": None,
    "node_id": "worker-test",
    "started_at": None,
    "completed_at": None,
    "created_at": datetime(2026, 11, 27, 12, 0, 0),
    "hook_mix_output_count": 4,
    "cutlist": None,
    "output_count": 2,
    "dedupe_config": {"enabled": True},
    "variant_count": 3,
    "source_bucket": "raw-footage",
    "source_file_key": "raw/source.mp4",
    "watermark_config": None,
    "badges_config": [{"file_key": "badges/logo.png"}],
    "badge_default_width": 80,
    "vert2horiz_config": None,
    "subtitle_config": None,
    "subtitle_align_mask": True,
    "subtitle_mask_config": None,
    "watermark_mask_config": None,
    "text_overlays_config": [{"text": "测试文字"}],
    "cover_image_key": "covers/cover.jpg",
    "output_tier": "720p",
    "hook_video_key": "hooks/legacy.mp4",
    "hook_video_keys": ["hooks/a.mp4", "hooks/b.mp4"],
    "outro_video_key": "hooks/outro.mp4",
    "hook_mix_mode": "random",
    "hook_position": "tail",
    "dual_mix_config": '{"enabled":true,"highlight_count":2,"main_count":1}',
    "remotion_mix_config": {"enabled": True, "template": "highlight"},
    "remotion_output_file_key": "remotion/mix.mp4",
    "remotion_status": "done",
}


@pytest.fixture(params=["orm", "mock"])
def task(request):
    if request.param == "orm":
        return SliceTask(**TASK_FIELDS)

    mock_task = MagicMock(spec=SliceTask)
    for field, value in TASK_FIELDS.items():
        setattr(mock_task, field, value)
    return mock_task


def test_serialize_task_preserves_history_tooltip_fields(task):
    serialized = _serialize_task(task)

    expected = {
        "variant_count": TASK_FIELDS["variant_count"],
        "cover_image_key": TASK_FIELDS["cover_image_key"],
        "hook_video_key": TASK_FIELDS["hook_video_key"],
        "hook_video_keys": TASK_FIELDS["hook_video_keys"],
        "outro_video_key": TASK_FIELDS["outro_video_key"],
        "hook_mix_mode": TASK_FIELDS["hook_mix_mode"],
        "dual_mix_config": TASK_FIELDS["dual_mix_config"],
        "source_bucket": TASK_FIELDS["source_bucket"],
        "source_file_key": TASK_FIELDS["source_file_key"],
        "output_tier": TASK_FIELDS["output_tier"],
        "hook_mix_output_count": TASK_FIELDS["hook_mix_output_count"],
        "hook_position": TASK_FIELDS["hook_position"],
        "remotion_mix_config": TASK_FIELDS["remotion_mix_config"],
        "remotion_output_file_key": TASK_FIELDS["remotion_output_file_key"],
        "remotion_status": TASK_FIELDS["remotion_status"],
    }
    for field, value in expected.items():
        assert serialized[field] == value

    # dual_mix_config 必须原样穿过 Pydantic，不能在服务端提前 parse。
    assert isinstance(serialized["dual_mix_config"], str)
    response = SliceTaskResponse.model_validate(serialized)
    assert response.dual_mix_config == TASK_FIELDS["dual_mix_config"]
    assert response.hook_video_keys == TASK_FIELDS["hook_video_keys"]
    assert response.outro_video_key == TASK_FIELDS["outro_video_key"]
    assert response.variant_count == TASK_FIELDS["variant_count"]
    assert response.cover_image_key == TASK_FIELDS["cover_image_key"]
    assert response.source_file_key == TASK_FIELDS["source_file_key"]
    assert response.outputs_total == TASK_FIELDS["hook_mix_output_count"]
