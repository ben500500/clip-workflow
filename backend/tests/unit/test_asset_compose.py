"""素材库拼接服务单测（11-04 简化口径：两段直拼，顺序可选，不选点不剪切）。

钉住四件真会坏的事：
1. **目标画幅＝排在最前那一段**，绝不能出现 `1920:1080` 这种硬编码横屏档
   （`api/upload.py:644` 的回退就是把这个业务的全部竖屏片加黑边塞进横框）；
2. **缺音轨的那一段补静音轨**，不是丢掉音轨、也不是让 ffmpeg 整条命令失败；
3. **混规格不流拷贝**：一律 filter_complex + 显式重编码（切片引擎同结论）；
4. 探不到视频流/解析不出 resolution 时**不猜**，把决定权交回调用方。

最后一条是**真跑 ffmpeg** 的回归（装了才跑，没装就 skip）：竖屏+有声 与 横屏+无声 两种
来源拼完，断言时长＝两段之和、画幅＝第一段、音轨还在。
"""

import asyncio
import json
import shutil
import subprocess
import uuid

import pytest

from app.services import asset_compose_service as c

VERT = {"width": 720, "height": 1280, "fps": "25/1", "duration": 10.08}
HORIZ_NO_AUDIO = {"width": 1280, "height": 720, "fps": "30/1", "duration": 6.0, "has_audio": False}


def _seg(**kw):
    base = {"has_audio": True, "duration": 5.0}
    base.update(kw)
    return base


# ─────────────────────────  规格解析：不许猜  ─────────────────────────

def test_parse_resolution_accepts_the_three_shapes_in_the_db():
    # slice_outputs.resolution 是自由文本，现网三种写法都见过
    assert c._parse_resolution("1080x1920") == (1080, 1920)
    assert c._parse_resolution("720*1280") == (720, 1280)
    assert c._parse_resolution("1080×1920") == (1080, 1920)
    assert c._parse_resolution(" 1080 X 1920 ") == (1080, 1920)


def test_parse_resolution_returns_none_instead_of_guessing():
    # 猜成 1920x1080 ＝ upload.py 那个横屏 bug 的成因，所以这里必须是 None
    for bad in (None, "", "竖屏", "1080", "1080x", "axb"):
        assert c._parse_resolution(bad) is None, bad


def test_fps_expr_keeps_fractional_rate_and_falls_back_on_junk():
    assert c._fps_expr("30000/1001") == "30000/1001"   # 原样给滤镜最准，换算成 29.97 会漂帧
    assert c._fps_expr("25/1") == "25/1"
    assert c._fps_expr("24") == "24"
    for junk in (None, "", "0/0", "N/A", "abc", "0/1", "-1/1"):
        assert c._fps_expr(junk) == c.DEFAULT_FPS, junk


def test_parse_probe_needs_a_video_stream_and_reports_audio_presence():
    def _probe(video, audio):
        streams = []
        if video:
            streams.append({"codec_type": "video", "width": 720, "height": 1280,
                            "avg_frame_rate": "25/1", "duration": "9.9"})
        if audio:
            streams.append({"codec_type": "audio"})
        return {"streams": streams, "format": {"duration": "10.02"}}

    assert c.parse_probe(None) is None
    assert c.parse_probe({"streams": [{"codec_type": "audio"}]}) is None      # 只有音轨＝不能拼
    assert c.parse_probe({"streams": [{"codec_type": "video", "duration": "1"}]}) is None  # 探不到宽高
    got = c.parse_probe(_probe(True, True))
    assert (got["width"], got["height"]) == (720, 1280)
    assert got["duration"] == 10.02 and got["has_audio"] is True
    assert c.parse_probe(_probe(True, False))["has_audio"] is False


# ─────────────────────────  拼接命令：口径就写在这条命令里  ─────────────────────────

def test_concat_cmd_scales_to_the_leading_segment_never_a_hardcoded_landscape():
    cmd, flt = c.build_concat_cmd(["/tmp/a.mp4", "/tmp/b.mp4"], "/tmp/out.mp4", VERT,
                                  [_seg(), _seg(**HORIZ_NO_AUDIO)])
    assert "scale=720:1280:force_original_aspect_ratio=decrease" in flt
    assert "pad=720:1280:(ow-iw)/2:(oh-ih)/2" in flt
    assert "setsar=1" in flt and "format=yuv420p" in flt
    # 这条断言就是"不复用 upload.py"的全部理由
    assert "1920:1080" not in flt and "1080:1920" not in flt
    assert "fps=25/1" in flt                                  # 帧率也跟第一段
    assert "-filter_complex" in cmd and "concat=n=2:v=1:a=1" in flt
    assert "-movflags" in cmd                                 # 边下边播，一线点下载不用等整文件
    assert "-c:v" in cmd and "libx264" in cmd                 # 显式重编码，绝不 -c copy
    assert "copy" not in " ".join(cmd)


