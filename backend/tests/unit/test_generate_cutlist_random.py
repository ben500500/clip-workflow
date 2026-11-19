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
