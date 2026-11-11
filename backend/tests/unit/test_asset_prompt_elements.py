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
    """**只**要这几行，不并出厂表（出厂表由 `merge_catalog` 负责）——认元素/替换的断言要
    isolated，不然正文里别的行每次都命中，断言写成"只有一个槽位"必假。"""
    return pe.normalize_catalog({"slots": [dict(r) for r in rows]})


def _slot(key, **kw):
    base = {"key": key, "label": kw.pop("label", key), "pool": [], "anchors": [], "categories": []}
    base.update(kw)
    return base


# ─────────────────  字典：规整 / 合并 / 清洗  ─────────────────

def test_defaults_are_exactly_the_prototype_rows_from_the_reference_doc():
    """出厂表＝用户那份《钩子模版换皮参数设定.docx》里 A–F 的参数项，**键不许撞、也不许多东西**。

    11-10 用户拍板「两行都从默认字典去掉」：`genre`（题材标签）与 `drama_name`（剧名）是我
    从投产模板 ① 行自己加的，参考文件里没有这两项，所以它们**不许再出现在默认表里**——
    这一条是负向断言，防止哪天又"顺手"把剧名做成可换项（换了剧名＝让豆包参考另一部真剧）。
    """
    cat = pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS)
    keys = {s["key"] for s in cat}
    assert not ({"genre", "drama_name"} & keys), f"出厂表多了参考文件里没有的行：{keys & {'genre', 'drama_name'}}"
    assert keys >= {
        "a_animal", "a_scene", "a_speech",
        "b_scene", "b_target", "b_secret",
        "c_scene", "c_treasure",
        "d_weak", "d_scene", "d_abuser", "d_line",
        "e_power", "e_scene",
        "f_plight", "f_power",
    }
    assert len(keys) == len(cat) == 16, "出厂表只该有这 16 行（A3/B3/C2/D4/E2/F2）"
    # 剩余槽位的认法都必须落到位（出厂表里已经没有 pattern 行了，这个循环是防将来加行时写漏）
    for slot in cat:
        if slot["mode"] == pe.MODE_PATTERN:
            assert slot["pattern"]
        elif slot["mode"] == pe.MODE_LITERAL:
            assert slot["anchors"] or slot["probe"]
        else:
            assert slot["mode"] == pe.MODE_MANUAL


# 《钩子模版换皮参数设定.docx》各原型「换皮变量」行里给了**词表**的那几项（斜杠段逐字照抄）。
# docx 没给词表的参数项不在这里：A 的「善举／神谕指令」、D 的「不公事实」、E 的「揭晓身份」、
# F 的三项都是整句或开放式取值；B 的「情报：股票/遗产/阴谋」走的是 `b_secret` 手填行
# （那一格要的是整句泄密内容，不是这三个词），manual 槽的 anchors 根本不参与识别，
# 塞进去只会让人往台词格里填半截词——判据见 `asset_prompt_elements` 顶部 8-25 批注。
DOCX_WORD_LISTS = {
    "a_animal": ["猫", "狗", "狐", "黄鼠狼", "孔雀", "鹰", "雕像", "佛像"],
    "b_scene": ["房梁", "引擎盖", "床底", "屋顶"],
    "b_target": ["老板", "对手", "亲戚"],
    "c_scene": ["老宅灶台", "枯井", "墙缝", "火葬场"],
    "c_treasure": ["金牙", "黄金碗", "金砖", "暗门金库"],
    "d_weak": ["老人", "孕妇", "婆婆", "妻子"],
    "d_abuser": ["儿媳", "丈夫", "长子"],
    "e_power": ["催生植物", "木耳双胞胎", "徒手神力"],
}

# docx 用单字「狐／鹰」，现网 11 处全写成整词（狐狸/白狐/猫头鹰/老鹰/神鹰/幼鹰）。
# 这批**不是新词**，是同一个业务指称的写法；登记它们只为了让长词面优先取到整词，
# 换掉之后不留「猫头雕」「…狸」这种残渣。除这批之外不许再往词表里塞自加词。
COMPOUND_FORMS = {"狐狸", "白狐", "猫头鹰", "老鹰", "神鹰", "幼鹰"}