def test_concat_cmd_pads_a_silent_track_for_the_segment_without_audio():
    cmd, flt = c.build_concat_cmd(["/tmp/a.mp4", "/tmp/b.mp4"], "/tmp/out.mp4", VERT,
                                  [_seg(duration=4.0), _seg(duration=7.5, has_audio=False)])
    # 缺音轨的段引用**追加的 lavfi 输入**（索引 2），不是裸 anullsrc（那是 source 滤镜，没输入可接）
    assert "[2:a]atrim=0:7.5" in flt
    assert "[0:a]aresample=async=1:first_pts=0[a0]" in flt   # 两段各自都有一条音频标签进 concat
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1" in flt
    assert cmd.count("anullsrc=channel_layout=stereo:sample_rate=44100") == 1
    assert "-f" in cmd and "lavfi" in cmd
    assert "-map" in cmd and "[outa]" in cmd                   # 音轨不静默丢掉


def test_concat_cmd_with_two_normal_segments_adds_no_extra_input():
    cmd, flt = c.build_concat_cmd(["/tmp/a.mp4", "/tmp/b.mp4"], "/tmp/out.mp4", VERT,
                                  [_seg(), _seg()])
    assert cmd.count("-i") == 2 and "lavfi" not in cmd
    assert "[0:a]aresample" in flt and "[1:a]aresample" in flt


def test_order_is_a_choice_not_a_default_only_path():
    assert c.resolve_input_order(c.ORDER_ASSET_FIRST, "A", "B") == ["A", "B"]
    assert c.resolve_input_order(c.ORDER_SECOND_FIRST, "A", "B") == ["B", "A"]
    assert c.resolve_input_order(None, "A", "B") == ["A", "B"]
    with pytest.raises(Exception) as exc:
        c.resolve_input_order("middle", "A", "B")
    assert "拼在前" in str(exc.value.detail) or "asset_first" in str(exc.value.detail)


def test_same_file_twice_is_rejected():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        c.check_inputs_differ("id-1", c.SOURCE_ASSET, "id-1")
    assert exc.value.status_code == 400 and "重复" in exc.value.detail
    # 同 id 但不同来源（素材库里那条 ≠ 切片产物）不该被这条挡住
    c.check_inputs_differ("id-1", c.SOURCE_SLICE, "id-1")


def test_concat_segments_rejects_wrong_count_and_reports_ffmpeg_failure_plainly():
    async def _scenario():
        # 段数不对：不启动 ffmpeg，直接一句人话
        assert await c.concat_segments(["/tmp/only.mp4"], VERT, "/tmp/o.mp4") == \
            "拼接固定两段，现在是 1 段（要三段以上再说，别改这条口径）"
        # 探不到视频流 → 指到具体是哪一段（一线要能看懂去换哪个文件）
        async def _no_video(path):
            return None
        original = c.probe_media
        c.probe_media = _no_video
        try:
            err = await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, "/tmp/o.mp4")
            assert "探不出视频流" in err
        finally:
            c.probe_media = original

    asyncio.run(_scenario())


# ─────────────────────────  真跑 ffmpeg 的回归  ─────────────────────────

@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="本机/CI 没有 ffmpeg，跳过真拼回归")
def test_real_ffmpeg_concat_keeps_leading_orientation_and_both_durations(tmp_path):
    """竖屏有声 2s + 横屏无声 3s → 拼完必须是竖屏 5s 且仍有音轨；反过来则出横屏。"""
    a, b = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")
    out = str(tmp_path / "out.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=red:s=720x1280:r=25", "-f", "lavfi",
                    "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", a], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=blue:s=1280x720:r=30", "-t", "3", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", b], check=True)

    async def _scenario():
        ia, ib = await c.probe_media(a), await c.probe_media(b)
        assert (ia["width"], ia["height"], ia["has_audio"]) == (720, 1280, True)
        assert (ib["width"], ib["height"], ib["has_audio"]) == (1280, 720, False)

        assert await c.concat_segments([a, b], ia, out) is None
        got = await c.probe_media(out)
        assert (got["width"], got["height"]) == (720, 1280), "画幅跟第一段（竖屏）"
        assert 4.6 <= got["duration"] <= 5.4, f"时长应是两段之和：{got}"
        assert got["has_audio"] is True, "第二段没音轨也不能把整条的音轨弄丢"

        out2 = str(tmp_path / f"o2-{uuid.uuid4().hex[:6]}.mp4")
        assert await c.concat_segments([b, a], ib, out2) is None
        got2 = await c.probe_media(out2)
        assert (got2["width"], got2["height"]) == (1280, 720), "换了顺序就是换了画幅"
        assert 4.6 <= got2["duration"] <= 5.4
        assert json.dumps(got2, ensure_ascii=False)  # 探到的结构能直接写库（resolution 拼串用）
        assert c.sha256_of(out2) and len(c.sha256_of(out2)) == 64

    asyncio.run(_scenario())
