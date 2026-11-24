"""叠加层（11-24 需求三 S3）单测：校验、话术、引擎缺位时的老实交代。

这块的真风险不是 ffmpeg 跑不对，而是**静默交付外观不对的片子**，所以判据全在
「坏值必须当场 400 并说清是哪一项」上：

1. 位置不认识 ⇒ 400。引擎侧（`engines/slice.py` 的 `build_badges_overlay_args`）是悄悄
   回落 top-left 的容错，那是"渲染不能停"的取舍；放到出包线上就是"人选了右下角、
   片子上在左上角、系统报成功"，所以素材库这一层必须比引擎严一档。
2. 角标只认**素材库图片行 id**，不认 MinIO key（批 G 那条教训：手填 key 打错字符
   照样建单，投出去是没卡的片）。
3. 数字坏值不许悄悄取默认（`offset: "abc"` 存进预设后每次出片都按默认走，
   改的人永远不知道没生效）。
4. 引擎不可用时回**一句人话**，且失败结果要缓存——否则每个请求都重跑一次注定失败的 import。
"""

import asyncio
import os
import sys
import uuid as _uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

# settings 是模块级实例化的（app/config.py:561），四个字段没默认值——不在 import 前
# 把环境变量塞好，本文件会在收集期就 ValidationError，报出来的还是「Field required」
# 这种和叠加八竿子打不着的话。同目录 test_asset_risk_lexicon.py 是同样写法。
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_asset_overlay.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.services import asset_overlay_service as ov  # noqa: E402


def _400(fn, *a, **kw):
    """跑一下，要求它当场 400，并把话术返回给断言。"""
    with pytest.raises(HTTPException) as exc:
        fn(*a, **kw)
    assert exc.value.status_code == 400, exc.value.detail
    return exc.value.detail


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────  位置表：与引擎逐字同名  ─────────────────────

def test_position_table_matches_the_engine_verbatim():
    """引擎侧那两处常量改了名/加了位，这里必须红——参数结构解耦的前提是键名一致。"""
    engine = BACKEND_ROOT.parent / "engines" / "slice.py"
    if not engine.is_file():  # 本机没挂引擎目录时不硬拦（现网容器里一定有）
        pytest.skip(f"本机没有 {engine}，位置表比对留给现网")
    src = engine.read_text(encoding="utf-8")
    for name in ov.BADGE_POSITIONS:
        assert f'"{name}"' in src, f"引擎的位置表里没有 {name}，素材库不许自己造一个"
    assert ov.TEXT_POSITIONS == ov.BADGE_POSITIONS


def test_bad_position_is_rejected_not_silently_fallback():
    badge = {"asset_id": "11111111-1111-1111-1111-111111111111", "position": "top-left"}
    assert ov.validate_overlay({"badges": [badge]})["badges"][0]["position"] == "top-left"
    msg = _400(ov.validate_overlay, {"badges": [{**badge, "position": "middle-right"}]})
    assert "不认识" in msg and "top-left" in msg, "报错要把可选位说出来，别让人猜"
    assert "没选位置" in _400(ov.validate_overlay, {"badges": [{**badge, "position": ""}]})


def test_badge_must_reference_an_asset_not_a_minio_key():
    msg = _400(ov.validate_overlay, {"badges": [{"position": "top-right", "path": "a/b.png"}]})
    assert "从素材库里挑" in msg and "MinIO" in msg
    many = [{"asset_id": f"i{i}", "position": "left"} for i in range(ov.MAX_BADGES + 1)]
    assert f"最多 {ov.MAX_BADGES} 个" in _400(ov.validate_overlay, {"badges": many})