def test_prototype_pools_are_the_docx_union_over_the_1110_list():
    """词表闸门（11-11 批 8-25 改写）。

    11-10 那版闸门是「照用户口述的三个词录入，一个不许加」；11-11 用户对着现网普查
    （88 条里只有 29 条认出过东西）拍板改成「按《钩子模版换皮参数设定.docx》补宽」。
    于是闸门从"卡死不许变"换成**三条同时成立**：
      ① docx 每行「换皮变量」里的词**必须在**（补宽不许漏）；
      ② 11-10 那批词一个不许掉（现网历史稿的实际写法，删了＝把已认出的改回认不出）；
      ③ 表里除了 ①② 和 `COMPOUND_FORMS` 之外**不许有别的词**——想自加业务词，
         必须先把它写进 docx 或者在元素库抽屉里由运营自己加（PUT 口，不用发版）。
    """
    by_key = {s["key"]: s for s in pe.normalize_catalog(pe.PROTOTYPE_PROMPT_ELEMENTS)}
    legacy_1110 = {
        "a_animal": ["猫", "狗", "黄鼠狼"],
        "a_scene": ["建筑工地", "繁华大街", "河边"],
        "b_scene": ["房梁", "床底", "衣柜"],
        "b_target": ["丈夫", "老板", "亲戚"],
        "c_scene": ["枯井", "暗道", "火葬场", "坟墓", "海底"],
        "c_treasure": ["黄金", "金碗", "金砖", "金牙"],
        "d_weak": ["老人", "孕妇", "妻子", "儿媳"],
        "d_scene": ["家庭", "公司", "大街"],
        "d_abuser": ["丈夫", "婆婆", "公公"],
        "e_power": ["催生植物", "眼发金光", "一口吸干河水"],
        "e_scene": ["山里", "河边", "海边"],
        "f_power": ["徒手拦车", "徒手接坠楼者"],
    }
    for key, words in DOCX_WORD_LISTS.items():
        assert set(words) <= set(by_key[key]["pool"]), \
            f"{key} 漏了设定表里的词：{set(words) - set(by_key[key]['pool'])}"
    for key, words in legacy_1110.items():
        assert set(words) <= set(by_key[key]["pool"]), \
            f"{key} 把 11-10 现网在用的词删掉了：{set(words) - set(by_key[key]['pool'])}"
    # 表里不许出现 ①②/整词形态之外的自加词（场景行也一并管：词面短了还有 probe 认位置，
    # 但"多出来一个 docx 没有的名词"同样要在这里被拦住）
    for key, slot in by_key.items():
        if slot["mode"] != pe.MODE_LITERAL:
            continue
        base = set(DOCX_WORD_LISTS.get(key, [])) | set(legacy_1110.get(key, []))
        extra = set(slot["pool"]) - base
        assert extra <= COMPOUND_FORMS, f"{key} 出现了自加词：{extra - COMPOUND_FORMS}"
    # 词面与候选必须同源（候选就是拿去正文里找的那批词）
    for key, slot in by_key.items():
        if slot["mode"] == pe.MODE_LITERAL:
            assert slot["anchors"] == slot["pool"], f"{key} 的词面与候选不是同一批"
    # 整句那四项不许有词面（间接转述，认不出就是认不出）
    for key in ("a_speech", "b_secret", "d_line", "f_plight"):
        assert by_key[key]["mode"] == pe.MODE_MANUAL, f"{key} 该是手填项"
        assert by_key[key]["anchors"] == []


def test_animal_compound_forms_win_over_the_single_char():
    """docx 写「狐／鹰」是单字，但**认半截会产出坏稿**：值拿去逐字全局替换，
    把「猫头鹰」认成「鹰」再换成雕，稿子里就剩「猫头雕」。
    所以词表登记了整词形态，靠 `_matches_for_anchors` 的长词面优先取整词。
    """
    slot = next(s for s in pe.normalize_catalog(pe.PROTOTYPE_PROMPT_ELEMENTS) if s["key"] == "a_animal")
    body = "剧情：【前3秒】院子里，一只猫头鹰突然开口劝他别上那辆车。\n镜头：猫头鹰转身。"
    assert [h["value"] for h in pe.slot_matches(body, slot)] == ["猫头鹰", "猫头鹰"], \
        "整词必须赢，且不许同时冒出「鹰」「猫」两行"
    body2 = "剧情：山上，一只白狐开口报恩。"
    assert [h["value"] for h in pe.slot_matches(body2, slot)] == ["白狐"]
    # 真正独立出现的单字照旧认（docx 那个词本身还在表里）
    assert [h["value"] for h in pe.slot_matches("剧情：一只狐蹲在门口。", slot)] == ["狐"]


