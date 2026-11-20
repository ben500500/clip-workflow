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
from app.utils.helpers import generate_cutlist


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
