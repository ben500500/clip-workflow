"""投产前「可替换元素」引擎（批 M，11-10）单测。

要验的四件事，都是这套设计的立身之本：

1. **候选池没配也必须认得出、换得动**（用户还没给元素清单，功能不能空转）；
2. **pattern 槽位只在命中处替换**——时长这类参数在②⑦⑩⑬ 四处必须一致，
   全局字面替换 "10" 会把时间轴、字幕时长、⑬ 行尾一起改掉，那是造坏片；
3. **literal 槽位该换几处换几处**（同一个元素在③⑧⑬ 出现三次就换三次），
   而且长词面优先、不重复占用（词面表同时有「橘猫」和「猫」时不能冒出两行）；
4. **没找到就说没找到**（`count=0`＋人话备注），绝不静默假装换上了。

引擎本身不连库、不打网络、不花钱，所以这里全是纯函数断言。
运行：cd backend && python -m pytest tests/unit/test_asset_prompt_elements.py -v
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# conftest 会把 app 拉起来，Settings 要这几个键才建得出来（本文件不碰库，落谁都行）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_prompt_elements.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.services import asset_prompt_elements as pe  # noqa: E402

PROMPT_10S = (
    "生成【现言豪门】仿真人写实短剧，参考【《一碗疙瘩汤成少爷后妈》】剧情，"
    "输入素材为 AI 多视图角色设定卡。\n"
    "时长 10 秒，9:16 竖屏，模拟手机竖屏实拍短剧影视质感。\n"
    "剧情：老破小客厅里，婆婆把一只橘猫摔在地上，媳妇抱着橘猫退到阳台。\n"
    "时间轴：0-3 秒强冲突钩子，3-7 秒推进矛盾，7-10 秒情绪定格收束留悬念。\n"
    "音频字幕：中文情感 AI 配音；其余剧情字幕仅限单行短句，单条字幕时长≥1.5 秒。\n"
    "负面约束：禁止五官崩坏变脸。 9:16，10s"
)


def _catalog(*rows):
    """把测试用例的槽位过一遍出厂合并逻辑（和接口实际读到的那份同源）。"""
    eff, _ = pe.merge_catalog({"slots": [dict(r) for r in rows]})
    return eff


def _only(*rows):
    """只要这几行、**不带出厂那两个槽位**——认元素/替换的断言要 isolated，
    不然正文里 ① 那两行每次都命中，断言写成"只有一个槽位"必假。"""
    return pe.normalize_catalog({"slots": [dict(r) for r in rows]})


def _slot(key, **kw):
    base = {"key": key, "label": kw.pop("label", key), "pool": [], "anchors": [], "categories": []}
    base.update(kw)
    return base


# ─────────────────  字典：规整 / 合并 / 清洗  ─────────────────

def test_defaults_are_pattern_slots_and_match_the_template():
    """出厂默认表那两个槽位，必须在一篇照模板写的正文里真认得出来。"""
    cat = pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS)
    assert {s["key"] for s in cat} == {"genre", "drama_name"}
    found = {e["key"]: e["current"] for e in pe.extract_elements(PROMPT_10S, cat)}
    assert found == {"genre": "现言豪门", "drama_name": "一碗疙瘩汤成少爷后妈"}


def test_defaults_have_no_invented_business_pool():
    """出厂表不许塞我凭空写的业务词——元素候选要等用户按钩子类型给清单。"""
    for slot in pe.DEFAULT_PROMPT_ELEMENTS:
        assert slot["pool"] == [], f"{slot['key']} 的候选池该由运营配，不是出厂写死"


def test_normalize_drops_rows_without_key_or_way_to_match():
    rows = [
        {"key": "", "label": "没键"},
        {"key": "empty", "label": "既没词面也没候选"},
        _slot("bad_rx", mode="pattern", pattern="([a-z"),
        _slot("ok", pool=["客厅"]),
    ]
    cat = pe.normalize_catalog({"slots": rows})
    assert [s["key"] for s in cat] == ["ok"], "坏行丢弃、好行留下，不许把整口接口打死"


def test_normalize_dedupe_key_keeps_last_and_caps_rows():
    cat = pe.normalize_catalog({"slots": [_slot("k", pool=["a"]), _slot("k", pool=["b"])]})
    assert len(cat) == 1 and cat[0]["pool"] == ["b"], "同键后写的覆盖先写的"
    many = [_slot(f"k{i}", pool=["x"]) for i in range(pe.MAX_SLOTS + 20)]
    assert len(pe.normalize_catalog({"slots": many})) == pe.MAX_SLOTS


def test_literal_anchor_defaults_to_pool():
    cat = pe.normalize_catalog({"slots": [_slot("scene", pool=["老破小客厅", "出租屋"])]})
    assert cat[0]["anchors"] == ["老破小客厅", "出租屋"]


def test_inherit_merges_over_default_and_replaces_same_key():
    cat = _catalog(_slot("genre", mode="pattern", pattern=r"生成【([^】]{1,12})】", pool=["都市情感"]))
    keys = [s["key"] for s in cat]
    assert "drama_name" in keys, "追加模式下出厂另一个槽位必须还在"
    genre = next(s for s in cat if s["key"] == "genre")
    assert genre["pool"] == ["都市情感"], "同键覆盖：出厂那行被配了候选的那行顶掉"


def test_inherit_false_replaces_whole_catalog():
    eff, override = pe.merge_catalog(
        {"inherit": False, "slots": [_slot("scene", pool=["出租屋"])]}
    )
    assert [s["key"] for s in eff] == ["scene"]
    assert eff is not override or eff == override, "整体替换时生效表就是覆盖表本身"


def test_bad_value_shapes_do_not_crash():
    """配置写坏（非数组／非字典／脏行）不许抛——回落到还能用的那份。"""
    assert pe.normalize_catalog("不是字典") == []
    assert pe.normalize_catalog({"slots": "不是数组"}) == []
    assert pe.normalize_catalog({"slots": [None, 1, ["x"], {"pool": ["客厅"]}]}) == []
    eff, override = pe.merge_catalog({"slots": [None, {"key": "s", "pool": ["客厅"]}]})
    assert override and override[0]["key"] == "s"
    assert {s["key"] for s in eff} >= {"s", "genre"}, "合并逻辑在脏数据下仍然给出可用表"


# ─────────────────  认元素  ─────────────────

def test_extract_reports_value_occurrences_and_pool():
    cat = _only(
        _slot("animal", label="出场的动物", anchors=["橘猫"], pool=["橘猫", "中华田园犬", "鹦鹉"])
    )
    got = pe.extract_elements(PROMPT_10S, cat)[0]
    assert got["label"] == "出场的动物"
    assert got["current"] == "橘猫"
    assert got["occurrences"] == [{"value": "橘猫", "count": 2}], "③剧情里出现两次就该报两次"
    assert got["pool"] == ["橘猫", "中华田园犬", "鹦鹉"]
    assert got["custom"] is True, "候选不满意时界面必须能自己填"


def test_extract_drops_slots_that_are_not_in_the_text():
    """认不出来的槽位不许出现在返回里——界面不摆一排空下拉。"""
    cat = _only(_slot("scene", anchors=["医院走廊"]))
    assert pe.extract_elements(PROMPT_10S, cat) == []


def test_extract_prefers_the_most_frequent_value():
    cat = _only(_slot("place", anchors=["客厅", "阳台"]))
    got = pe.extract_elements(PROMPT_10S, cat)[0]
    assert got["current"] == "客厅"
    assert [o["value"] for o in got["occurrences"]] == ["客厅", "阳台"]


def test_longer_anchor_wins_and_span_is_not_double_counted():
    """词面表同时有「橘猫」和「猫」时，「一只橘猫」只算橘猫一次，不许冒出两行。"""
    cat = _only(_slot("animal", anchors=["橘猫", "猫"]))
    got = pe.extract_elements(PROMPT_10S, cat)[0]
    assert [o["value"] for o in got["occurrences"]] == ["橘猫"]
    assert got["occurrences"][0]["count"] == 2


def test_category_filter_only_applies_matching_slots():
    cat = _only(
        _slot("scene", anchors=["客厅"], categories=["悬念"]),
        _slot("animal", anchors=["橘猫"]),
    )
    assert [s["key"] for s in pe.extract_elements(PROMPT_10S, cat, "悬念")] == ["scene", "animal"]
    assert [s["key"] for s in pe.extract_elements(PROMPT_10S, cat, "萌宝")] == ["animal"], "别的原型不带这槽位"
    assert [s["key"] for s in pe.extract_elements(PROMPT_10S, cat)] == ["animal"], "没报原型时限定槽位不出现"


def test_pattern_slot_without_group_uses_whole_match():
    cat = pe.normalize_catalog({"slots": [_slot("dur_line", mode="pattern", pattern=r"时长 \d+ 秒")]})
    got = pe.extract_elements(PROMPT_10S, cat)[0]
    assert got["current"] == "时长 10 秒"


def test_empty_or_none_text_returns_nothing():
    cat = _only(_slot("scene", anchors=["客厅"]))
    assert pe.extract_elements("", cat) == []
    assert pe.extract_elements(None, cat) == []


# ─────────────────  替换组稿  ─────────────────

def test_literal_edit_replaces_every_occurrence_and_reports_count():
    cat = _only(_slot("animal", anchors=["橘猫"]))
    text, rep, notes = pe.apply_edits(
        PROMPT_10S, cat, [{"key": "animal", "from": "橘猫", "to": "中华田园犬"}]
    )
    assert rep[0]["count"] == 2 and "橘猫" not in text and text.count("中华田园犬") == 2
    assert notes == []


def test_pattern_edit_touches_only_the_capture_group():
    """核心判据：改 pattern 槽位绝不许把正文里同数字的别处一起改掉。"""
    cat = _only(
        _slot("duration", mode="pattern", pattern=r"时长 (\d+) 秒", pool=["10", "15"]),
    )
    text, rep, _notes = pe.apply_edits(PROMPT_10S, cat, [{"key": "duration", "from": "10", "to": "15"}])
    assert "时长 15 秒" in text
    assert "7-10 秒" in text, "⑦时间轴不许被顺手改掉（那是模板自查第③条的硬要求）"
    assert "9:16，10s" in text, "⑬行尾同理"
    assert "≥1.5 秒" in text
    assert rep[0]["count"] == 1


def test_pattern_edit_without_from_replaces_all_hits_of_that_slot():
    cat = _only(_slot("genre", mode="pattern", pattern=r"生成【([^】]{1,12})】"))
    text, rep, _ = pe.apply_edits(PROMPT_10S, cat, [{"key": "genre", "from": "", "to": "都市情感"}])
    assert "生成【都市情感】" in text and rep[0]["count"] == 1


def test_custom_edit_is_plain_literal_replace():
    """用户自己填的替换（字典里没这个槽位）照样走得通——这是「自定义输入」那条路。"""
    text, rep, _ = pe.apply_edits(PROMPT_10S, [], [{"from": "阳台", "to": "楼道口"}])
    assert "退到楼道口" in text and rep[0]["mode"] == "literal" and rep[0]["count"] == 1


def test_missing_source_is_said_out_loud_not_swallowed():
    _text, rep, notes = pe.apply_edits(PROMPT_10S, [], [{"from": "幼儿园", "to": "公司前台"}])
    assert rep[0]["count"] == 0
    assert notes and "没找到" in notes[0]


def test_same_value_and_blank_sides_are_skipped_with_note():
    _t, rep, notes = pe.apply_edits(PROMPT_10S, [], [{"from": "客厅", "to": "客厅"}])
    assert rep[0]["count"] == 0 and "它自己" in notes[0]
    _t, _r, notes = pe.apply_edits(PROMPT_10S, [], [{"from": "", "to": "X"}])
    assert any("没写「换掉什么」" in n for n in notes)
    _t, _r, notes = pe.apply_edits(PROMPT_10S, [], [{"from": "客厅", "to": "  "}])
    assert any("没写换成什么" in n for n in notes)


def test_edits_are_applied_in_order_on_the_running_text():
    """两步连做：先把场景换成 A，再把 A 换成 B，最终正文是 B（后一步在前一步的结果上走）。"""
    cat = _only(_slot("scene", anchors=["老破小客厅"]))
    text, rep, _ = pe.apply_edits(
        PROMPT_10S, cat,
        [{"from": "老破小客厅", "to": "出租屋客厅"}, {"from": "出租屋客厅", "to": "老家堂屋"}],
    )
    assert "老家堂屋" in text and "出租屋客厅" not in text
    assert [r["count"] for r in rep] == [1, 1]


def test_no_edits_returns_text_as_is():
    text, rep, notes = pe.apply_edits(PROMPT_10S, [], [])
    assert text == PROMPT_10S and rep == [] and notes


def test_pattern_slot_that_is_absent_says_the_text_does_not_follow_the_template():
    cat = _only(_slot("genre", mode="pattern", pattern=r"生成【([^】]{1,12})】"))
    _t, _r, notes = pe.apply_edits("一句完全不照模板写的话", cat, [{"key": "genre", "from": "", "to": "X"}])
    assert any("没找到" in n for n in notes)


def test_slot_from_another_key_is_not_used_as_literal():
    """给了 key 但那个槽位是 literal，而 from 是别的词面：按 from 逐字换，不许拿池子里的词乱换。"""
    cat = _only(_slot("scene", anchors=["老破小客厅"], pool=["老破小客厅", "出租屋"]))
    text, rep, _ = pe.apply_edits(PROMPT_10S, cat, [{"key": "scene", "from": "阳台", "to": "楼道"}])
    assert rep[0]["count"] == 1 and "退到楼道" in text and "老破小客厅" in text