def test_line_one_is_not_an_element_but_is_still_protected():
    """① 行不再做成可换项（11-10 拍板），但它**整行仍然受保护**。

    撤槽位 ≠ 撤保护：`DEFAULT_SKIP_LINES` 与槽位表无关，换动物/换人时那行里的《剧名》
    一个字都不许被顺手带走——那等于让豆包参考另一部真剧。
    """
    cat = pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS)
    rows = pe.extract_elements(PROMPT_10S, cat)
    assert not [e for e in rows if e["current"] == "现言豪门"], "① 行的题材标签不该再被认成元素"
    assert not [e for e in rows if e["current"] == "一碗疙瘩汤成少爷后妈"], "剧名不该是可换项"
    text, rep, _notes = pe.apply_edits(PROMPT_10S, cat, [{"key": "d_weak", "from": "婆婆", "to": "嫂子"}])
    assert rep[0]["count"] == 1, "剧情行里的弱势对象照换"
    assert "生成【现言豪门】" in text and "《一碗疙瘩汤成少爷后妈》" in text


def test_extract_returns_the_source_line_so_people_can_compare():
    """用户口径（11-10）「把原提示词中对应的内容也放出来，这样可以做一个对比」。

    只给「当前：橘猫」看不出它是哪句里的哪个成分，所以每个认出来的元素要带命中那行原文；
    手填项本来就不认值，`context` 必须如实为空，不许编一段上下文出来。
    """
    cat = _only(
        _slot("animal", label="出场的动物", anchors=["橘猫"], pool=["橘猫", "鹦鹉"]),
        _slot("line", label="说的一句话", mode=pe.MODE_MANUAL),
    )
    rows = {e["key"]: e for e in pe.extract_elements(PROMPT_10S, cat)}
    assert rows["animal"]["context"].startswith("剧情：") and "橘猫" in rows["animal"]["context"]
    assert rows["line"]["current"] is None and rows["line"]["context"] == ""
    # 长行要截断加省略号，不然界面一行铺出去几十个字
    long_line = "剧情：" + "很" * 400
    got = pe.extract_elements(long_line, _only(_slot("s", anchors=["很"])))
    assert got[0]["context"].endswith("…") and len(got[0]["context"]) <= pe.MAX_CONTEXT_LEN + 1


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
    cat = _catalog(_slot("a_scene", pool=["建筑工地", "老家堂屋"]))
    keys = [s["key"] for s in cat]
    assert "a_animal" in keys, "追加模式下出厂其它槽位必须还在"
    scene = next(s for s in cat if s["key"] == "a_scene")
    assert scene["pool"] == ["建筑工地", "老家堂屋"], "同键覆盖：出厂那行被配了候选的那行顶掉"


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
    assert {s["key"] for s in eff} >= {"s", "a_animal"}, "合并逻辑在脏数据下仍然给出可用表"


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
    """① 行那两项默认字典里已不再有，但运营自己照这个写法配一行，pattern 模式照样换得动。"""
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


# ─────────────────  批 N：手填项 / 受保护行 / 位置识别  ─────────────────
# 这篇是照**现网真稿**的骨架写的（11-10 从 163 库里取样核对过）：
# ① 行里带着《剧名》，钩子原文那行是过审的那句话，剧情行开头是场景句，
# 台词是**间接转述**（「催他下水求财」）而不是带引号的原话。少一行就测不到相应那条判据。

PROMPT_A = "\n".join([
    "【第 3 段 · 建议 10 秒 · 本钩共 6 条 · 编号 8PZXGA1】",
    "钩子原文：我家猫开口了，说门口那人不干净",
    "生成【都市脑洞】仿真人写实短剧，参考【《鲸鱼开口指路跳海》】剧情，"
    "输入素材为 AI 多视图角色设定卡，严格参考锁定男女主五官。",
    "时长 10 秒，9:16 竖屏，模拟手机竖屏实拍短剧影视质感。",
    "剧情：【前3秒】建筑工地的水泥管边，一只黄鼠狼开口催他下水求财。"
    "【后7秒】河边，男人照做，捞出一只木箱。",
    "镜头：自动匹配剧情对应场景，工地拦费用侧四十五度中近景。",
    "负面约束：禁止五官崩坏变脸。 9:16，10s",
])