def test_numbers_are_not_quietly_defaulted():
    badge = {"asset_id": "x", "position": "left"}
    assert ov.validate_overlay({"badges": [badge]})["badges"][0]["offset"] == 10  # 没填＝默认
    assert "得是整数" in _400(ov.validate_overlay, {"badges": [{**badge, "offset": "abc"}]})
    assert "只能在 0～600" in _400(ov.validate_overlay, {"badges": [{**badge, "offset": 601}]})
    # 透明度下限是 0.05 而不是 0：0 透明＝叠了一张看不见的图，但位置被占了
    assert "看不见" in _400(ov.validate_overlay, {"badges": [{**badge, "opacity": 0}]})
    assert "得是 0～1" in _400(ov.validate_overlay, {"badges": [{**badge, "opacity": "半"}]})


def test_text_overlay_rules():
    line = {"text": "本剧纯属虚构", "position": "bottom-center"}
    got = ov.validate_overlay({"text_overlays": [line]})["text_overlays"][0]
    assert got["font_size"] == 36 and got["color"] == "#FFFFFF" and got["vertical"] is False
    assert "是空的" in _400(ov.validate_overlay, {"text_overlays": [{**line, "text": "  "}]})
    long = _400(ov.validate_overlay,
                {"text_overlays": [{**line, "text": "字" * (ov.MAX_TEXT_CHARS + 1)}]})
    assert f"最多 {ov.MAX_TEXT_CHARS} 字" in long
    assert "#RGB" in _400(ov.validate_overlay, {"text_overlays": [{**line, "color": "white"}]})
    assert "只能在 12～200" in _400(
        ov.validate_overlay, {"text_overlays": [{**line, "font_size": 6}]})
    many = [{"text": "行", "position": "left"} for _ in range(ov.MAX_TEXT_OVERLAYS + 1)]
    assert f"最多 {ov.MAX_TEXT_OVERLAYS} 行" in _400(ov.validate_overlay, {"text_overlays": many})


def test_unknown_keys_are_dropped_not_stored():
    """预设是存库反复用的东西：`{"widh": 80}` 这种手滑键留着＝永久生效的静默默认值。"""
    got = ov.validate_overlay({
        "badges": [{"asset_id": "x", "position": "left", "widh": 80, "asset_id ": "y"}],
        "text_overlays": [{"text": "字", "position": "left", "font-size": 44}],
        "whatever": [1, 2],
    })
    assert set(got["badges"][0]) == {"asset_id", "position", "width", "offset", "opacity"}
    assert set(got["text_overlays"][0]) == {
        "text", "position", "font_size", "color", "border_color", "vertical", "offset"}
    assert set(got) == {"badges", "text_overlays"}


def test_validate_rejects_non_list_shapes():
    assert "必须是列表" in _400(ov.validate_overlay, {"badges": {"asset_id": "x"}})
    assert "格式不对" in _400(ov.validate_overlay, {"badges": ["一个字符串"]})
    assert ov.validate_overlay(None) == {"badges": [], "text_overlays": []}
    assert ov.validate_overlay({"badges": None, "text_overlays": None}) == {
        "badges": [], "text_overlays": []}


# ─────────────────────  一句话回显（界面预告／审计）  ─────────────────────

def test_summary_says_it_plainly():
    assert ov.overlay_is_empty(None) and ov.overlay_is_empty({"badges": [], "text_overlays": []})
    assert ov.overlay_summary(None) == "不叠加"
    params = ov.validate_overlay({
        "badges": [{"asset_id": "x", "position": "top-right"}],
        "text_overlays": [{"text": "本剧纯属虚构，请勿模仿", "position": "bottom-center"}],
    })
    s = ov.overlay_summary(params)
    assert "1 个角标（top-right）" in s and "1 行字" in s and "＋" in s
    # 长文字只回显前 8 字，别把审计 after 撑成整段文案
    assert "本剧纯属虚构，请" in s and "勿模仿" not in s


# ─────────────────────  角标图解析：坏一张就整格失败  ─────────────────────

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _db_with(rows):
    return SimpleNamespace(execute=AsyncMock(return_value=_FakeResult(rows)))


def _asset(asset_id, *, kind="image", file_key="asset/img/card.png", code="AS-CARD"):
    return SimpleNamespace(id=asset_id, media_kind=kind, file_key=file_key,
                           bucket="raw", code=code)


