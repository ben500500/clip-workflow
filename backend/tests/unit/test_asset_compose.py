"""素材库拼接服务单测（11-04 简化口径：两段直拼，顺序可选，不选点不剪切）。

2026-11-25 起本模块**不再自带 ffmpeg 配方**，改为调切片线引擎
（`engines/slice.py::concat_segments`，用户原话：「那边我更新了，你这边也无需再动」）。
所以这里钉的是四件**接线层**会坏的事：
1. 段数闸门（2～3）与「不是视频就别拼」——闸门一松，引擎单段那条 `shutil.move`
   会把调用方的输入文件**搬走**（缓存原片／已入库产物被搬＝数据事故）；
2. 阻塞的 ffmpeg 走线程池，不压在事件循环上；
3. 引擎的异常/空产物翻成能给人看的原话，不许"没报错就算成功"；
4. 引擎挂不到（本地开发机）时报人话，不许 500、也不许退回"自己再写一份配方"。

配方本身的口径在 `engines/tests/test_concat_graph_regression.py`，另有一份
「全仓只此一份 concat」的静态守卫在 `test_asset_concat_single_impl.py`。

最后一条是**真跑 ffmpeg** 的回归（装了才跑，没装就 skip）：它跑的是**真引擎**，
等于把「适配层＋引擎」这条链在原子上验了一遍——竖屏+有声 与 横屏+无声 两种来源拼完，
断言时长＝两段之和、画幅＝第一段、音轨还在。
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

from app.services import asset_compose_service as c

VERT = {"width": 720, "height": 1280, "fps": "25/1", "duration": 10.08}


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


# ───────────────────  适配层：只调引擎、不自己写配方（11-25 改口径）  ───────────────────
#
# 这一段的判据从「拼出来的滤镜串长什么样」换成了「有没有老实把活儿交给引擎」——
# 滤镜串本身的口径（目标画幅＝首段、缺音轨补 anullsrc、混规格不流拷贝、faststart 开关）
# 全部搬到了引擎侧那份回归：`engines/tests/test_concat_graph_regression.py`。
# 分成两份是故意的：**配方变了动引擎那份，接线变了动这份**，两边不会互相误红。


class _FakeEngine:
    """冒充 engines/slice.py 的 concat_segments：记录调用参数与所在线程。"""

    def __init__(self, error=None, write_output=False):
        self.calls = []
        self.error = error
        self.write_output = write_output

    def concat_segments(self, parts, out, **kw):
        self.calls.append({"parts": list(parts), "out": out, "kw": kw,
                           "thread": threading.get_ident()})
        if self.error:
            raise RuntimeError(self.error)
        if self.write_output:
            with open(out, "wb") as fh:
                fh.write(b"\x00" * 4096)


def _stub_media_ok(monkeypatch):
    """把探测与可执行文件检查打桩：这几条测的是接线，不碰真 ffmpeg。"""
    async def _ok(path):
        return {"width": 720, "height": 1280, "fps": "25/1", "duration": 5.0, "has_audio": True}

    monkeypatch.setattr(c, "probe_media", _ok)
    monkeypatch.setattr(c.shutil, "which", lambda name: f"/usr/bin/{name}")


def _with_engine(monkeypatch, engine):
    monkeypatch.setattr(c, "_ENGINE", engine)
    monkeypatch.setattr(c, "_ENGINE_ERROR", None)


def test_adapter_delegates_to_engine_with_asset_side_flags(monkeypatch):
    """素材库这一侧要的三档：threads=0（同步等，别按切片线的限 CPU 默认）、faststart 开、允许流拷贝。"""
    _stub_media_ok(monkeypatch)
    engine = _FakeEngine(write_output=True)
    _with_engine(monkeypatch, engine)

    async def _scenario():
        assert await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, "/tmp/out.mp4") is None

    asyncio.run(_scenario())
    assert len(engine.calls) == 1, engine.calls
    kw = engine.calls[0]["kw"]
    assert kw["threads"] == 0, "照引擎默认 1 会把几秒的活儿拉成几十秒（本口是同步等）"
    assert kw["faststart"] is True, "产物要挂网页边下边播"
    assert kw["copy_if_possible"] is True, "同规格免重编码（引擎自己校验时长再回退）"
    assert kw["encoder"] == "libx264"
    assert engine.calls[0]["parts"] == ["/tmp/a.mp4", "/tmp/b.mp4"], "顺序＝调用方给的顺序"
    assert engine.calls[0]["out"] == "/tmp/out.mp4"


def test_adapter_runs_the_blocking_engine_call_off_the_event_loop(monkeypatch):
    """阻塞的 ffmpeg 必须在线程池里跑：三个拼接口都在同一个 uvicorn 事件循环上。

    这条一旦红（有人把 `run_in_executor` 改成直接调），表现是**拼一条片子期间整个后端
    不响应**——不是拼接报错，是最难归因的那种卡死，所以钉在这里。
    """
    _stub_media_ok(monkeypatch)
    engine = _FakeEngine(write_output=True)
    _with_engine(monkeypatch, engine)

    async def _scenario():
        assert await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, "/tmp/out.mp4") is None
        return threading.get_ident()

    main_thread = asyncio.run(_scenario())
    assert engine.calls[0]["thread"] != main_thread, "引擎在事件循环线程里被直接调了"


def test_adapter_turns_engine_failure_into_plain_words(monkeypatch):
    """引擎抛的是 `RuntimeError("ffmpeg failed: <stderr 尾部>")`，这里要变成能给人看的原话。"""
    _stub_media_ok(monkeypatch)
    _with_engine(monkeypatch, _FakeEngine(error="ffmpeg failed: Invalid data found when processing input"))

    async def _scenario():
        return await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, "/tmp/out.mp4")

    err = asyncio.run(_scenario())
    assert err and "拼接失败" in err and "Invalid data" in err, err


def test_adapter_rejects_a_zero_byte_product_as_failure(monkeypatch):
    """引擎不返回码——只说"没报错"不够。11-04 真链路踩过「桶里 0 字节对象照样 201」。"""
    _stub_media_ok(monkeypatch)
    empty = str(Path(tempfile.mkdtemp()) / "empty.mp4")
    with open(empty, "wb") as fh:
        fh.write(b"")
    _with_engine(monkeypatch, _FakeEngine(write_output=False))

    async def _scenario():
        return await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, empty)

    err = asyncio.run(_scenario())
    assert err and "空" in err, err

    async def _scenario_missing():
        return await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, "/tmp/never-created.mp4")

    assert "不存在" in asyncio.run(_scenario_missing())


def test_missing_engine_is_a_plain_refusal_not_a_crash(monkeypatch):
    """本地开发机没挂 engines 时：报一句人话，别 500、也别悄悄退回"自己再写一份配方"。"""
    _stub_media_ok(monkeypatch)
    monkeypatch.setattr(c, "_ENGINE", None)
    monkeypatch.setattr(c, "_ENGINE_ERROR", None)
    monkeypatch.setattr(c, "_engine_path", lambda: None)

    async def _scenario():
        return await c.concat_segments(["/tmp/a.mp4", "/tmp/b.mp4"], VERT, "/tmp/out.mp4")

    err = asyncio.run(_scenario())
    assert err and "切片引擎" in err, err
    assert c.engine_available()[0] is False


def test_engine_loader_survives_a_module_level_sys_exit(monkeypatch):
    """`engines/slice.py` 顶部对 Python<3.10 是直接 `sys.exit(1)`——那是 BaseException。

    接不住会把整个请求进程带走（表现＝后端重启，日志里只有一句 SystemExit），
    所以这里喂一个真的会 sys.exit 的假引擎文件，断言它变成一句人话。
    """
    bad = Path(tempfile.mkdtemp()) / "slice.py"
    bad.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    monkeypatch.setattr(c, "_ENGINE", None)
    monkeypatch.setattr(c, "_ENGINE_ERROR", None)
    monkeypatch.setattr(c, "_engine_path", lambda: str(bad))

    module, err = c._load_engine()
    assert module is None and err and "SystemExit" in err, err


def test_engine_loader_refuses_a_module_without_concat_segments(monkeypatch):
    """同名不同物：引擎里没 concat_segments 就判不可用，别到调用点才 TypeError。"""
    stub = Path(tempfile.mkdtemp()) / "slice.py"
    stub.write_text("def apply_badges():\n    return None\n", encoding="utf-8")
    monkeypatch.setattr(c, "_ENGINE", None)
    monkeypatch.setattr(c, "_ENGINE_ERROR", None)
    monkeypatch.setattr(c, "_engine_path", lambda: str(stub))

    module, err = c._load_engine()
    assert module is None and "concat_segments" in err, err


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
        # 段数不对：不启动 ffmpeg，直接一句人话。11-24 需求三把上限从 2 放宽到 3
        # （钩子片＋正片＋片尾），但**只放宽一格**——第四段属于混剪，得先回文档定口径。
        for n in (1, 4):
            err = await c.concat_segments([f"/tmp/{i}.mp4" for i in range(n)], VERT, "/tmp/o.mp4")
            assert f"现在是 {n} 段" in err and "混剪" in err, err
        assert await c.concat_segments(["/tmp/only.mp4"], VERT, "/tmp/o.mp4") == \
            "一次拼 2～3 段（钩子片／正片／片尾），现在是 1 段（要更多段属于混剪需求，" \
            "先回文档确认口径，别改这条）"
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
