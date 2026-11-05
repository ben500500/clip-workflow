"""抽帧服务单测（11-04 批 F：审核台卡片图的取帧/拼图/跳过口径）。

钉住五件真会坏的事：
1. **不取 t=0**：短片第一帧常常是黑帧或台标，卡片上一片黑会被一线当成"抽帧坏了"；
2. **时长未知就不抽**：连时间轴都没有，百分比和等间隔都算不出来，硬抽＝随机抽一帧骗人；
3. **超长原片跳过**（整集片会把 worker 钉在 ffmpeg 上），且跳过是 `skipped` 不是 `failed`；
4. **抽帧不许抛异常**：一条坏文件不该把整批导入的抽帧一起带崩，失败只回原因；
5. **0 字节文件不算抽成功**（素材库真踩过：桶里躺 0 字节对象照样回 200）。

最后一段是**真跑 ffmpeg** 的回归（装了才跑，没装就 skip）：造一条 3 秒测试片，
抽完断言 3 张单帧 + 1 张九宫格都落地、是 JPEG、尺寸对得上配置。
"""

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

# `asset_frame_service` 取值走 `settings`，而 Settings 的 DATABASE_URL/JWT_SECRET 是必填
# （本目录没有 conftest 兜这些），所以导入前先把测试用的环境变量钉住——
# 和 tests/integration/test_asset_library_api.py 同一套做法，只是这里**一个连接都不发**
# （URL 只在 `app.database` 建引擎时解析，sqlite 那种会连带校验池参数，故给个 pg 假地址）。
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:59999/frames_unit")
os.environ.setdefault("JWT_SECRET", "t" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.models.asset import FRAME_GRID, FRAME_THUMB  # noqa: E402
from app.services import asset_frame_service as f  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# ───────────────────  时间点：不许取首帧，也不许取到片尾外  ───────────────────

def test_plan_offsets_skips_the_black_first_frame():
    offsets = f.plan_offsets(10.0)
    assert offsets == [1.0, 4.5, 8.0]
    assert 0.0 not in offsets, "t=0 那帧多半是黑帧/台标，卡片上一片黑会被当成抽帧坏了"
    assert all(0 < t < 10.0 for t in offsets), offsets


def test_plan_offsets_clamps_inside_the_clip():
    # 2.1s 的片子按 80% 算是 1.68s，不会因为四舍五入跑到 2.1s 之外
    for t in f.plan_offsets(2.1, count=5):
        assert 0.05 <= t <= 2.05, t
    assert len(f.plan_offsets(2.1, count=5)) == 5


def test_plan_offsets_gives_one_mid_frame_for_a_micro_clip():
    # 不到 2 秒抽三张就是同一帧复制三遍，直接给一张中段
    assert f.plan_offsets(1.2) == [0.6]


def test_plan_offsets_returns_empty_for_a_bad_duration():
    for bad in (0, -3.0):
        assert f.plan_offsets(bad) == [], bad


def test_plan_offsets_falls_back_to_config_count():
    assert len(f.plan_offsets(30.0)) == int(settings.ASSET_FRAME_THUMB_COUNT)


# ───────────────────  九宫格：间隔与拼图命令  ───────────────────

def test_grid_interval_is_duration_over_tiles():
    assert f.grid_interval(9.0, 9) == 1.0
    assert f.grid_interval(0) == 0.0
    assert f.grid_interval(10.0) == round(10.0 / int(settings.ASSET_FRAME_GRID_TILES), 3)


def test_thumb_cmd_seeks_before_input_and_caps_to_one_frame():
    cmd = f.build_thumb_cmd("/tmp/src.mp4", 4.5, "/tmp/out.jpg")
    assert cmd[0] == "ffmpeg"
    ss, i = cmd.index("-ss"), cmd.index("-i")
    assert ss < i, "-ss 放 -i 前＝关键帧快速定位（抽缩略图不需要帧级精确）"
    assert cmd[ss + 1] == "4.50"
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    assert cmd[cmd.index("-vf") + 1] == f"scale={settings.ASSET_FRAME_THUMB_WIDTH}:-2"
    assert cmd[cmd.index("-q:v") + 1] == f.JPEG_QA


def test_grid_cmd_tiles_the_whole_clip_and_starts_half_a_step_in():
    cmd = f.build_grid_cmd("/tmp/src.mp4", 9.0, "/tmp/grid.jpg")
    assert cmd[cmd.index("-ss") + 1] == "0.50", "起点抬半个间隔，躲开 t=0"
    assert cmd[cmd.index("-t") + 1] == "9.00"
    vf = cmd[cmd.index("-vf") + 1]
    assert "tile=3x3" in vf and "fps=1/1.0" in vf, vf
    cell = max(64, int(settings.ASSET_FRAME_GRID_WIDTH) // f.GRID_COLS)
    assert f"scale={cell}:-2" in vf, vf


def test_grid_cmd_refuses_a_zero_duration_instead_of_dividing_by_zero():
    with pytest.raises(ValueError):
        f.build_grid_cmd("/tmp/src.mp4", 0.0, "/tmp/grid.jpg")


# ───────────────────  跳过判定：回人话，不回异常  ───────────────────

def test_should_skip_names_the_reason_a_human_can_act_on():
    assert f.should_skip(30.0) is None

    r = f.should_skip(None)
    assert r and "时长未知" in r, r

    r = f.should_skip(1200.0)
    assert r and "超过抽帧上限" in r, r

    r = f.should_skip("abc")
    assert r and "不是数" in r, r

    assert f.should_skip(0) and f.should_skip(-1), "0/负数也要给原因，不是静默不抽"


def test_should_skip_treats_zero_cap_as_the_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "ASSET_FRAME_MAX_SOURCE_SECONDS", 0.0)
    r = f.should_skip(5.0)
    assert r and "关着" in r, r


# ───────────────────  0 字节对象不算成功  ───────────────────

def test_usable_rejects_a_zero_byte_file(tmp_path):
    empty = tmp_path / "x.jpg"
    empty.write_bytes(b"")
    assert f._usable(str(empty)) is False, "ffmpeg 退 0 但没落字节＝素材库真踩过的坑"
    assert f._usable(str(tmp_path / "nope.jpg")) is False
    good = tmp_path / "y.jpg"
    good.write_bytes(b"\xff\xd8")
    assert f._usable(str(good)) is True


@pytest.mark.asyncio
async def test_extract_does_not_raise_when_ffmpeg_is_missing(monkeypatch, tmp_path):
    """抽帧失败只回原因：一条坏文件不能把整批导入的抽帧一起带崩。"""
    async def _no_ffmpeg(cmd, timeout=None):
        return 127, "本机/容器内没有 ffmpeg 可执行文件"

    monkeypatch.setattr(f, "_run", _no_ffmpeg)
    got = await f.extract(str(tmp_path / "src.mp4"), 12.0, str(tmp_path / "out"))
    assert got["thumbs"] == [] and got["grid"] is None
    assert got["errors"], "全失败也要把原因带回去，台账里得写清为什么没图"
    assert any("第1帧" in e for e in got["errors"])
    assert any("九宫格" in e for e in got["errors"])


@pytest.mark.asyncio
async def test_extract_survives_a_partial_failure(tmp_path, monkeypatch):
    """单帧失败只少一张图，剩下的照给（九宫格成功就不算这条抽帧失败）。"""
    real_run = f._run

    async def _flaky(cmd, timeout=None):
        if cmd[cmd.index("-ss") + 1] == "1.35":
            return 1, "解码失败"
        return await real_run(cmd, timeout)

    src = _make_clip(tmp_path)
    if src is None:
        pytest.skip("需要 ffmpeg 才能造测试片")
    monkeypatch.setattr(f, "_run", _flaky)
    got = await f.extract(src, 3.0, str(tmp_path / "out"))
    assert len(got["thumbs"]) == 2, [t["seq"] for t in got["thumbs"]]
    assert got["errors"] and "第2帧" in got["errors"][0], got["errors"]


# ───────────────────  真跑 ffmpeg 的回归  ───────────────────

def _make_clip(tmp_path: Path):
    """造一条 3 秒 720x1280 的测试片（彩条＋正弦音，yuv420p + faststart）。"""
    if not HAS_FFMPEG:
        return None
    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=25:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         "-movflags", "+faststart", str(out)],
        check=True, capture_output=True,
    )
    return str(out)


