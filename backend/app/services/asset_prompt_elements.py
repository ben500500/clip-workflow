"""投产前的「可替换元素」引擎（批 M，2026-11-10 用户口径）。

用户原话：「文案最终去投产豆包的时候，在确认投产之前，需要对提示词进行修改编辑。
后面我会根据每一种钩子的类型给你提供几个元素，这几个元素是出现在提示词当中的，
比如场景是什么，或者里面出现的某种动物是什么。这些元素在最终投产之前是可以进行替换的。
我需要你首先对这些元素进行一个裂变，给出几种选择，当然还可以进行自定义输入……
最终在可替换元素选择完之后的完整版提示词，也是要一份可完整编辑的状态，确认之后才可以进行生产。」

所以这一层的职责只有三件，**都不花钱、都不落库**：

1. **认出元素**（`extract_elements`）——在提示词正文里把「有得换的东西」找出来，
   给出当前值和它出现了几次；
2. **给几个选择**（候选＝字典里这个槽位的 `pool`，即"裂变"）——池子还没配时
   界面照旧留「自定义输入」，功能不断档；
3. **换完再拼回整段**（`apply_edits`）——返回**完整可编辑的正文**，
   人在这份正文上按「确认投产」才走既有 `prompt_overrides` 通道。

三条边界，是这套设计的关键，不是装饰：

- **元素字典是数据，不是代码。** 用户后面会按钩子类型给元素清单，那时只改
  `system_config.asset_prompt_elements`（元素库抽屉／PUT 口），不用发版。
  槽位有两种认法：`literal`（在正文里逐字找给定词面，适合"场景/动物/道具"这类
  写在③剧情自由文本里的东西）和 `pattern`（带捕获组的正则，适合①那种
  模板保证存在、且**只能在原地处改**的位置）。
- **不改库里的原稿。** 组出来的正文只作为「这一次投出去的」投递稿走
  `DispatchRequest.prompt_overrides`（11-06 拍板），`prompt_text`／过审文案一字不动；
  漂移判定不受影响，下一轮再投仍是原稿。改后的正文照走 block 级风险词重扫。
- **pattern 槽位只在命中处替换。** 时长这类参数在②⑦⑩⑬ 四处必须一致
  （模板自查第③条硬要求），所以绝不用全局字面替换去动 "10"——
  引擎只在 pattern 命中的那个捕获组里换，换了几处照实回报。

`literal` 槽位是全局逐字替换（把「老破小客厅」换成「出租屋客厅」应当三处都换），
命中了几处、没找到哪一条，都在返回值里点名，界面复述给人看。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROMPT_ELEMENTS_CONFIG_KEY = "asset_prompt_elements"

MODE_LITERAL = "literal"
MODE_PATTERN = "pattern"
SLOT_MODES = (MODE_LITERAL, MODE_PATTERN)

# 防呆上限：元素是"词组"，不是一整段文档
MAX_ANCHOR_LEN = 60
MAX_VALUE_LEN = 200
MAX_POOL_PER_SLOT = 20
MAX_PATTERN_LEN = 300
MAX_SLOTS = 60


# 出厂默认表：只有模板自己**保证存在**的两个位置（`autoclip/app/prompt/hook_prompt_web.txt` ①行）。
# pool 一律留空——场景/动物/道具这些元素要等用户给清单，我在这儿凭空写业务词就是"自己加设定"。
# 认得出、能自定义替换，界面从第一天就不断档，这就够了。
DEFAULT_PROMPT_ELEMENTS: List[Dict[str, Any]] = [
    {
        "key": "genre",
        "label": "题材标签",
        "mode": MODE_PATTERN,
        "pattern": r"生成【([^】]{1,12})】",
        "anchors": [],
        "pool": [],
        "categories": [],
        "note": "① 题材声明行。模板原文：「题材不是现言豪门时相应替换标签」，所以这里可以换。",
    },
    {
        "key": "drama_name",
        "label": "剧名",
        "mode": MODE_PATTERN,
        "pattern": r"参考【《([^》]{1,30})》】",
        "anchors": [],
        "pool": [],
        "categories": [],
        "note": "① 里的《剧名》。成片不念剧名，但换皮的时候顺手照抄一遍更稳。",
    },
]


def _clean_text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _clean_words(values: Any, limit: int, max_items: int) -> List[str]:
    """词面数组：去空、去重、保序（池子顺序就是界面上的推荐顺序，不许打乱）。"""
    out: List[str] = []
    for v in values or []:
        w = _clean_text(v, limit)
        if w and w not in out:
            out.append(w)
        if len(out) >= max_items:
            break
    return out


def normalize_slot(raw: Any) -> Optional[Dict[str, Any]]:
    """规整一个槽位；键或标签为空、两种认法都没内容、写法编不过 → 丢弃（并留日志）。

    丢弃而不是报错，是为了让"字典里有一行写坏了"不至于把整口接口打死；
    写入口（PUT）另有硬校验，会把坏写法当场 400 拒回去，不会让人以为存好了。
    """
    if not isinstance(raw, dict):
        return None
    key = _clean_text(raw.get("key"), 60)
    label = _clean_text(raw.get("label"), 40) or key
    if not key:
        return None
    mode = _clean_text(raw.get("mode"), 20)
    pattern = _clean_text(raw.get("pattern"), MAX_PATTERN_LEN)
    anchors = _clean_words(raw.get("anchors"), MAX_ANCHOR_LEN, MAX_POOL_PER_SLOT)
    pool = _clean_words(raw.get("pool"), MAX_VALUE_LEN, MAX_POOL_PER_SLOT)
    if mode not in SLOT_MODES:
        # 没写认法时按"有没有正则"推断：给了 pattern 就是 pattern 槽位
        mode = MODE_PATTERN if pattern else MODE_LITERAL
    if mode == MODE_PATTERN and not pattern:
        mode = MODE_LITERAL
    if mode == MODE_PATTERN:
        if compile_error(pattern) is not None:
            logger.warning("元素槽位 %s 的识别写法无效，已忽略该槽位：%s", key, pattern)
            return None
        # pattern 槽位靠捕获组认值：pool 空只意味着"没有推荐候选"，槽位仍然可用
    elif not anchors and not pool:
        logger.warning("元素槽位 %s 既没给词面也没给候选，认不出任何东西，已忽略", key)
        return None
    return {
        "key": key,
        "label": label,
        "mode": mode,
        # literal 槽位没单独给词面时，候选池就是拿去正文里找的词面
        "anchors": anchors or (pool if mode == MODE_LITERAL else []),
        "pattern": pattern if mode == MODE_PATTERN else "",
        "pool": pool,
        "categories": _clean_words(raw.get("categories"), 60, MAX_POOL_PER_SLOT),
        "note": _clean_text(raw.get("note"), 200),
    }


def compile_error(pattern: str) -> Optional[str]:
    """正则写错了就返回人话原因，没写错返回 None。"""
    try:
        re.compile(pattern)
    except re.error as e:
        return str(e)
    return None


def normalize_catalog(raw: Any) -> List[Dict[str, Any]]:
    """整份字典规整：逐槽位清洗、键去重（**同键后写的覆盖先写的**，位置不动）、总条数封顶。

    "后写覆盖"与 `merge_catalog` 里"覆盖表顶掉出厂同键那行"是同一条规则，
    两处口径不一致就会出现"存进去的顺序和读出来的顺序说的不是一回事"。
    """
    rows: Any
    if isinstance(raw, dict):
        rows = raw.get("slots")
    else:
        rows = raw
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in rows or []:
        slot = normalize_slot(row)
        if slot is None:
            continue
        if slot["key"] not in by_key:
            order.append(slot["key"])
        by_key[slot["key"]] = slot
        if len(order) >= MAX_SLOTS:
            break
    return [by_key[k] for k in order]


def merge_catalog(value: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把 system_config 里的原始值合并成 (生效槽位, 覆盖槽位)。

    `inherit=true`（缺省）＝在**出厂默认表上追加/覆盖同键**；`inherit=false` ＝整体替换。
    与风险词库同一个三层口径：defaults／override／effective，
    目的是「元素库抽屉里看到的」和「抽元素接口实际认的」**永远是同一份**。
    """
    raw = value if isinstance(value, dict) else {}
    inherit = bool(raw.get("inherit", True))
    override = normalize_catalog(raw.get("slots"))
    if not inherit:
        return override, override
    by_key = {s["key"]: s for s in DEFAULT_PROMPT_ELEMENTS}
    ordered: List[Dict[str, Any]] = [dict(s) for s in DEFAULT_PROMPT_ELEMENTS]
    for slot in override:
        if slot["key"] in by_key:
            idx = next(i for i, s in enumerate(ordered) if s["key"] == slot["key"])
            ordered[idx] = slot
        else:
            ordered.append(slot)
    return ordered, override


