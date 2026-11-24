"""concat 唯一实现守卫（1123 施工方案 §9.3 收口）。

为什么值得写成测试而不是注释：拼接配方一共有三处调用方（手工两段拼接、批 Q 的回收后
自动拼、11-24 需求三的组合导出矩阵），而仓库里**还留着另一份能用的** concat 实现
（`api/upload.py::_ffmpeg_concat`）。漂移的过程从来不是"有人故意写两遍"，是第四个人
需要拼视频时搜到一个现成函数就调了——然后四条线的画幅口径开始各走各的：
`_ffmpeg_concat` 的回退档硬编码 `1920:1080` 横屏，会把这批业务的全部竖屏片加黑边塞进
横框（这正是 11-04 定「不复用它」的原始理由）。

四条判据：
1. 后端里 `concat=n=` 这条 ffmpeg 滤镜串**只出现在** `asset_compose_service.py`；
2. concat 命令构建函数（`build_concat_cmd` / `build_concat_filter` / `concat_segments`）
   的定义只有一份；
3. `_ffmpeg_concat` 只剩「多文件合并上传」那**一个**调用点，且它的禁止新增调用方告示
   还在（告示被删＝下一个人又开始复用它）；
4. 素材库三条拼接线全部走 `_concat_render`，没人绕过去自己接 ffmpeg。
"""

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def _py_files():
    for p in APP_ROOT.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        yield p, p.read_text(encoding="utf-8")


def test_only_one_place_builds_a_concat_filter():
    owners = sorted(
        str(p.relative_to(APP_ROOT)) for p, src in _py_files() if "concat=n=" in src
    )
    assert owners == ["services/asset_compose_service.py"], (
        f"concat 滤镜串出现在 {owners}——§9.3 的收口口径是全仓只此一份，"
        "新写的那处必须改成调 asset_compose_service，或者把两处一起并成一份"
    )


def test_concat_command_builders_are_defined_exactly_once():
    # probe_media **不在**这份名单里，不是漏写：`utils/source_media.py` 那个同步版服务的是
    # 上传/归一化线（projects.py:34、upload.py:348），字段只有 width/height/fps/duration；
    # compose 服务这个异步版多带 has_audio，是拼接配方的输入契约。两个同名不同物属历史遗留，
    # 要收口的是 concat 命令本身，不是 ffprobe——把 probe_media 一起钉死只会挡住正当的调用方。
    for fn in ("build_concat_cmd", "build_concat_filter", "concat_segments"):
        defs = [
            str(p.relative_to(APP_ROOT))
            for p, src in _py_files()
            if re.search(rf"^(async )?def {fn}\(", src, re.M)
        ]
        assert defs == ["services/asset_compose_service.py"], f"{fn} 出现了多份定义：{defs}"


def test_upload_concat_is_frozen_to_its_one_caller_and_still_warns():
    """`upload.py::_ffmpeg_concat` ＝ 仅限多文件合并上传：调用点必须还是只有它自己那一个。"""
    call_sites = [
        str(p.relative_to(APP_ROOT))
        for p, src in _py_files()
        for line in src.splitlines()
        if re.search(r"_ffmpeg_concat\(", line) and not line.strip().startswith(("def ", "async def "))
    ]
    assert call_sites == ["api/upload.py"], (
        f"_ffmpeg_concat 的调用方变成了 {call_sites}——它有硬编码 1920:1080 横屏的回退档，"
        "素材库/切片线的竖屏片走它会全部加黑边。要拼视频请用 asset_compose_service.concat_segments"
    )

    src = (APP_ROOT / "api" / "upload.py").read_text(encoding="utf-8")
    body = src.split("async def _ffmpeg_concat(", 1)
    assert len(body) == 2, "_ffmpeg_concat 不见了：如果它已被合并进 compose 服务，请同步删掉本用例"
    doc = body[1].split('"""', 2)[1]  # 函数 docstring
    for marker in ("仅限", "禁止新增调用方", "asset_compose_service"):
        assert marker in doc, f"_ffmpeg_concat 的告示少了「{marker}」——这道闸就只剩注释在扛了"
    assert "test_asset_concat_single_impl" in src, "守卫用例名也要留在原地，下一个人才知道这行是有人看着的"


def test_asset_library_concat_lines_all_go_through_one_render():
    misc = (APP_ROOT / "api" / "assets" / "misc.py").read_text(encoding="utf-8")
    renders = len(re.findall(r"await _concat_render\(", misc))
    assert renders == 3, (
        f"素材库走 `_concat_render` 的拼接线现在是 {renders} 条（应为 3："
        "手工拼接／回收自动拼／组合导出矩阵）。多了＝有人绕过统一口自己接 ffmpeg，"
        "少了＝某条线被拆掉而这里没跟着改"
    )
    assert len(re.findall(r"compose\.concat_segments\(", misc)) == 1, (
        "只有 `_concat_render` 能调 concat_segments；出现第二处＝绕开了统一的产物落桶口"
    )


def test_compose_service_is_the_only_importer_of_concat_rules():
    """拼接配方不许被复制成两份常量：段数上下限、超时档只认 compose 服务这一个来源。"""
    owners = [
        str(p.relative_to(APP_ROOT))
        for p, src in _py_files()
        if re.search(r"^MIN_SEGMENTS\s*=", src, re.M) or re.search(r"^MAX_SEGMENTS\s*=", src, re.M)
    ]
    assert owners == ["services/asset_compose_service.py"], f"段数上下限散落到 {owners}"