CAT_A = "原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）"


def _cat():
    return pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS)


def test_protected_lines_are_not_touched_by_animal_replace():
    """换动物绝不能把 ① 行的《剧名》换掉——那等于换成了另一部剧（现网实测的形状）。"""
    cat = _cat()
    text, rep, _notes = pe.apply_edits(PROMPT_A, cat, [{"key": "a_animal", "from": "鲸鱼", "to": "猫"}])
    assert "《鲸鱼开口指路跳海》" in text, "剧名一个字都不许动"
    assert rep[0]["count"] == 0, "唯一的命中在受保护行里，这一条就是没改"


def test_protected_hook_copy_is_reported_not_silently_skipped():
    """猫在钩子原文（过审那句）和剧情行各有一次：剧情行换掉、钩子行不动，并且当场说清楚。"""
    cat = _cat()
    text, rep, notes = pe.apply_edits(PROMPT_A, cat, [{"key": "a_animal", "from": "猫", "to": "狗"}])
    hook_line = next(line for line in text.splitlines() if line.startswith("钩子原文"))
    story_line = next(line for line in text.splitlines() if line.startswith("剧情"))
    assert "我家猫开口了" in hook_line, "过审那句不许被元素替换改掉"
    assert "一只黄鼠狼" in story_line
    assert rep[0]["count"] == 0
    assert any("受保护行" in n for n in notes), "没改的地方必须点名，别让人以为换上了"


def test_explicit_empty_skip_lines_reopens_the_protected_lines():
    """槽位自己写 skip_lines=""＝允许碰那两行（运营明确要改剧名时的正路，不用改代码）。"""
    cat = pe.normalize_catalog({"slots": [{
        "key": "beast", "label": "牲口", "mode": pe.MODE_LITERAL,
        "anchors": ["鲸鱼"], "skip_lines": "",
    }]})
    text, rep, _notes = pe.apply_edits(PROMPT_A, cat, [{"key": "beast", "from": "鲸鱼", "to": "白鳍豚"}])
    assert rep[0]["count"] == 1 and "《白鳍豚开口指路跳海》" in text


def test_scene_is_recognised_by_position_even_when_the_word_list_misses_it():
    """「自动提取原脚本中的参数」：场景认的是「剧情：」后第一段这个**位置**，不是词表。
    现网稿子里写的是「普通民居客厅」，词表里一个都没有，照样要认出来。"""
    body = PROMPT_A.replace("建筑工地的水泥管边", "普通民居客厅")
    got = {e["key"]: e for e in pe.extract_elements(body, _cat(), CAT_A)}
    assert got["a_scene"]["current"] == "普通民居客厅"
    # 词表命中时给词表那个短值（拿去全文替换更准），位置识别不重复占同一段
    got2 = {e["key"]: e for e in pe.extract_elements(PROMPT_A, _cat(), CAT_A)}
    assert got2["a_scene"]["current"] == "建筑工地"


def test_scene_probe_skips_a_leading_question_sentence():
    """现网实拍（8PZY7／8QZYV，11-11 唯一一次花钱的 guess-values 对照出来的）：
    ③行以**问话**起手时，问句不是场景。这一格的值是拿去逐字全局替换的，
    认错的后果不是"提示不准"，是照它换会把开场那句问话整句换掉。"""
    tagged = PROMPT_A.replace(
        "剧情：【前3秒】建筑工地的水泥管边，一只黄鼠狼开口催他下水求财。",
        "剧情：【疑问起手】女首富为什么蹲在池塘边给一只孔雀敷药？"
        "清晨的普通庭院池塘边，儿媳一把攥住孔雀尾羽拔下。",
    )
    plain = PROMPT_A.replace(
        "剧情：【前3秒】建筑工地的水泥管边，一只黄鼠狼开口催他下水求财。",
        "剧情：谁把床上的人换掉了？深夜的普通家庭卧室，丈夫给熟睡的妻子擦脸。",
    )
    assert _scene_current(tagged) == "清晨的普通庭院池塘边"
    assert _scene_current(plain) == "深夜的普通家庭卧室"
    # 反向：问句里的字不许当成场景值出现在替换起点上（老写法就是栽在这两条上）
    assert "为什么" not in _scene_current(tagged)
    assert "谁把床上" not in _scene_current(plain)