def slot_applies(slot: Dict[str, Any], category: Optional[str]) -> bool:
    """槽位是否适用这一条。没限定就全适用；限定了就按钩子原型名/键对一下（大小写与空格不敏感）。"""
    cats = slot.get("categories") or []
    if not cats:
        return True
    if not category:
        return False
    want = str(category).strip().lower()
    return any(str(c).strip().lower() == want for c in cats)


def _matches_for_pattern(text: str, pattern: str) -> List[Dict[str, Any]]:
    """pattern 槽位：返回每个命中（捕获组 1 为当前值，没有组就用整个命中）。"""
    try:
        rx = re.compile(pattern)
    except re.error:
        return []
    out: List[Dict[str, Any]] = []
    for m in rx.finditer(text):
        value = m.group(1) if m.groups() else m.group(0)
        if value is None or not str(value).strip():
            continue
        if m.groups():
            start, end = m.span(1)
        else:
            start, end = m.span(0)
        out.append({"value": str(value), "start": start, "end": end, "span": (m.start(), m.end())})
    return out


def _matches_for_anchors(text: str, anchors: List[str]) -> List[Dict[str, Any]]:
    """literal 槽位：逐个词面在正文里逐字找。

    长词面优先且不重复占用同一段字符（词面表里既有「橘猫」又有「猫」时，
    「一只橘猫」只算「橘猫」命中一次，不会又算「猫」一次冒出两行）。
    """
    hits: List[Dict[str, Any]] = []
    taken: List[Tuple[int, int]] = []
    for anchor in sorted({a for a in anchors if a}, key=len, reverse=True):
        start = text.find(anchor)
        while start != -1:
            end = start + len(anchor)
            if not any(s <= start and end <= e for s, e in taken):
                taken.append((start, end))
                hits.append({"value": anchor, "start": start, "end": end, "span": (start, end)})
            start = text.find(anchor, end)
    hits.sort(key=lambda h: h["start"])
    return hits


