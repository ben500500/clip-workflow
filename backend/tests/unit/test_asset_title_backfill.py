"""反推成功自动起标题（11-06 用户实测实锤的缺失功能）：抽屉一直承诺
「反推成功后才有标题」，但此前没有任何代码写过 asset.title。

自包含抽取函数源码执行，避免 import app.api.assets 拉起 Settings（与抽帧单测同思路）。
"""

import re
from pathlib import Path
from typing import Optional

_SRC = (Path(__file__).resolve().parents[2] / "app" / "api" / "assets.py").read_text()
_M = re.search(r"def _derive_asset_title_from_script.*?(?=\n\ndef |\nasync def )", _SRC, re.S)
assert _M, "_derive_asset_title_from_script 找不到了（函数被挪走？）"
exec(_M.group(0))


def _derive(script: Optional[str]):
    return _derive_asset_title_from_script(script)  # noqa: F821


class TestDerive:
    def test_primary_theme_section(self):
        s = "### 视频核心主题\n揭露假身份的冲突，涉及被藏匿的亲生妈妈。\n\n### 主要人物设定\n1. 宝宝"
        assert _derive(s) == "揭露假身份的冲突，涉及被藏匿的亲生妈妈"

    def test_fallback_first_prose_line(self):
        assert _derive("这是一篇没有小节标记的详规文本\n第二行") == "这是一篇没有小节标记的详规文本"

    def test_strips_markdown_decorations(self):
        assert _derive("### 视频核心主题\n**床车露营看日出，治愈系开场**") == "床车露营看日出，治愈系开场"
        assert _derive("### 视频核心主题\n### 人物") == "人物"
        assert _derive("### 视频核心主题\n主题：床车露营") == "床车露营"

    def test_truncates_to_24(self):
        assert len(_derive("### 视频核心主题\n" + "很" * 40)) == 24

    def test_empty_returns_none(self):
        assert _derive("") is None
        assert _derive(None) is None