def test_scene_probe_refuses_to_cut_a_lead_sentence_in_half():
    """超过 24 字的场景段**认不出**，而不是给半句：老写法截出过「清晨的普通」这种尾巴，
    人照半句去全文替换会命中不到／命中到别处，比留空更坏（留空界面会走「原稿里没认出」白话）。"""
    overlong = "剧情：" + "房" * 30 + "，男人推门。"
    assert _scene_current(overlong, include_unmatched=True) is None
    # 恰好卡在 24 字且以逗号收尾＝正常认出（上限没被 lookahead 收紧成"只认短句"）
    assert _scene_current("剧情：" + "房" * 24 + "，男人推门。") == "房" * 24
    # 只有问话、后面没有场景段 → 认不出，且**不许跨行**去④「镜头：」那行开头捞
    only_question = "剧情：为什么？\n镜头：自动匹配剧情对应场景。"
    assert _scene_current(only_question, include_unmatched=True) is None


def _scene_current(body: str, include_unmatched: bool = False):
    got = {e["key"]: e for e in pe.extract_elements(body, _cat(), CAT_A, include_unmatched)}
    return got.get("a_scene", {}).get("current")


def test_manual_speech_row_is_always_listed_and_replaces_a_whole_sentence():
    """用户口径「所有可替换参数由手动输入」＋台词没法认：这一行永远摆出来，
    原句由人从稿子里复制，换的时候按整句走（60 字的词面帽儿会把它截成半句话）。"""
    rows = {e["key"]: e for e in pe.extract_elements(PROMPT_A, _cat(), CAT_A)}
    speech = rows["a_speech"]
    assert speech["mode"] == pe.MODE_MANUAL and speech["current"] is None
    assert "请从稿子里复制" in speech["note"], "要如实说认不出，别让人以为系统已经填好了"
    long_old = ("一只黄鼠狼开口催他下水求财，说这管子底下埋着他爹留下的三箱货，"
                "还说只要他把管子推开就别再回这个工地干活，说完就钻进了水泥管里再没出来")
    long_new = ("一只猫开口让他别上门口那辆车，说司机身上有股土腥味，"
                "还说这车昨天刚拉过一口棺材，说完就跳上了料堆冲着他眯了眯眼")
    body = PROMPT_A.replace("剧情：【前3秒】建筑工地的水泥管边，一只黄鼠狼开口催他下水求财。",
                            f"剧情：【前3秒】建筑工地的水泥管边，{long_old}。")
    text, rep, _notes = pe.apply_edits(body, _cat(), [{"key": "a_speech", "from": long_old, "to": long_new}])
    assert len(long_old) > pe.MAX_ANCHOR_LEN, "这句要比词面上限长，才测得出帽儿放宽了"
    assert long_new in text and long_old not in text
    assert rep[0]["count"] == 1


def test_extract_with_unmatched_lists_every_parameter_of_the_prototype():
    """④开单屏要的是「这一原型该设的参数全摆出来」，认不出原值的 current=None（批 O 的前端口）。"""
    rows = pe.extract_elements("", _cat(), CAT_A, include_unmatched=True)
    keys = {r["key"] for r in rows}
    assert {"a_animal", "a_scene", "a_speech"} <= keys
    assert not ({"genre", "drama_name"} & keys), "① 行那两项已按用户口径从默认字典去掉"
    assert all(r["current"] is None for r in rows if r["key"] in {"a_animal", "a_scene", "a_speech"})
    assert not any(r["key"].startswith("d_") for r in rows), "原型 D 的参数不该出现在 A 的单子上"


def test_category_matches_on_the_short_prototype_code():
    """字典里原型名是一句长话，界面只传「原型 A」时槽位不许集体消失。"""
    rows = pe.extract_elements(PROMPT_A, _cat(), "原型 A")
    assert {r["key"] for r in rows} >= {"a_animal", "a_scene", "a_speech"}
    assert pe.slot_applies({"categories": ["原型 A"]}, CAT_A) is True
    assert pe.slot_applies({"categories": ["原型 A"]}, "原型 B：偷听泄密（获取关键情报）") is False


def test_normalize_keeps_manual_slot_without_any_words():
    cat = pe.normalize_catalog({"slots": [{"key": "line", "label": "一句话", "mode": pe.MODE_MANUAL}]})
    assert [s["key"] for s in cat] == ["line"], "手填项不需要词面也不需要候选，这行就是要人填"
    assert cat[0]["skip_lines"] == pe.DEFAULT_SKIP_LINES


