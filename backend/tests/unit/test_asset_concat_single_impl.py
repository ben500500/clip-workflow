"""concat 唯一实现守卫（1123 施工方案 §9.3 收口，2026-11-25 随「统一到切片引擎」改判据）。

为什么值得写成测试而不是注释：拼接配方一共有三处调用方（手工两段拼接、批 Q 的回收后
自动拼、11-24 需求三的组合导出矩阵），而仓库里**还留着另一份能用的** concat 实现
（`api/upload.py::_ffmpeg_concat`）。漂移的过程从来不是"有人故意写两遍"，是第四个人
需要拼视频时搜到一个现成函数就调了——然后四条线的画幅口径开始各走各的：
`_ffmpeg_concat` 的回退档硬编码 `1920:1080` 横屏，会把这批业务的全部竖屏片加黑边塞进
横框（这正是 11-04 定「不复用它」的原始理由）。

**11-25 起那"唯一一份"从 backend 挪到了 `engines/slice.py`**（用户原话：「拼接你可不可以
直接用短剧切片的那套现成的代码？就是那边我更新了，你这边也无需再动。」）。判据因此
从「backend 里只有一处」变成「跨两处目录只有一处，且在引擎那侧」——这条必须用机器守住，
否则下一任看见 backend 里没有配方，会顺手再补一份"以防引擎挂不到"。

五条判据：
1. 全仓（`backend/app` ＋ `engines`）里 `concat=n=` 这条 ffmpeg 滤镜串**只出现在**
   `engines/slice.py`，`backend/app` 里一处都不许有；
2. 素材库适配层 `asset_compose_service.py` 的**代码**里不许再出现任何 ffmpeg 配方串
   （`filter_complex`／`concat=n=`／`-movflags`）——docstring 里提到这些词是允许的，
   所以走 AST 只看非文档字符串的字面量；
3. concat 相关函数定义不重复（适配层 `concat_segments` 一份、引擎 `concat_segments`
   与 `build_concat_filtergraph` 各一份；旧的 `build_concat_cmd`/`build_concat_filter`
   应当**全仓归零**）；
4. `_ffmpeg_concat` 只剩「多文件合并上传」那**一个**调用点，且它的禁止新增调用方告示
   还在（告示被删＝下一个人又开始复用它）；
5. 素材库三条拼接线全部走 `_concat_render`，没人绕过去自己接 ffmpeg。
"""

import ast
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"      # backend/app
REPO_ROOT = Path(__file__).resolve().parents[3]             # 仓库根
ENGINES_ROOT = REPO_ROOT / "engines"

# `slice-worker/engines/` 是 .gitignore 的**构建副本**（唯一事实来源是仓库根 engines/，
# 由 scripts/sync-engines-to-worker.sh 全量刷新），它含同一份配方属正常，不算第二处实现。
_RECIPE_MARKERS = ("filter_complex", "concat=n=", "-movflags")


def _py_files(root: Path, prefix: str):
    for p in root.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts or "slice-worker" in p.parts:
            continue
        yield f"{prefix}/{p.relative_to(root)}", p.read_text(encoding="utf-8")


def _code_strings(src: str) -> list[str]:
    """文件里**非 docstring** 的字符串字面量（配方只可能出现在代码里，叙述里提到不算）。"""
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_only_the_engine_builds_a_concat_filter():
    # 这一条是**裸文本**扫（连注释一起扫），故意比下面 AST 那条更严：配方字面量在全仓
    # 只该有一个出处，谁在 backend 的注释里写一遍 "concat=n="，下一个人 grep 到了就会
    # 以为 backend 里也有配方、顺手去改它——叙述要提这件事，写函数名别写滤镜串。
    owners = sorted(rel for rel, src in _py_files(ENGINES_ROOT, "engines") if "concat=n={" in src)
    assert owners == ["engines/slice.py"], (
        f"concat 滤镜串出现在 {owners}——§9.3 的收口口径是全仓只此一份且在切片引擎里，"
        "新写的那处必须改成调 engines/slice.py::concat_segments，或者把两处并成一份"
    )
    in_backend = sorted(rel for rel, src in _py_files(APP_ROOT, "app") if "concat=n=" in src)
    assert in_backend == [], (
        f"backend 里又出现了 concat 滤镜串 {in_backend}——素材库这一侧只准做适配层，"
        "否则「切片线更新了这边不用动」这句话当场作废；"
        "若只是注释/文档里提了一句，把它改成说事不写字面量（本条故意扫裸文本）"
    )


def test_asset_compose_service_holds_no_ffmpeg_recipe():
    """适配层里不许留任何配方串——留了就会 drift，而 drift 的表现是两条线各出各的片。"""
    src = (APP_ROOT / "services" / "asset_compose_service.py").read_text(encoding="utf-8")
    offenders = [
        marker for marker in _RECIPE_MARKERS
        if any(marker in lit for lit in _code_strings(src))
    ]
    assert offenders == [], (
        "asset_compose_service.py 的代码里还残留配方串 "
        f"{offenders}——11-25 起拼接一律走 engines/slice.py，"
        "这里只该剩闸门＋线程池＋话术翻译"
    )


def test_concat_command_builders_are_defined_exactly_once():
    # probe_media **不在**这份名单里，不是漏写：`utils/source_media.py` 那个同步版服务的是
    # 上传/归一化线（projects.py:34、upload.py:348），字段只有 width/height/fps/duration；
    # compose 服务这个异步版多带 has_audio，是拼接输入的契约（段数/是不是视频的守门）。
    # 两个同名不同物属历史遗留，要收口的是 concat 命令本身，不是 ffprobe——
    # 把 probe_media 一起钉死只会挡住正当的调用方。
    everywhere = list(_py_files(APP_ROOT, "app")) + list(_py_files(ENGINES_ROOT, "engines"))
    expect = {
        # 适配层一份（名字保留是为了让现有打桩照样生效）
        "concat_segments": ["app/services/asset_compose_service.py", "engines/slice.py"],
        "build_concat_filtergraph": ["engines/slice.py"],
        # 11-25 删掉的旧配方构造器：谁再写回来这里就红
        "build_concat_cmd": [],
        "build_concat_filter": [],
    }
    for fn, want in expect.items():
        defs = sorted(
            rel for rel, src in everywhere
            if re.search(rf"^(async )?def {fn}\(", src, re.M)
        )
        assert defs == sorted(want), f"{fn} 的定义变成了 {defs}（应为 {want}）"



def test_upload_concat_is_frozen_to_its_one_caller_and_still_warns():
    """`upload.py::_ffmpeg_concat` ＝ 仅限多文件合并上传：调用点必须还是只有它自己那一个。"""
    call_sites = [
        rel
        for rel, src in _py_files(APP_ROOT, "app")
        for line in src.splitlines()
        if re.search(r"_ffmpeg_concat\(", line) and not line.strip().startswith(("def ", "async def "))
    ]
    assert call_sites == ["app/api/upload.py"], (
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
    """拼接护栏常量不许被复制成两份：段数上下限只认 compose 服务这一个来源。"""
    owners = [
        rel
        for rel, src in _py_files(APP_ROOT, "app")
        if re.search(r"^MIN_SEGMENTS\s*=", src, re.M) or re.search(r"^MAX_SEGMENTS\s*=", src, re.M)
    ]
    assert owners == ["app/services/asset_compose_service.py"], f"段数上下限散落到 {owners}"
