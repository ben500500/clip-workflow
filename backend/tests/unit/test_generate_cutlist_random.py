"""generate_cutlist 高光混剪（含 random 随机抽取模式）单测。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

import random
from unittest.mock import patch

from app.models.material import ClipCandidate
from app.utils.helpers import generate_cutlist, map_cutlist_output_clip_ids, strip_output_extension


def _sec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _mk(i, start, end, score=80.0, status="accepted"):
    return ClipCandidate(
        id=None, episode_id=None, clip_index=i, start_time=start, end_time=end,
        duration=end - start, title=f"clip{i}", score=score, status=status,
    )


def _total(cutlist: str) -> float:
    total = 0.0
    for line in cutlist.splitlines():
        s, e, _ = line.split()
        total += _sec(e) - _sec(s)
    return total


def _lines(cutlist: str):
    return cutlist.splitlines()


def test_random_respects_total_duration_and_uses_original_segments():
    clips = [_mk(i, i * 100, i * 100 + 20) for i in range(10)]  # 10 段各 20s
    cut = generate_cutlist(clips, episode_title="t", highlight_mix=True,
                           max_duration=60.0, order="random")
    assert cut, "随机抽取应产出非空 cutlist"
    total = _total(cut)
    assert total <= 60.0 + 1e-6, f"累计时长 {total} 超过上限 60"
    assert total >= 40.0, f"贪心凑近上限后总时长 {total} 过小"
    # 每行段都来自原候选（时间轴未被篡改）
    orig = {(c.start_time, c.end_time) for c in clips}
    for line in _lines(cut):
        s, e, _ = line.split()
        assert (_sec(s), _sec(e)) in orig


def test_random_is_nondeterministic_across_runs():
    clips = [_mk(i, i * 100, i * 100 + 30) for i in range(12)]  # 12 段各 30s，上限 60
    outs = set()
    for _ in range(12):
        outs.add(generate_cutlist(clips, episode_title="t", highlight_mix=True,
                                  max_duration=60.0, order="random"))
    assert len(outs) > 1, "多次随机抽取应产生不同组合"


def test_random_without_max_duration_keeps_all_segments():
    clips = [_mk(i, i * 100, i * 100 + 10) for i in range(8)]
    cut = generate_cutlist(clips, episode_title="t", highlight_mix=True,
                           order="random")  # 无总时长上限
    assert len(_lines(cut)) == 8, "无上限时随机模式应全部纳入"


def test_time_order_regression_unchanged():
    clips = [_mk(i, i * 100, i * 100 + 20, score=90 - i) for i in range(5)]
    cut = generate_cutlist(clips, episode_title="t", highlight_mix=True,
                           max_duration=200.0, order="time")
    starts = [_sec(line.split()[0]) for line in _lines(cut)]
    assert starts == sorted(starts), "time 模式应保持源时间升序"
    assert len(_lines(cut)) == 5


def test_single_clip_over_limit_gets_trimmed_in_random_mode():
    clips = [_mk(0, 0, 90, score=95), _mk(1, 200, 210, score=70)]  # 一段 90s 一段 10s
    cut = generate_cutlist(clips, episode_title="t", highlight_mix=True,
                           max_duration=50.0, max_clip_duration=45.0, order="random")
    total = _total(cut)
    assert total <= 50.0 + 1e-6
    assert cut, "超长段裁剪后应至少保留一段"


def test_multi_output_splits_into_n_files_without_max_duration():
    clips = [_mk(i, i * 100, i * 100 + 20) for i in range(5)]  # 5 段各 20s
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           mix_output_count=3, order="time")
    names = [line.split()[2] for line in _lines(cut)]
    distinct = sorted(set(names))
    assert len(distinct) == 3, f"应产出 3 个不同文件名，实际 {distinct}"
    counts = [names.count(n) for n in distinct]
    assert sorted(counts, reverse=True) == [2, 2, 1], f"按段数均分应为 2/2/1，实际 {counts}"


def test_multi_output_respects_per_file_duration():
    clips = [_mk(i, i * 100, i * 100 + 30) for i in range(10)]  # 10 段各 30s
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           max_duration=60.0, mix_output_count=4, order="time")
    names = [line.split()[2] for line in _lines(cut)]
    distinct = sorted(set(names))
    assert len(distinct) == 4, f"应产出 4 个文件，实际 {len(distinct)}"
    # 每文件累计 ≤ 60s（每文件 2 段 × 30s）
    for n in distinct:
        t = sum(_sec(l.split()[1]) - _sec(l.split()[0]) for l in _lines(cut) if l.split()[2] == n)
        assert t <= 60.0 + 1e-6, f"文件 {n} 累计 {t}s 超过 60s"
    assert len(_lines(cut)) == 8, "4 个文件 × 每文件 2 段 = 8 段，剩余 2 段丢弃"


def test_multi_output_random_nondeterministic_grouping():
    clips = [_mk(i, i * 100, i * 100 + 20) for i in range(9)]
    outs = set()
    for _ in range(10):
        cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                               max_duration=60.0, mix_output_count=3, order="random")
        outs.add(tuple(_lines(cut)))
    assert len(outs) > 1, "随机模式多次切片的文件内容组合应不同"


def test_single_output_regression_matches_legacy():
    clips = [_mk(i, i * 100, i * 100 + 20) for i in range(5)]
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           max_duration=60.0, order="time", mix_output_count=1)
    names = {line.split()[2] for line in _lines(cut)}
    assert len(names) == 1, "output_count=1 应保持单文件行为"
    assert len(_lines(cut)) == 3, "60s 上限 × 20s 段应纳入 3 段"


# ─────────────────────────────────────────────────────────────
# random + 输出个数：素材复用凑满 N 个（2026-11-20 业务规则：
# 输出个数是硬指标，素材可跨文件复用，只要组合顺序不同）
# ─────────────────────────────────────────────────────────────

def test_multi_output_random_fills_exact_n_by_reusing_segments():
    """素材总时长不足 N×上限时，random 模式复用素材凑满 N 个文件。

    场景还原：52 段 × 9.3s ≈ 485s，上限 60s，顺序填充只能出 9 个；
    业务要求必须出满 20 个。
    """
    clips = [_mk(i, i * 100, i * 100 + 9.3) for i in range(52)]
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           max_duration=60.0, mix_output_count=20, order="random")
    names = [l.split()[2] for l in _lines(cut)]
    distinct = sorted(set(names))
    assert len(distinct) == 20, f"必须凑满 20 个文件，实际 {len(distinct)}"
    for n in distinct:
        t = sum(_sec(l.split()[1]) - _sec(l.split()[0]) for l in _lines(cut) if l.split()[2] == n)
        assert t <= 60.0 + 1e-6, f"文件 {n} 累计 {t}s 超过上限 60s"
        assert t >= 45.0, f"文件 {n} 累计 {t}s 远低于上限，凑近逻辑失效"


def test_multi_output_random_groups_have_different_sequences():
    """各文件的段组合序列互不相同（素材可复用，但不能按相同顺序使用）。"""
    clips = [_mk(i, i * 100, i * 100 + 30) for i in range(6)]  # 池 180s < 5×60s
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           max_duration=60.0, mix_output_count=5, order="random")
    names = {l.split()[2] for l in _lines(cut)}
    assert len(names) == 5, f"应凑满 5 个文件，实际 {len(names)}"
    sigs = {
        tuple(l.split()[0] for l in _lines(cut) if l.split()[2] == n)
        for n in names
    }
    assert len(sigs) == len(names), "各文件的段组合序列应互不相同"


def test_multi_output_random_no_duplicate_segment_within_a_file():
    """单个文件内同一段不应重复使用。"""
    clips = [_mk(i, i * 100, i * 100 + 30) for i in range(6)]
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           max_duration=60.0, mix_output_count=5, order="random")
    for n in {l.split()[2] for l in _lines(cut)}:
        starts = [l.split()[0] for l in _lines(cut) if l.split()[2] == n]
        assert len(starts) == len(set(starts)), f"文件 {n} 内存在重复使用的段"


def test_multi_output_time_mode_still_stops_when_pool_exhausted():
    """time/score 顺序模式语义不变：素材用完即止，不凑满（只有 random 复用素材）。"""
    clips = [_mk(i, i * 100, i * 100 + 30) for i in range(6)]  # 池 180s
    cut = generate_cutlist(clips, episode_title="剧名", highlight_mix=True,
                           max_duration=60.0, mix_output_count=5, order="time")
    names = {l.split()[2] for l in _lines(cut)}
    assert len(names) == 3, "time 模式素材耗尽应只出 3 个文件（180s ÷ 60s），不凑满"


def test_cutlist_mapping_uses_content_not_candidate_order():
    import uuid

    clips = [_mk(i, i * 100, i * 100 + 20) for i in range(6)]
    ids = [uuid.uuid4() for _ in clips]
    for clip, clip_id in zip(clips, ids):
        clip.id = clip_id
    cutlist = (
        "00:03:20.000 00:03:40.000 剧名_1127_001\n"
        "00:00:00.000 00:00:20.000 剧名_1127_002\n"
        "00:08:20.000 00:08:40.000 剧名_1127_003\n"
    )
    mapped = map_cutlist_output_clip_ids(cutlist, list(reversed(clips)))
    assert mapped == {
        "剧名_1127_001": ids[2],
        "剧名_1127_002": ids[0],
        "剧名_1127_003": ids[5],
    }


def test_cutlist_mapping_supports_trimmed_and_variant_outputs():
    import uuid

    clip = _mk(0, 10, 40)
    clip.id = uuid.uuid4()
    mapped = map_cutlist_output_clip_ids(
        "00:00:10.000 00:00:30.000 t_001\n", [clip]
    )
    assert mapped == {"t_001": clip.id}
    mapped = map_cutlist_output_clip_ids(
        "00:00:10.000 00:00:30.000 t_001-v2.mp4\n", [clip]
    )
    assert mapped == {"t_001-v2": clip.id, "t_001": clip.id}
    frozen = map_cutlist_output_clip_ids(
        "00:00:10.000 00:00:30.000 t_001-v2.mp4\n", [clip],
        allow_variant_suffix=False,
    )
    assert frozen == {"t_001-v2": clip.id}


def test_cutlist_mapping_refuses_mixed_or_ambiguous_outputs():
    import uuid

    clips = [_mk(0, 0, 20), _mk(1, 0, 20), _mk(2, 100, 120), _mk(3, 200, 220)]
    for clip in clips:
        clip.id = uuid.uuid4()
    mapped = map_cutlist_output_clip_ids(
        "00:00:00.000 00:00:20.000 ambiguous\n"
        "00:01:40.000 00:02:00.000 mixed\n"
        "00:03:20.000 00:03:40.000 mixed\n"
        "00:05:00.000 00:05:20.000 missing\n",
        clips,
    )
    assert mapped == {
        "ambiguous": None,
        "mixed": None,
        "missing": None,
    }


def test_cutlist_mapping_preserves_dots_in_episode_titles():
    import uuid

    clip = _mk(0, 10, 40)
    clip.id = uuid.uuid4()
    name = "S01.E02_1127_001"
    assert strip_output_extension(name) == name
    assert strip_output_extension(f"{name}.mp4") == name
    assert strip_output_extension(f"{name}.MP4") == name
    for cutlist_name in (name, f"{name}.mp4"):
        assert map_cutlist_output_clip_ids(
            f"00:00:10.000 00:00:30.000 {cutlist_name}\n", [clip]
        ) == {name: clip.id}


def test_cutlist_mapping_uses_adjusted_timeline():
    import uuid

    clip = _mk(0, 10, 20)
    clip.id = uuid.uuid4()
    clip.adjusted_start = 30.0
    clip.adjusted_end = 45.0
    mapped = map_cutlist_output_clip_ids(
        "00:00:30.000 00:00:45.000 adjusted\n", [clip]
    )
    assert mapped == {"adjusted": clip.id}


def test_snapshot_candidates_apply_the_same_score_gate_as_cutlist():
    from types import SimpleNamespace
    from app.api.slice_helpers import snapshot_candidate_clips

    low = SimpleNamespace(id="low", score=4.0)
    high = SimpleNamespace(id="high", score=8.0)
    unscored = SimpleNamespace(id="unscored", score=None)
    clips = [low, high, unscored]

    assert snapshot_candidate_clips(clips, True, 7.0) == [high]
    assert snapshot_candidate_clips(clips, True, None) == clips
    assert snapshot_candidate_clips(clips, False, 7.0) == clips


# ─────────────────────────────────────────────────────────────
# _build_props 画布方向（短剧竖屏源 → 画布 9:16）
# ─────────────────────────────────────────────────────────────

def test_build_props_portrait_canvas():
    from app.services.remotion_renderer import _build_props

    segs = [{"start": 1.0, "end": 10.0}]
    cfg = {"enabled": True, "template": "highlight", "transition_frames": 12, "output_tier": "720p"}
    props = _build_props(segs, cfg, "source.mp4", portrait=True)
    assert (props["width"], props["height"]) == (720, 1280), "竖屏源 720p 档画布应为 720x1280"

    cfg1080 = dict(cfg, output_tier="1080p")
    props = _build_props(segs, cfg1080, "source.mp4", portrait=True)
    assert (props["width"], props["height"]) == (1080, 1920), "竖屏源 1080p 档画布应为 1080x1920"


def test_build_props_landscape_canvas_default():
    from app.services.remotion_renderer import _build_props

    segs = [{"start": 1.0, "end": 10.0}]
    cfg = {"enabled": True, "template": "highlight", "transition_frames": 12, "output_tier": "720p"}
    props = _build_props(segs, cfg, "source.mp4", portrait=False)
    assert (props["width"], props["height"]) == (1280, 720), "横屏源默认画布保持 1280x720"
    # trim 帧换算在 Segment 组件内完成，props 只透传秒
    assert props["segments"][0]["start"] == 1.0 and props["segments"][0]["end"] == 10.0