def test_bad_probe_keeps_the_word_list_and_only_drops_the_position():
    """位置写法编不过时只丢位置：词表那条路还在，别让一行坏正则把整个槽位吃掉。"""
    cat = pe.normalize_catalog({"slots": [{
        "key": "scene", "label": "场景", "mode": pe.MODE_LITERAL,
        "pool": ["河边"], "probe": "剧情：(?:(",
    }]})
    assert cat and cat[0]["probe"] == ""
    assert [h["value"] for h in pe.slot_matches(PROMPT_A, cat[0])] == ["河边"]


# ─────────────────  批 N：多值展开（按行配对／全组合）  ─────────────────

def test_expand_matrix_zip_pairs_rows_and_broadcasts_single_values():
    rows, notes = pe.expand_matrix(
        {
            "a_scene": ["河边", "建筑工地", "繁华大街"],
            "a_animal": ["猫"],
            "a_speech": ["说别上车", "说快跑", "说那人不干净"],
        },
        pe.MATRIX_ZIP,
        {"a_scene": "场景", "a_animal": "动物", "a_speech": "说的话"},
    )
    assert len(rows) == 3
    assert [r["a_scene"] for r in rows] == ["河边", "建筑工地", "繁华大街"]
    assert all(r["a_animal"] == "猫" for r in rows), "只填一个值的参数每行复用"
    assert [r["a_speech"] for r in rows] == ["说别上车", "说快跑", "说那人不干净"]
    assert any("动物只填了一个值" in n for n in notes), "复用了什么要当场说清楚"


def test_expand_matrix_zip_refuses_uneven_columns_instead_of_guessing():
    import pytest
    with pytest.raises(ValueError) as exc:
        pe.expand_matrix({"a_scene": ["河边", "工地", "大街"], "a_animal": ["猫", "狗"]})
    assert "对不齐" in str(exc.value)


def test_expand_matrix_product_and_its_row_cap():
    rows, notes = pe.expand_matrix(
        {"a_scene": ["河边", "工地", "大街"], "a_animal": ["猫", "狗"]}, pe.MATRIX_PRODUCT,
    )
    assert len(rows) == 6 and {"河边", "工地"} <= {r["a_scene"] for r in rows}
    assert any("全组合" in n for n in notes)
    import pytest
    big = {"k1": [str(i) for i in range(11)], "k2": [str(i) for i in range(11)], "k3": ["x"]}
    with pytest.raises(ValueError) as exc:
        pe.expand_matrix(big, pe.MATRIX_PRODUCT)
    assert str(pe.MAX_MATRIX_ROWS) in str(exc.value)


def test_compose_variants_fans_rows_out_on_one_base_prompt():
    """一行一条正文，逐行替换、互不污染（这条过了，批 P 才敢往生产单上落）。"""
    cat = _cat()
    base = {"a_scene": "建筑工地", "a_animal": "黄鼠狼"}
    rows = [{"a_scene": "河边", "a_animal": "猫"}, {"a_scene": "繁华大街", "a_animal": "狗"}]
    out = pe.compose_variants(PROMPT_A, cat, base, rows, CAT_A)
    assert len(out) == 2 and [o["seq"] for o in out] == [1, 2]
    assert "河边" in out[0]["text"] and "繁华大街" not in out[0]["text"]
    assert "繁华大街" in out[1]["text"] and "河边" in out[1]["text"], "第 2 条只换场景，动物那条不动"
    assert out[0]["changed"] is True


def test_compose_variants_says_which_parameters_had_no_original_value():
    cat = _cat()
    out = pe.compose_variants(PROMPT_A, cat, {}, [{"a_speech": "说快跑"}], CAT_A)
    assert out[0]["missing"] == ["动物说的一句话"]
    assert out[0]["changed"] is False
    assert any("没有原值" in n for n in out[0]["notes"])


def test_manual_rows_always_tell_the_operator_the_engine_does_not_guess():
    """手填项的说明必须带「系统不猜」——出厂行只写了业务来意，一线看到空输入框会以为字典坏了。"""
    got = {s["key"]: s for s in pe.extract_elements(PROMPT_A, _cat(), "原型 F", True)}
    assert "不猜" in got["f_plight"]["note"]
    assert got["f_plight"]["note"].startswith("用户口径"), "运营写的那句说明不许被顶掉，只在后面补"


