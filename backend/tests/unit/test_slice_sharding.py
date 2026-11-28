"""真分片一期：切分器/校验器/准入判定/父聚合纯函数 单元测试。

docs/1128-任务内真分片-工程方案-v2评审修订版 §6 的 V1-V5/V7 与聚合状态机用例。
V6（时间窗越界）由调用方 _validate_cutlist_fits_source 对整表把关；
V8（-vN 变体后缀）为引擎运行时后缀、不出现在 cutlist，一期不适用；
V9（hook 缩放）随钩子分片二期补。T 系链路用例随扇出/前端轮次补集成测试。
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".."))

# 环境 bootstrap：settings 的必填项在 import 链上做 pydantic 校验（与同目录
# test_slice_task_serialization_fields.py 同一套引导）
import os as _os

_os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
_os.environ.setdefault("JWT_SECRET", "u" * 64)
_os.environ.setdefault("MINIO_ACCESS_KEY", "test")
_os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

import pytest

from app.api.slice_helpers import (
    SHARD_MAX_K,
    SHARD_MAX_OUTPUTS,
    compute_parent_aggregate,
    parse_cutlist_groups,
    plan_shards_if_eligible,
    split_cutlist_groups,
    validate_shard_cutlists,
)


def _cutlist(n, dur=60.0, start=600.0):
    """生成 n 个组（每组 1 行）的 cutlist 文本：非混剪模式 行=组。"""
    lines = []
    for i in range(1, n + 1):
        s = start + (i - 1) * dur
        lines.append(f"00:{int(s)//60:02d}:{int(s)%60:06.3f} 00:{int(s+dur)//60:02d}:{(s+dur)%60:06.3f} 剧名_MMDD_{i:03d}.mp4")
    return "\n".join(lines)


def _names(cutlist):
    return set(parse_cutlist_groups(cutlist).keys())


# ── V1 合法划分 ──────────────────────────────────────────────────────────
def test_v1_split_partition_is_exact():
    full = _cutlist(6)
    shards = split_cutlist_groups(full, 2)
    assert len(shards) == 2
    sets = [_names(sc) for sc in shards]
    # 不相交
    assert sets[0].isdisjoint(sets[1])
    # 并集=全集（V4）
    assert sets[0] | sets[1] == _names(full)
    validate_shard_cutlists(full, shards)  # 不抛即通过


# ── V2 组跨片撕裂拒绝 ────────────────────────────────────────────────────
def test_v2_torn_group_rejected():
    # 混剪形态：同名 2 行（一个成品两段），撕裂成两片必须拒绝
    full = "\n".join([
        "00:00:00.000 00:01:00.000 剧名_001.mp4",
        "00:02:00.000 00:03:00.000 剧名_001.mp4",
        "00:04:00.000 00:05:00.000 剧名_002.mp4",
    ])
    torn = [
        "00:00:00.000 00:01:00.000 剧名_001.mp4",
        "00:02:00.000 00:03:00.000 剧名_001.mp4\n00:04:00.000 00:05:00.000 剧名_002.mp4",
    ]
    # 正确切法（同名两行同片）不被撕裂
    split_cutlist_groups(full, 2)
    ok = split_cutlist_groups(full, 1)
    validate_shard_cutlists(full, ok)
    # 手工撕裂 → V2 拒绝
    with pytest.raises(ValueError, match="V2"):
        validate_shard_cutlists(full, torn)


# ── V3 跨片重名拒绝 ──────────────────────────────────────────────────────
def test_v3_duplicate_across_shards_rejected():
    full = _cutlist(3)
    dup = [_cutlist(2), _cutlist(2)]
    with pytest.raises(ValueError, match="V3"):
        validate_shard_cutlists(full, dup)


# ── V4 并集不完备拒绝 ────────────────────────────────────────────────────
def test_v4_missing_output_rejected():
    full = _cutlist(3)
    partial = [_cutlist(2)]
    with pytest.raises(ValueError, match="V4"):
        validate_shard_cutlists(full, partial)


# ── V5 行数守恒 + 与引擎同规则的行处理 ───────────────────────────────────
def test_v5_bad_lines_dropped_consistently():
    full = "\n".join([
        _cutlist(2),
        "这行不够 token",
        "00:99:99.000 00:00:00.000 坏时间戳行.mp4",
        "00:03:00.000 00:01:00.000 end小于start行.mp4",
        "00:03:00.000 00:04:00.000 剧名_003.mp4",
    ])
    shards = split_cutlist_groups(full, 2)
    # 坏行与引擎口径一致被丢弃：只剩 3 个好组
    assert _names(full) == {"剧名_MMDD_001", "剧名_MMDD_002", "剧名_003"}
    validate_shard_cutlists(full, shards)


# ── V7 分片数钳制 ────────────────────────────────────────────────────────
def test_v7_k_clamped_to_group_count():
    full = _cutlist(3)
    shards = split_cutlist_groups(full, 8)
    assert len(shards) == 3  # 钳到组数，不允许空分片


# ── 准入判定 plan_shards_if_eligible ─────────────────────────────────────
def _req(**kw):
    d = types.SimpleNamespace(
        target_node_id=None, no_cut=False, output_id=None,
        hook_video_key=None, hook_video_keys=None, outro_video_key=None,
        hook_mix_mode=None, dual_mix_enabled=False,
    )
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_plan_disabled_or_nonworker_returns_none():
    full = _cutlist(90)
    assert plan_shards_if_eligible(sharding_enabled=False, engine="worker", data=_req(), remotion_mix_config=None, cutlist=full) is None
    assert plan_shards_if_eligible(sharding_enabled=True, engine="celery", data=_req(), remotion_mix_config=None, cutlist=full) is None


def test_plan_excludes_phase1_features():
    full = _cutlist(90)
    base = dict(sharding_enabled=True, engine="worker", remotion_mix_config=None, cutlist=full)
    assert plan_shards_if_eligible(data=_req(target_node_id="slice-worker-1"), **base) is None
    assert plan_shards_if_eligible(data=_req(no_cut=True), **base) is None
    assert plan_shards_if_eligible(data=_req(output_id="x"), **base) is None
    assert plan_shards_if_eligible(data=_req(hook_video_keys=["h/1.mp4"]), **base) is None
    assert plan_shards_if_eligible(data=_req(outro_video_key="outro/x.mp4"), **base) is None
    assert plan_shards_if_eligible(data=_req(hook_mix_mode="random"), **base) is None
    assert plan_shards_if_eligible(data=_req(dual_mix_enabled=True), **base) is None
    assert plan_shards_if_eligible(data=_req(), remotion_mix_config={"enabled": True}, **{k: v for k, v in base.items() if k != "remotion_mix_config"}) is None


def test_plan_k_formula_and_minimum():
    base = dict(sharding_enabled=True, engine="worker", data=_req(), remotion_mix_config=None)
    # 30 组以内 → k=1 不分片
    assert plan_shards_if_eligible(cutlist=_cutlist(SHARD_MAX_OUTPUTS), **base) is None
    # 31 组 → k=2；61 组 → k=3（封顶）；超 90 组仍 k=3
    s31 = plan_shards_if_eligible(cutlist=_cutlist(31), **base)
    assert s31 and len(s31) == 2
    s61 = plan_shards_if_eligible(cutlist=_cutlist(61), **base)
    assert s61 and len(s61) == SHARD_MAX_K
    s90 = plan_shards_if_eligible(cutlist=_cutlist(90), **base)
    assert s90 and len(s90) == SHARD_MAX_K
    # 每片组数均衡：90 组/3 片 = 30/30/30
    assert [len(_names(sc)) for sc in s90] == [30, 30, 30]


# ── 父聚合纯函数（状态机口径）────────────────────────────────────────────
def _shard(status, progress=0.0, outputs=0, err=None):
    return types.SimpleNamespace(status=status, progress=progress, output_count=outputs, error_message=err)


def test_aggregate_running_when_any_non_terminal():
    agg = compute_parent_aggregate([_shard("completed", 100, 10), _shard("running", 40, 3)])
    assert agg["status"] == "running"
    assert agg["completed"] is False
    assert agg["progress"] == 70.0
    assert agg["output_count"] == 13


def test_aggregate_completed_all_done():
    agg = compute_parent_aggregate([_shard("completed", 100, 10), _shard("completed", 100, 8)])
    assert agg["status"] == "completed"
    assert agg["error_message"] is None
    assert agg["completed"] is True
    assert agg["output_count"] == 18


def test_aggregate_partial_failure_keeps_outputs():
    agg = compute_parent_aggregate([
        _shard("completed", 100, 10),
        _shard("failed", 60, 4, err="引擎失败"),
    ])
    # 口径拍板：混合→completed 保留全部成品 + partial 标注
    assert agg["status"] == "completed"
    assert agg["completed"] is True
    assert "1/2 片失败" in agg["error_message"]
    assert "产出 10 条成品" in agg["error_message"]


def test_aggregate_all_failed():
    agg = compute_parent_aggregate([
        _shard("failed", 30, 0, err="A 失败"),
        _shard("failed", 20, 0, err="B 失败"),
    ])
    assert agg["status"] == "failed"
    assert agg["completed"] is True
    assert "全部分片失败" in agg["error_message"]
    assert "A 失败" in agg["error_message"]


def test_aggregate_all_cancelled_is_cancelled():
    # 口径（docs/1128-v2 §4.3）：取消父任务把全部分片置 cancelled——父行应 cancelled
    agg = compute_parent_aggregate([_shard("cancelled"), _shard("cancelled")])
    assert agg["status"] == "cancelled"
    assert agg["completed"] is True


def test_aggregate_completed_plus_cancelled_is_partial_completed():
    agg = compute_parent_aggregate([
        _shard("completed", 100, 8),
        _shard("cancelled", 40, 0),
    ])
    assert agg["status"] == "completed"
    assert "1/2 片失败或取消" in agg["error_message"]
    assert "产出 8 条成品" in agg["error_message"]