def slot_matches(text: str, slot: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not text:
        return []
    if slot.get("mode") == MODE_PATTERN:
        return _matches_for_pattern(text, slot.get("pattern") or "")
    return _matches_for_anchors(text, list(slot.get("anchors") or []))


def extract_elements(
    text: Optional[str],
    catalog: List[Dict[str, Any]],
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """从一段提示词正文里认出可替换元素。

    返回 `[{key,label,mode,current,occurrences,pool,custom,categories,note}]`：
    `current` 是当前值（同槽位多个不同值时取第一个命中，`occurrences` 把每个值各出现几次说清），
    `pool` 是候选（裂变），`custom=true` 表示这一槽位允许自己填。
    认不出来的槽位不出现——界面只摆真换得动的东西，不摆一排空下拉。
    """
    body = text or ""
    out: List[Dict[str, Any]] = []
    for slot in catalog:
        if not slot_applies(slot, category):
            continue
        found = slot_matches(body, slot)
        if not found:
            continue
        counts: Dict[str, int] = {}
        for hit in found:
            counts[hit["value"]] = counts.get(hit["value"], 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        out.append({
            "key": slot["key"],
            "label": slot["label"],
            "mode": slot["mode"],
            "current": ordered[0][0],
            "occurrences": [{"value": v, "count": c} for v, c in ordered],
            "pool": list(slot.get("pool") or []),
            "custom": True,
            "categories": list(slot.get("categories") or []),
            "note": slot.get("note") or "",
        })
    return out


def _replace_spans(text: str, spans: List[Tuple[int, int]], to: str) -> str:
    """按 span 从后往前替换，避免前面的替换把后面的偏移搞乱。"""
    pieces = text
    for start, end in sorted(spans, key=lambda s: s[0], reverse=True):
        pieces = pieces[:start] + to + pieces[end:]
    return pieces


def apply_edits(
    text: Optional[str],
    catalog: List[Dict[str, Any]],
    edits: Optional[List[Dict[str, Any]]],
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """按人选的替换把整段正文组出来。

    `edits` 每条：`{key?, from?, to}`。
    - 带 `key` 且槽位是 pattern → **只在该槽位命中的捕获组里换**（`from` 再筛一道值），
      绝不全局替换数字，时长这类参数不会被顺手改到别的行；
    - 带 `key` 且槽位是 literal，或**不带 key（自定义输入）** → 逐字全局替换 `from` → `to`。

    返回 `(新正文, 逐条替换明细, 人话备注)`。明细里 `count=0` 表示原文里没这个词面、
    这一条没动——界面把它显式说出来，别让人以为换上了。
    """
    body = text or ""
    if not edits:
        return body, [], ["没给替换项，正文原样返回"]
    replaced: List[Dict[str, Any]] = []
    notes: List[str] = []
    by_key = {s["key"]: s for s in catalog}
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        to = _clean_text(edit.get("to"), MAX_VALUE_LEN)
        key = _clean_text(edit.get("key"), 60)
        raw_from = edit.get("from")
        slot = by_key.get(key) if key else None
        if slot is not None and slot.get("mode") == MODE_PATTERN and (raw_from is None or raw_from == ""):
            # pattern 槽位没点名值＝这个槽位的所有命中都换（例：把这条正文里所有【题材】标签换掉）
            spans = [
                (h["start"], h["end"]) for h in _matches_for_pattern(body, slot.get("pattern") or "")
            ]
            count = len(spans)
            if count:
                body = _replace_spans(body, spans, to)
            replaced.append({
                "key": key,
                "label": slot["label"],
                "mode": MODE_PATTERN,
                "from": "",
                "to": to,
                "count": count,
            })
            if not count:
                notes.append(f"「{slot['label']}」这一行没找到，没改（正文可能不照模板写）")
            continue
        src = _clean_text(raw_from, MAX_ANCHOR_LEN)
        if not src:
            notes.append("有一条替换没写「换掉什么」，已跳过")
            continue
        if not to:
            notes.append(f"「{src}」没写换成什么，已跳过")
            continue
        if src == to:
            notes.append(f"「{src}」换的还是它自己，没动")
            replaced.append({
                "key": key,
                "label": (slot or {}).get("label") or key or "自定义",
                "mode": (slot or {}).get("mode") or MODE_LITERAL,
                "from": src,
                "to": to,
                "count": 0,
            })
            continue
        if slot is not None and slot.get("mode") == MODE_PATTERN:
            hits = [h for h in _matches_for_pattern(body, slot.get("pattern") or "") if h["value"] == src]
            count = len(hits)
            if count:
                body = _replace_spans(body, [(h["start"], h["end"]) for h in hits], to)
        else:
            count = body.count(src)
            if count:
                body = body.replace(src, to)
        replaced.append({
            "key": key,
            "label": (slot or {}).get("label") or key or "自定义",
            "mode": (slot or {}).get("mode") or MODE_LITERAL,
            "from": src,
            "to": to,
            "count": count,
        })
        if not count:
            notes.append(f"原文里没找到「{src}」，这一条没改")
    if len(body) > 20000:
        notes.append(f"组完 {len(body)} 字，比投递稿长度上限还长，投板时会被拦，先删点")
    return body, replaced, notes
