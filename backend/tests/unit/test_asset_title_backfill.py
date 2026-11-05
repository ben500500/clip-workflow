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
        assert _derive(s) == "揭露假身份的冲突"

    def test_fallback_first_prose_line(self):
        assert _derive("这是一篇没有小节标记的详规文本\n第二行") == "这是一篇没有小节标记的详规文本"

    def test_strips_markdown_decorations(self):
        assert _derive("### 视频核心主题\n**床车露营看日出，治愈系开场**") == "床车露营看日出，治愈系开场"
        assert _derive("### 视频核心主题\n### 人物") is None  # 「人物」两字不成标题，宁缺勿滥
        assert _derive("### 视频核心主题\n主题：床车露营看日出，治愈开场") == "床车露营看日出，治愈开场"

    def test_truncates_to_24_when_no_punctuation(self):
        assert len(_derive("### 视频核心主题\n" + "很" * 40)) == 24

    def test_timestamp_script_body_used(self):
        # 分镜体详规：时间轴前缀剥掉后正文当标题
        assert _derive("00:00-00:03：画面为五人围坐在餐桌前吃饭，其中一位婆婆说话。") == "画面为五人围坐在餐桌前吃饭"

    def test_section_header_lines_never_become_title(self):
        assert _derive("### 视频拆解总结\n**人物设定**：") is None

    def test_empty_returns_none(self):
        assert _derive("") is None
        assert _derive(None) is None