def test_resolve_badges_downloads_each_image_and_keeps_order(tmp_path):
    ids = [str(_uuid.uuid4()), str(_uuid.uuid4())]
    rows = [_asset(i, file_key=f"asset/img/{i}.png") for i in ids]
    written = []

    async def _dl(bucket, key, path):
        with open(path, "wb") as fh:
            fh.write(b"png bytes")
        written.append((bucket, key, os.path.basename(path)))
        return True

    async def _scenario():
        badges = [{"asset_id": ids[0], "position": "top-left", "width": 0, "offset": 10, "opacity": 1.0},
                  {"asset_id": ids[1], "position": "bottom-right", "width": 0, "offset": 10, "opacity": 1.0}]
        with patch("app.services.minio_service.download_to_file", _dl):
            got = await ov.resolve_badges(_db_with(rows), badges, str(tmp_path))
        assert [g["asset_id"] for g in got] == ids, "顺序＝板上顺序，不许悄悄重排"
        assert [os.path.basename(g["path"]) for g in got] == ["badge_0.png", "badge_1.png"]
        assert written[0][1] == rows[0].file_key
        # 空列表不查库、不调下载
        db = _db_with([])
        assert await ov.resolve_badges(db, [], str(tmp_path)) == []
        assert db.execute.await_count == 0

    _run(_scenario())


def test_resolve_badges_fails_the_cell_instead_of_skipping():
    """引擎侧那套 `valid` 过滤会跳过坏角标继续出片；素材库这边一条都不许放。"""
    vid, gone = str(_uuid.uuid4()), str(_uuid.uuid4())

    async def _scenario():
        # ① 选了视频当角标
        db = _db_with([_asset(vid, kind="video", file_key="asset/video/raw.mp4")])
        assert "不是图片" in await _raises_400(
            ov.resolve_badges(db, [{"asset_id": vid, "position": "left"}], "/tmp"))
        # ② 桶里没有文件
        db = _db_with([_asset(vid, file_key=None)])
        assert "桶里没有文件" in await _raises_400(
            ov.resolve_badges(db, [{"asset_id": vid, "position": "left"}], "/tmp"))
        # ③ 图已被删（查不到行）
        assert "不在素材库里" in await _raises_400(
            ov.resolve_badges(_db_with([]), [{"asset_id": gone, "position": "left"}], "/tmp"))
        # ④ 下载说成功了但本地是空的 ⇒ 502（环境问题，不是人选错了）
        with patch("app.services.minio_service.download_to_file", AsyncMock(return_value=True)):
            with pytest.raises(HTTPException) as exc:
                await ov.resolve_badges(
                    _db_with([_asset(vid)]), [{"asset_id": vid, "position": "left"}], "/tmp/不存在")
        assert exc.value.status_code == 502 and "稍后重试" in exc.value.detail

    _run(_scenario())


async def _raises_400(coro):
    try:
        await coro
    except HTTPException as exc:
        assert exc.status_code == 400, exc.detail
        return exc.detail
    raise AssertionError("本该 400，却放过去了")


def test_badge_asset_id_must_be_a_uuid():
    """坏 id 当场 400（而不是让驱动在绑定参数时抛一堆方言话）。"""
    msg = _400(_run, ov.resolve_badges(
        _db_with([]), [{"asset_id": "不是 uuid", "position": "left"}], "/tmp"))
    assert "不是合法的素材 id" in msg


# ─────────────────────  引擎不可用：一句人话＋只判一次  ─────────────────────

@pytest.fixture
def clean_engine_cache():
    saved = (ov._ENGINE, ov._ENGINE_ERROR)
    ov._ENGINE, ov._ENGINE_ERROR = None, None
    yield
    ov._ENGINE, ov._ENGINE_ERROR = saved


