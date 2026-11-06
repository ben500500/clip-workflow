"""风险词表合并口径单测（app/services/asset_service.py）。

为什么单独测这两个函数：审核/投产的闸门和「配置页看到的词表」必须**永远是同一份**。
以前合并逻辑只内联在 API 层一处，配置页若另写一份，运营加的词会看着生效、实际没拦。
所以把合并抽成 `merge_risk_config` / `effective_risk_words`，这里钉住它的行为：

1. `inherit=true`（缺省）＝在默认表上**追加**，默认词不许被悄悄清空；
2. `inherit=false` ＝整体替换（默认词不再拦人）；
3. 豁免正则：inherit=true 时与默认豁免**合并**，false 时只认自己配的；
4. 词表整体为空 → 回落内置默认表（**不能变成全放行**）；
5. 未知级别 → 并入 block（宁可多拦不可漏）。

运行：cd backend && python -m pytest tests/unit/test_asset_risk_lexicon.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_asset_risk.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.services import asset_service as svc


def test_no_config_means_default_table():
    """没配过 → 生效词表就是内置默认表（block 至少含「砍死」，warn 至少含「第一」）。"""
    book, exempt = svc.effective_risk_words(None)
    assert "砍死" in book["block"]
    assert "第一" in book["warn"]
    # 默认豁免也要在：不然「第一次」会被「第一」误伤
    assert "第一" in exempt


def test_inherit_true_appends_to_default():
    """inherit=true（缺省）：运营加的词**追加**在默认表之后，默认词不许被清掉。"""
    book, _ = svc.effective_risk_words({"block": ["新禁词"], "warn": ["新警词"]})
    assert "新禁词" in book["block"]
    assert "新警词" in book["warn"]
    assert "砍死" in book["block"], "默认表必须还在"
    assert "第一" in book["warn"]


def test_inherit_false_replaces_default_table():
    """inherit=false：整体替换，默认词不再拦人（这是运营明确表达「这些不算风险」）。"""
    book, _ = svc.effective_risk_words(
        {"block": ["只有这个词"], "warn": [], "inherit": False}
    )
    assert book["block"] == ["只有这个词"]
    assert "砍死" not in book["block"]


def test_empty_table_falls_back_to_default_never_all_pass():
    """把词表清空**不等于**放行：normalize 会回落默认表（宁可多拦，不能因配置写错变全放行）。"""
    book, _ = svc.effective_risk_words({"block": [], "warn": [], "inherit": False})
    assert "砍死" in book["block"], "清空词表必须回落默认表，不许变成什么都不拦"


def test_exempt_merges_with_default_when_inherit():
    """inherit=true 时豁免也要合并（默认的「第一」豁免不能被运营的配置挤掉）。"""
    _book, exempt = svc.effective_risk_words({"exempt": {"第一": "第一次|第一眼"}})
    assert "第一" in exempt
    assert "史上" in exempt, "默认豁免必须还在"
    assert exempt["第一"] == "第一次|第一眼", "运营写的同名豁免要覆盖默认值"


def test_exempt_replaced_when_not_inherit():
    """inherit=false 时豁免只认自己配的。"""
    _book, exempt = svc.effective_risk_words(
        {"exempt": {"第一": "第一次"}, "inherit": False}
    )
    assert "史上" not in exempt
    assert exempt["第一"] == "第一次"


def test_unknown_level_falls_into_block():
    """级别写错（比如把词放进 'warning'）不能变成「没人管」——一律并入 block。"""
    lexicon, _exempt = svc.merge_risk_config({"warning": ["写错级别的词"]})
    book, _compiled = svc.normalize_risk_lexicon(lexicon, None)
    # 「warning」不是合法级别，normalize 会把未知级别的词并进 block
    assert "写错级别的词" in book["block"]
    assert "写错级别的词" not in book["warn"]


def test_invalid_exempt_regex_is_ignored_not_crashing():
    """豁免正则写坏 → 忽略这条豁免（不能把整个词表搞挂）。"""
    lexicon, exempt = svc.merge_risk_config({"exempt": {"坏正则": "([a-z"}})
    book, compiled = svc.normalize_risk_lexicon(lexicon, exempt)
    assert "砍死" in book["block"]
    assert "坏正则" not in compiled