def test_manual_row_without_a_note_still_gets_the_how_to_fill_line():
    cat = _only(_slot("x_line", mode=pe.MODE_MANUAL))
    got = pe.extract_elements(PROMPT_A, cat)[0]
    assert got["note"] == pe.MANUAL_NOTE and got["current"] is None


# ─────────────  11-10「帮我提炼原值」：模型补位回来的原值，逐字校验才算数  ─────────────
# 这一段的分量全在**丢弃**那半边：模型一定会有编的时候，收错了就等于把《剧名》当场景换掉、
# 或者拿一个稿子里根本没有的词去换词（换不动，还留下一张看起来正常的单）。
# 所以每个"该丢"都单独钉一条，每个"该收"也钉一条——只测收不测丢，等于没测。

def _guess_slots(category=None):
    return pe.slots_for_guess(pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS), category)


def test_guess_slot_list_includes_the_manual_rows_and_carries_the_guard():
    """要提炼的清单**必须含手填项**（用户嫌累的正在那几行），还必须带 `skip_lines`。

    `skip_lines` 掉了＝校验拿不到保护行判据，于是"只在 ① 行出现过的词"会被当成有效原值收下来。
    """
    slots = {s["key"]: s for s in _guess_slots("原型 A")}
    assert {"a_animal", "a_scene", "a_speech"} <= set(slots), sorted(slots)
    assert slots["a_speech"]["mode"] == pe.MODE_MANUAL, "手填项不在这份清单里就白做了"
    assert slots["a_speech"]["skip_lines"] == pe.DEFAULT_SKIP_LINES
    assert "f_plight" not in slots, "限定别的原型的行不该混进这一型的清单"
    # 一批混着几种原型时前端不报原型 → 全部行并起来问（与 extract 不一样，是故意的：
    # 跟着滤就成了一屏空白＋一句"没配参数项"，而那明明是好几种原型各要各的参数）
    every = {s["key"] for s in _guess_slots()}
    assert {"a_speech", "f_plight"} <= every, sorted(every)


def test_guess_values_accepted_only_when_the_words_are_really_in_the_copy():
    """手填项的间接转述被模型原样抄回来 → 收；这是这一口存在的全部理由。"""
    slots = _guess_slots("原型 A")
    out = pe.accept_guessed_values(
        PROMPT_A, slots, [{"key": "a_speech", "value": " 催他下水求财 "}]
    )
    assert out["values"] == {"a_speech": "催他下水求财"}, out  # 只 strip 首尾，中间一字不动
    assert out["dropped"] == []


def test_guess_value_that_only_lives_in_a_protected_line_is_dropped():
    """「鲸鱼」只在 ① 生成【…】那行（剧名）里出现 → 抄得再像也不能收，那儿换不动。"""
    out = pe.accept_guessed_values(PROMPT_A, _guess_slots("原型 A"), [{"key": "a_animal", "value": "鲸鱼"}])
    assert out["values"] == {}, out
    assert len(out["dropped"]) == 1 and "不动的那两行" in out["dropped"][0], out["dropped"]


def test_invented_guess_value_is_dropped_with_a_different_sentence():
    """串在稿子里根本没有 → 说的是"找不到"，不是"在保护行里"（两种红的修法不一样）。"""
    out = pe.accept_guessed_values(
        PROMPT_A, _guess_slots("原型 A"), [{"key": "a_scene", "value": "深夜的写字楼茶水间"}]
    )
    assert out["values"] == {} and "找不到" in out["dropped"][0], out


def test_guess_value_for_an_unconfigured_key_is_dropped():
    slots = _guess_slots("原型 A")
    out = pe.accept_guessed_values(PROMPT_A, slots, [{"key": "mood", "value": "河边"}])
    assert out["values"] == {} and "没配" in out["dropped"][0], out


def test_second_guess_value_for_the_same_key_loses():
    """同键回两条只留第一条——换词一口只能有一个原值，留哪条都不该由模型掷硬币。"""
    out = pe.accept_guessed_values(
        PROMPT_A,
        _guess_slots("原型 A"),
        [{"key": "a_scene", "value": "建筑工地的水泥管边"}, {"key": "a_scene", "value": "河边"}],
    )
    assert out["values"] == {"a_scene": "建筑工地的水泥管边"}, out
    assert "回了两条" in out["dropped"][0], out