def test_engine_missing_is_reported_once_and_in_plain_words(clean_engine_cache):
    with patch.object(ov, "_engine_path", lambda: None):
        ok, err = ov.engine_available()
    assert ok is False and "找不到切片引擎" in err and "打桩" in err
    # 失败结果**也**缓存：不许每个请求都重跑一次注定失败的探测
    with patch.object(ov, "_engine_path", side_effect=AssertionError("不该再探第二次")):
        assert ov.engine_available() == (False, err)


def test_apply_overlay_without_engine_returns_the_reason(clean_engine_cache):
    ov._ENGINE, ov._ENGINE_ERROR = None, "引擎没挂上"

    async def _scenario():
        # 什么都不叠 ⇒ 直接放行（这是「不叠加」那一格的路径，不该被引擎缺位拦住）
        assert await ov.apply_overlay("/tmp/a.mp4", "/tmp/b.mp4", [], []) is None
        # 要叠 ⇒ 回原因（不带「叠加失败：」前缀，前缀由调用方统一加）
        assert await ov.apply_overlay("/tmp/a.mp4", "/tmp/b.mp4", [{"position": "left"}], []) \
            == "引擎没挂上"

    _run(_scenario())


def test_apply_overlay_runs_badges_then_text_and_replaces_output(clean_engine_cache, tmp_path):
    """两层各跑一次 ffmpeg；角标先、文字后（剧名压在角标之上才看得清）。"""
    calls = []

    def _badges(src, out, badges, threads=1):
        calls.append(("badges", src, out, len(badges), threads))
        with open(out, "wb") as fh:
            fh.write(b"badged")

    def _texts(src, out, texts, threads=1):
        calls.append(("texts", src, out, len(texts), threads))
        with open(out, "wb") as fh:
            fh.write(b"texted")

    ov._ENGINE = SimpleNamespace(apply_badges=_badges, apply_text_overlays=_texts)
    ov._ENGINE_ERROR = None
    src, out = str(tmp_path / "in.mp4"), str(tmp_path / "out.mp4")
    with open(src, "wb") as fh:
        fh.write(b"raw")

    async def _scenario():
        got = await ov.apply_overlay(src, out, [{"position": "left"}], [{"text": "字"}], threads=2)
        assert got is None, got
        assert open(out, "rb").read() == b"texted"
        assert [c[0] for c in calls] == ["badges", "texts"]
        assert calls[1][1] == out + ".badged.mp4", "文字层要吃角标层的产物，不是吃原片"
        assert all(c[4] == 2 for c in calls)
        assert not os.path.exists(out + ".texted.mp4"), "中间产物要收掉，别在临时目录里堆片"

    _run(_scenario())


def test_apply_overlay_reports_silent_engine_failure(clean_engine_cache):
    """引擎"跑完了但没产出文件"不能当成功——那是 11-04 那个 0 字节对象的原族。"""
    ov._ENGINE = SimpleNamespace(
        apply_badges=lambda src, out, badges, threads=1: None,
        apply_text_overlays=lambda src, out, texts, threads=1: None)
    ov._ENGINE_ERROR = None

    async def _scenario():
        got = await ov.apply_overlay("/tmp/没有这个.mp4", "/tmp/也不会有.mp4", [{"position": "left"}], [])
        assert got and "静默失败" in got, got

    _run(_scenario())


def test_apply_overlay_wraps_engine_exception_into_one_sentence(clean_engine_cache):
    def _boom(*_a, **_kw):
        raise RuntimeError("ffmpeg exit 234 Invalid argument")

    ov._ENGINE = SimpleNamespace(apply_badges=_boom, apply_text_overlays=_boom)
    ov._ENGINE_ERROR = None

    async def _scenario():
        got = await ov.apply_overlay("/tmp/x.mp4", "/tmp/y.mp4", [{"position": "left"}], [])
        assert got.startswith("RuntimeError:") and "ffmpeg exit 234" in got
        assert "叠加失败：" not in got, "前缀由调用方统一加，否则日志里两层前缀"

    _run(_scenario())