@pytest.mark.skipif(not HAS_FFMPEG, reason="本机/CI 没装 ffmpeg+ffprobe")
@pytest.mark.asyncio
async def test_real_ffmpeg_produces_three_thumbs_and_one_grid(tmp_path):
    src = _make_clip(tmp_path)
    got = await f.extract(src, 3.0, str(tmp_path / "out"))

    assert got["errors"] == [], got["errors"]
    assert len(got["thumbs"]) == 3
    assert [t["seq"] for t in got["thumbs"]] == [0, 1, 2]
    assert [t["kind"] for t in got["thumbs"]] == [FRAME_THUMB] * 3
    assert [t["t_offset"] for t in got["thumbs"]] == [0.3, 1.35, 2.4]

    grid = got["grid"]
    assert grid and grid["kind"] == FRAME_GRID and grid["seq"] == 0
    assert grid["t_offset"] == pytest.approx(3.0 / 9 / 2, abs=0.01)

    for item in got["thumbs"] + [grid]:
        path = Path(item["path"])
        assert path.is_file() and item["file_size"] == path.stat().st_size > 0, item
        head = path.read_bytes()[:3]
        assert head == b"\xff\xd8\xff", f"{path} 不是 JPEG（{head!r}）"

    # 尺寸：单帧宽=配置宽、高按 720x1280 等比取偶数；九宫格整图宽=配置宽
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", got["thumbs"][0]["path"]],
        check=True, capture_output=True, text=True,
    )
    w, h = (int(x) for x in probe.stdout.strip().split(","))
    assert w == int(settings.ASSET_FRAME_THUMB_WIDTH)
    assert h == int(settings.ASSET_FRAME_THUMB_WIDTH) * 1280 // 720

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", grid["path"]],
        check=True, capture_output=True, text=True,
    )
    gw, gh = (int(x) for x in probe.stdout.strip().split(","))
    cell = int(settings.ASSET_FRAME_GRID_WIDTH) // f.GRID_COLS
    assert gw == cell * f.GRID_COLS == int(settings.ASSET_FRAME_GRID_WIDTH)
    assert gh == (cell * 1280 // 720) * f.GRID_COLS


@pytest.mark.skipif(not HAS_FFMPEG, reason="本机/CI 没装 ffmpeg+ffprobe")
@pytest.mark.asyncio
async def test_real_ffmpeg_on_a_garbage_file_reports_instead_of_raising(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes("这不是视频".encode("utf-8") * 200)
    got = await f.extract(str(bad), 30.0, str(tmp_path / "out"))
    assert got["thumbs"] == [] and got["grid"] is None
    assert got["errors"], "坏文件也要有原因，不然台账里就是一条看不懂的「失败」"