def test_overlong_guess_value_is_refused_before_it_hits_the_replace_gate():
    """抄回来一整段（>600 字）＝拿整篇稿子当"原值"，换词必然把全稿换掉：不收。"""
    long_text = PROMPT_A + "补" * (pe.MAX_MANUAL_VALUE_LEN + 1)
    out = pe.accept_guessed_values(
        long_text, _guess_slots("原型 A"), [{"key": "a_scene", "value": "补" * 700}]
    )
    assert out["values"] == {} and "超过" in out["dropped"][0], out


def test_guess_accept_says_so_when_there_is_nothing_to_ask():
    """没稿子／没清单不是"模型没活儿"，是这一屏没什么可提炼——界面要有一句人话。"""
    assert pe.accept_guessed_values("", _guess_slots("原型 A"), [])["dropped"]
    assert pe.accept_guessed_values(PROMPT_A, [], [{"key": "a_scene", "value": "河边"}])["dropped"]
    assert pe.slots_for_guess([], None) == []


# ── 批 Z（11-11）：认不出自动问模型，钱只能花一次 ────────────────────────────


def test_body_fingerprint_is_the_cache_key_and_changes_with_the_draft():
    """缓存键是**正文指纹**，不是 summary_id。

    三条都要成立，否则"只花一次钱"会变成"拿旧稿的词去新稿里换"：
    同文同键（跨行 id、跨生产单都命中同一份）、改一个字符就换键、空文也有稳定键（不炸）。
    """
    assert pe.body_fingerprint(PROMPT_A) == pe.body_fingerprint(PROMPT_A)
    assert pe.body_fingerprint(PROMPT_A) != pe.body_fingerprint(PROMPT_A + "补一句")
    assert pe.body_fingerprint(None) == pe.body_fingerprint("")
    assert len(pe.body_fingerprint(PROMPT_A)) == 64, "列宽 String(64)＝sha256 hex，别换成别的摘要"


def test_guess_batch_prefers_the_row_missing_the_most_slots():
    """分批是**确定**的，而且钱要花在缺得最多的那篇上。

    同一篇稿子读一遍是这一枪的固定开销：缺 3 格的那篇才是该问的，只缺 1 格的下次再说。
    排序规则一旦不确定（比如按 dict 遍历序），同一批稿子两次打开弹窗会问到不同的篇，
    钱花在哪没人说得清。
    """
    chosen, skipped = pe.select_guess_batch(
        {"a": ["x"], "b": ["x", "y", "z"], "c": ["y", "z"]},
        max_items=2,
        max_chars=10 ** 6,
    )
    assert chosen == ["b", "c"] and skipped == ["a"], (chosen, skipped)
    again, _ = pe.select_guess_batch(
        {"c": ["y", "z"], "b": ["x", "y", "z"], "a": ["x"]}, max_items=2, max_chars=10 ** 6
    )
    assert again == chosen, "同样的缺法必须问同样的篇"


def test_guess_batch_never_drops_everything_and_stays_inside_the_budget():
    """一次问不完时分两种情况，两种都不许出现"一篇都不问"。

    - 只有一篇、且它本身就超字数预算 → **照样问**（它缺的那格正是人卡住的地方，
      宁可这一枪超预算，也不能让界面回一句"没提炼到"其实一枪都没打）；
    - 一篇超长＋几篇短的 → 按预算装得下的那几篇先问，超长的这篇留到下次；
    - 篇数超上限 → 只少几篇，不是全都别问。
    """
    only_big, skipped = pe.select_guess_batch(
        {"big": ["x"]}, max_items=5, max_chars=1000, char_of=lambda _t: 9999
    )
    assert only_big == ["big"] and skipped == [], "唯一该问的一篇不许被字数预算挡掉"

    chosen, skipped = pe.select_guess_batch(
        {"big": ["x"], "s1": ["x"], "s2": ["x"]},
        max_items=5,
        max_chars=1000,
        char_of=lambda t: {"big": 9999, "s1": 10, "s2": 10}[t],
    )
    assert chosen == ["s1", "s2"] and skipped == ["big"], (chosen, skipped)

    chosen2, _ = pe.select_guess_batch(
        {t: ["x"] for t in "abcdef"}, max_items=pe.GUESS_MAX_ITEMS, max_chars=pe.GUESS_MAX_TOTAL_CHARS
    )
    assert len(chosen2) == pe.GUESS_MAX_ITEMS, "超篇数只该少几篇，不是全都别问"
