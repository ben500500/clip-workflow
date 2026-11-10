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

import itertools
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROMPT_ELEMENTS_CONFIG_KEY = "asset_prompt_elements"

MODE_LITERAL = "literal"
MODE_PATTERN = "pattern"
# 手填项（11-10 批 N）：真稿里「动物说的话／偷听到的内容／引爆台词」这类是**间接转述**
# （现网样例：「催他下水求财」「得意地说某只实业公司的股票即将疯涨」），没有引号形状可依赖，
# 硬编一个正则去认就是假认——界面照样列出这一项，但如实说「认不出原句，请从稿子里复制」。
MODE_MANUAL = "manual"
SLOT_MODES = (MODE_LITERAL, MODE_PATTERN, MODE_MANUAL)

# 防呆上限：元素是"词组"，不是一整段文档
MAX_ANCHOR_LEN = 60
MAX_VALUE_LEN = 200
MAX_POOL_PER_SLOT = 20
MAX_PATTERN_LEN = 300
MAX_MANUAL_VALUE_LEN = 600  # 手填项给的是整句（台词/泄密内容），比词面上限宽
MAX_SLOTS = 60
MAX_SKIP_PATTERN_LEN = 300
# 给界面摆「稿子里对应的原句」用的那一行有多长（11-10 用户口径：要能对着看）
MAX_CONTEXT_LEN = 160

# 默认跳过哪两行（批 N 的真坑）：现网 ① 行是
# `生成【都市脑洞】仿真人写实短剧，参考【《鲸鱼开口指路跳海》】…`——
# 换动物做全文替换会把**剧名**换成《猫开口指路跳海》，那是另一部剧；
# `钩子原文：` 那行是过审的那句话，动它就等于改了审核过的文案（投产复核会判漂移）。
# 所以除特殊槽位外，认与换都**不碰这两行**，界面把这句话原样说给投放人员。
DEFAULT_SKIP_LINES = r"^(钩子原文|生成【)"

# 多值扇出（批 N，用户口径「按行配对为主＋可切全组合」）
MATRIX_ZIP = "zip"
MATRIX_PRODUCT = "product"
MATRIX_MODES = (MATRIX_ZIP, MATRIX_PRODUCT)
MAX_MATRIX_ROWS = 100  # 一次扇出的行数上限：再多就是白烧号池，界面也铺不下
MAX_VALUES_PER_PARAM = 50  # 单个参数最多填几个值（多值扇出的"列高"上限）

# 手填项在界面上要说的那句实话（别让人以为系统认出来了）
MANUAL_NOTE = "整句（台词／泄密内容／绝境描述）没有固定写法可依赖，系统不猜：请从稿子里复制原句，再填新句"

# 只用来**认出当前值**的正则（probe），替换仍按逐字全局走——场景就是这一类：
# 模板保证「剧情：」后第一段是场景句（现网样例 `剧情：【前3秒】普通民居客厅，旧沙发…`），
# 位置认得出；但同一个场景词在⑧镜头行还会出现，必须全局换干净才不精神分裂。
SCENE_LEAD_PROBE = r"剧情：(?:【[^】]{1,8}】)?\s*([^，。；\n]{2,24})"


# 出厂默认表（一）：模板①行那两个位置（题材标签／剧名）——**11-10 用户拍板清空**。
# 依据是用户给的《钩子模版换皮参数设定.docx》：全文只有各原型的「逐镜填空表＋文案公式＋
# 换皮变量」，没有「剧名」「题材」「标签」这三个字。这两行是我从投产模板
# `autoclip/app/prompt/hook_expand.txt` 第①行「生成【都市脑洞】…参考【《剧名》】」自己加的，
# 属于自加设计，按口径撤掉：
#  - 剧名指认的是剧目库里那部**真剧**，换了它等于让豆包参考另一部剧（还会和过审文案对不上）；
#  - 题材标签真要改，走「自定义替换」把 `生成【…】` 里那几个字照打一遍就行，不必占一行字典。
# 常量名留着且为空表：将来运营明确要这两行，在「可替换元素库」里自己加（PUT 口），不用发版。
# ⚠️ 撤掉槽位**不等于**①行可以动：`DEFAULT_SKIP_LINES` 仍然把 `生成【…】`（含剧名）和
# `钩子原文：`（过审那句）整行划在可动区间外，判据见 `test_protected_lines_are_not_touched_by_animal_replace`。
TEMPLATE_PROMPT_ELEMENTS: List[Dict[str, Any]] = []

# 出厂默认表（二）：11-10 用户逐原型给的**可替换参数清单**，词表照原话录入、
# 一个词没加（"..." 后面的开放式取值由「自定义输入／多值」那条路走，不由我编）。
# 认法分工是这么定的：
# - 场景：**probe 认位置 ＋ 逐字全局换**（模板把场景句钉在「剧情：」后第一段，认得出；
#   同一个词还会在⑧镜头行冒出来，全局换才不留半个旧场景）；词表外的场景照样认得出，
#   因为认的是位置，不是词表；
# - 动物／偷听对象／财富／弱势对象／施暴者／超能力／神力：单个词，写在③剧情自由文本里，
#   走 literal（词面逐字找，命中几处换几处）；词表外的值认不出来时界面如实说「没认出」，
#   人可以自己填；
# - 说的话／偷听到的内容／引爆台词／绝境描述：整句、且真稿里是**间接转述**
#   （现网样例「催他下水求财」「得意地说某只实业公司的股票即将疯涨」），没有引号形状可依，
#   走 manual：这一行永远摆出来，原值请人从稿子里复制。
# `categories` 只填「原型 A」这种前缀（不填全名）：现网字典里原型名被改名也不会让槽位集体消失，
# 判据见 `slot_applies` 的前缀口径。
PROTOTYPE_PROMPT_ELEMENTS: List[Dict[str, Any]] = [
    # ── 原型 A：非人物件 / 动物开口说话 ──
    {
        "key": "a_animal",
        "label": "动物／非人物件",
        "mode": MODE_LITERAL,
        "pattern": "",
        "anchors": ["猫", "狗", "黄鼠狼"],
        "pool": ["猫", "狗", "黄鼠狼"],
        "categories": ["原型 A"],
        "note": "③剧情行里开口的那个。用户词表只有这三个，别的动物自己填（可多值）。",
    },
    {
        "key": "a_scene",
        "label": "场景",
        "mode": MODE_LITERAL,
        "probe": SCENE_LEAD_PROBE,
        "anchors": ["建筑工地", "繁华大街", "河边"],
        "pool": ["建筑工地", "繁华大街", "河边"],
        "categories": ["原型 A"],
        "note": "「剧情：」后第一段自动认出；换成别的场景时全文一起换。",
    },
    {
        "key": "a_speech",
        "label": "动物说的一句话",
        "mode": MODE_MANUAL,
        "anchors": [],
        "pool": [],
        "categories": ["原型 A"],
        "note": MANUAL_NOTE,
    },
    # ── 原型 B：偷听泄密 ──
    {
        "key": "b_scene",
        "label": "场景",
        "mode": MODE_LITERAL,
        "probe": SCENE_LEAD_PROBE,
        "anchors": ["房梁", "床底", "衣柜"],
        "pool": ["房梁", "床底", "衣柜"],
        "categories": ["原型 B"],
        "note": "偷听的藏身之处／事发场景。自动认「剧情：」后第一段，词表外的自己填。",
    },
    {
        "key": "b_target",
        "label": "偷听对象（第三方）",
        "mode": MODE_LITERAL,
        "anchors": ["丈夫", "老板", "亲戚"],
        "pool": ["丈夫", "老板", "亲戚"],
        "categories": ["原型 B"],
        "note": "说泄密话的那位。注意别与原型 D 的「施暴者」混：这一项是**说话的人**。",
    },
    {
        "key": "b_secret",
        "label": "偷听到的（泄密）内容",
        "mode": MODE_MANUAL,
        "anchors": [],
        "pool": [],
        "categories": ["原型 B"],
        "note": MANUAL_NOTE,
    },
    # ── 原型 C：隐藏财富 / 秘境发现 ──
    {
        "key": "c_scene",
        "label": "场景／秘境",
        "mode": MODE_LITERAL,
        "probe": SCENE_LEAD_PROBE,
        "anchors": ["枯井", "暗道", "火葬场", "坟墓", "海底"],
        "pool": ["枯井", "暗道", "火葬场", "坟墓", "海底"],
        "categories": ["原型 C"],
        "note": "触发机关那处。用户词表五项照录，其余自己填。",
    },
    {
        "key": "c_treasure",
        "label": "发现的财富",
        "mode": MODE_LITERAL,
        "anchors": ["黄金", "金碗", "金砖", "金牙"],
        "pool": ["黄金", "金碗", "金砖", "金牙"],
        "categories": ["原型 C"],
        "note": "曝光出来的那件东西。",
    },
    # ── 原型 D：虐待 / 冲突 / 不公反转 ──
    {
        "key": "d_weak",
        "label": "弱势对象",
        "mode": MODE_LITERAL,
        "anchors": ["老人", "孕妇", "妻子", "儿媳"],
        "pool": ["老人", "孕妇", "妻子", "儿媳"],
        "categories": ["原型 D"],
        "note": "被欺负的那位。换人设时记得同步③里的称谓，正文可整段手改。",
    },
    {
        "key": "d_scene",
        "label": "场景",
        "mode": MODE_LITERAL,
        "probe": SCENE_LEAD_PROBE,
        "anchors": ["家庭", "公司", "大街"],
        "pool": ["家庭", "公司", "大街"],
        "categories": ["原型 D"],
        "note": "当众发生那处。",
    },
    {
        "key": "d_abuser",
        "label": "施暴者",
        "mode": MODE_LITERAL,
        "anchors": ["丈夫", "婆婆", "公公"],
        "pool": ["丈夫", "婆婆", "公公"],
        "categories": ["原型 D"],
        "note": "动手的那位。原型 D 合规要求（纯属虚构＋请勿模仿、侧拍借位）在正文里，别顺手删。",
    },
    {
        "key": "d_line",
        "label": "引爆不公的一句话",
        "mode": MODE_MANUAL,
        "anchors": [],
        "pool": [],
        "categories": ["原型 D"],
        "note": MANUAL_NOTE,
    },
    # ── 原型 E：超能力 / 异常 / 猎奇 ──
    {
        "key": "e_power",
        "label": "超能力展示",
        "mode": MODE_LITERAL,
        "anchors": ["催生植物", "眼发金光", "一口吸干河水"],
        "pool": ["催生植物", "眼发金光", "一口吸干河水"],
        "categories": ["原型 E"],
        "note": "异常初现那一下。是动作短语，写在③剧情行里，逐字全局换。",
    },
    {
        "key": "e_scene",
        "label": "场景",
        "mode": MODE_LITERAL,
        "probe": SCENE_LEAD_PROBE,
        "anchors": ["山里", "河边", "海边"],
        "pool": ["山里", "河边", "海边"],
        "categories": ["原型 E"],
        "note": "「剧情：」后第一段自动认出。",
    },
    # ── 原型 F：神力 / 温情 / 绝境反转 ──
    {
        "key": "f_plight",
        "label": "绝境",
        "mode": MODE_MANUAL,
        "anchors": [],
        "pool": ["车祸", "悬崖边"],
        "categories": ["原型 F"],
        "note": "用户口径是「自定义描述」，所以按手填走；候选只给车祸／悬崖边两个提示用，选了也要自己核原句。",
    },
    {
        "key": "f_power",
        "label": "神力",
        "mode": MODE_LITERAL,
        "anchors": ["徒手拦车", "徒手接坠楼者"],
        "pool": ["徒手拦车", "徒手接坠楼者"],
        "categories": ["原型 F"],
        "note": "介入的那一下。",
    },
]

DEFAULT_PROMPT_ELEMENTS: List[Dict[str, Any]] = TEMPLATE_PROMPT_ELEMENTS + PROTOTYPE_PROMPT_ELEMENTS



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
    """规整一个槽位；键或标签为空、三种认法都没内容、写法编不过 → 丢弃（并留日志）。

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
    probe = _clean_text(raw.get("probe"), MAX_PATTERN_LEN)
    anchors = _clean_words(raw.get("anchors"), MAX_ANCHOR_LEN, MAX_POOL_PER_SLOT)
    pool = _clean_words(raw.get("pool"), MAX_VALUE_LEN, MAX_POOL_PER_SLOT)
    # skip_lines：没写＝用默认保护行；显式写空串＝这个槽位允许碰「钩子原文／①」那两行
    raw_skip = raw.get("skip_lines")
    skip_lines = DEFAULT_SKIP_LINES if raw_skip is None else _clean_text(raw_skip, MAX_SKIP_PATTERN_LEN)
    if mode not in SLOT_MODES:
        # 没写认法时按"给了什么"推断：给了 pattern 就是 pattern 槽位。
        # **不推断成 manual**：手填是"这行就是要人填"的明确表态，没写认法又什么都没给的行
        # 是配置写漏了，按老口径丢掉，不然界面会冒出一堆没人打算填的空行。
        mode = MODE_PATTERN if pattern else MODE_LITERAL
    if mode == MODE_PATTERN and not pattern:
        mode = MODE_LITERAL
    if mode == MODE_PATTERN:
        if compile_error(pattern) is not None:
            logger.warning("元素槽位 %s 的识别写法无效，已忽略该槽位：%s", key, pattern)
            return None
        # pattern 槽位靠捕获组认值：pool 空只意味着"没有推荐候选"，槽位仍然可用
        probe = ""  # pattern 自己就是认法，probe 是给 literal 用的，留着只会让人以为两套都生效
        skip_lines = ""  # pattern 钉在自己的写法位置上，不存在"撞进保护行"
    elif mode == MODE_MANUAL:
        # 手填项**不需要词面也不需要候选**：这一行永远摆出来给人填（用户口径：所有可替换参数由手动输入）
        anchors, pattern = [], ""
    else:
        if not anchors and not pool and not probe:
            logger.warning("元素槽位 %s 既没给词面、没给候选也没给识别位置，认不出任何东西，已忽略", key)
            return None
        # literal 槽位没单独给词面时，候选池就是拿去正文里找的词面
        anchors = anchors or pool
        pattern = ""
    if probe and compile_error(probe) is not None:
        # probe 写坏只丢掉 probe（词面那条路照走），别把整行扔掉——业务词表还在，功能不断档
        logger.warning("元素槽位 %s 的识别位置无效，已忽略位置、保留词面：%s", key, probe)
        probe = ""
    return {
        "key": key,
        "label": label,
        "mode": mode,
        "anchors": anchors,
        "pattern": pattern,
        "probe": probe,
        "pool": pool,
        "categories": _clean_words(raw.get("categories"), 60, MAX_POOL_PER_SLOT),
        "skip_lines": skip_lines,
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
    # 出厂表也走一遍清洗：不清洗的话"接口吐的出厂行"少 probe／skip_lines 这些键，
    # 前端按同一套字段渲染就会在这一行上崩出 undefined（三层表必须同构）
    defaults = normalize_catalog(DEFAULT_PROMPT_ELEMENTS)
    by_key = {s["key"]: s for s in defaults}
    ordered: List[Dict[str, Any]] = [dict(s) for s in defaults]
    for slot in override:
        if slot["key"] in by_key:
            idx = next(i for i, s in enumerate(ordered) if s["key"] == slot["key"])
            ordered[idx] = slot
        else:
            ordered.append(slot)
    return ordered, override


def slot_applies(slot: Dict[str, Any], category: Optional[str]) -> bool:
    """槽位是否适用这一条。没限定就全适用；限定了就按钩子原型名/键对一下（大小写与空格不敏感）。

    11-10 批 N 放宽成**前缀也算**：字典里的原型名是一句长话
    （「原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）」），运营改名、界面只传
    「原型 A」这种短码时，槽位不该集体消失——消失的后果是"参数项没了"，比多显示更糟。
    短的那 side 至少 3 个字才当前缀，防止一个「A」把别的原型也兜进来。
    """
    cats = slot.get("categories") or []
    if not cats:
        return True
    if not category:
        return False
    want = str(category).strip().lower().replace(" ", "")
    for c in cats:
        got = str(c).strip().lower().replace(" ", "")
        if not got:
            continue
        if got == want:
            return True
        if len(got) >= 3 and want.startswith(got):
            return True
        if len(want) >= 3 and got.startswith(want):
            return True
    return False


def _allowed_spans(text: str, skip_pattern: str) -> List[Tuple[int, int]]:
    """受保护行以外的可动区间（按行切，跳过行整行不算命中）。

    写法编不过时**不启用保护**而不是全盘跳过——保护是加分项，把它做成判据的话，
    一行坏正则会让"什么都换不动"看起来像"字典没生效"。
    """
    if not text:
        return []
    rx = None
    if skip_pattern:
        try:
            rx = re.compile(skip_pattern, re.MULTILINE)
        except re.error:
            rx = None
    if rx is None:
        return [(0, len(text))]
    out: List[Tuple[int, int]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        body_end = pos + len(line.rstrip("\r\n"))
        if body_end > pos and not rx.search(line):
            out.append((pos, body_end))
        pos += len(line)
    return out


def _span_ok(span: Tuple[int, int], allowed: List[Tuple[int, int]]) -> bool:
    start, end = span
    return any(a <= start and end <= b for a, b in allowed)


def _find_all(text: str, needle: str) -> List[Tuple[int, int]]:
    """逐字找，非重叠、从左到右。"""
    out: List[Tuple[int, int]] = []
    if not needle:
        return out
    start = text.find(needle)
    while start != -1:
        out.append((start, start + len(needle)))
        start = text.find(needle, start + len(needle))
    return out


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


def _line_context(text: str, pos: int, limit: int = MAX_CONTEXT_LEN) -> str:
    """命中处所在那一行（截断）——给界面摆「稿子里对应的原句」用。

    只截不改：这一行是给人**对着看**的，不参与替换，所以哪怕它落在受保护行里也照原样给出去
    （人一眼看到「这词在①行里」比系统替他藏起来有用）。
    """
    if not text:
        return ""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    line = " ".join(text[start:end].split())
    return line[:limit] + ("…" if len(line) > limit else "")


def slot_matches(text: str, slot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """这个槽位在这段正文里认出哪些命中。**手填项永远认不出东西**（这是它的诚实之处）。"""
    if not text:
        return []
    mode = slot.get("mode")
    if mode == MODE_PATTERN:
        return _matches_for_pattern(text, slot.get("pattern") or "")
    if mode == MODE_MANUAL:
        return []
    allowed = _allowed_spans(text, slot.get("skip_lines") or "")
    hits = [h for h in _matches_for_anchors(text, list(slot.get("anchors") or [])) if _span_ok((h["start"], h["end"]), allowed)]
    probe = slot.get("probe") or ""
    if probe:
        # 位置识别只负责"认出当前值是什么"（词表外的场景也能认出来）；
        # 替换仍按逐字全局走，所以这里给出的 span 只用于去重，不参与替换。
        taken = [(h["start"], h["end"]) for h in hits]
        for h in _matches_for_pattern(text, probe):
            span = (h["start"], h["end"])
            if not _span_ok(span, allowed):
                continue
            if any(not (span[1] <= s or span[0] >= e) for s, e in taken):
                continue
            taken.append(span)
            h["probe_hit"] = True
            hits.append(h)
        hits.sort(key=lambda h: h["start"])
    return hits


def _slot_note_for_ui(slot: Dict[str, Any]) -> str:
    """给界面看的那句说明。

    手填项（mode=manual）必须带上"系统不猜"那条口径：这一项没有 `current`，
    一线看到空下拉最容易以为字典坏了／这一项不用填。出厂行与运营自配行都可能只写了
    业务说明（原型 F 的「绝境」就只写了候选的来意），所以缺就补一句，不覆盖人家写的。
    """
    note = str(slot.get("note") or "")
    if slot.get("mode") == MODE_MANUAL and MANUAL_NOTE not in note:
        note = f"{note}｜{MANUAL_NOTE}" if note else MANUAL_NOTE
    return note


def extract_elements(
    text: Optional[str],
    catalog: List[Dict[str, Any]],
    category: Optional[str] = None,
    include_unmatched: bool = False,
) -> List[Dict[str, Any]]:
    """从一段提示词正文里认出可替换元素。

    返回 `[{key,label,mode,current,occurrences,pool,custom,categories,note,protected}]`：
    `current` 是当前值（同槽位多个不同值时取第一个命中，`occurrences` 把每个值各出现几次说清），
    `pool` 是候选（裂变），`custom=true` 表示这一槽位允许自己填。
    认不出来的槽位默认不出现——②投产弹窗只摆真换得动的东西，不摆一排空下拉。

    `include_unmatched=true`（批 N，④开单屏要的就是这个）：**这一原型该设的参数项全摆出来**，
    认不出原值的 `current=None`，界面把它说成「原稿里没认出（词表外的值），请从稿子里复制」，
    而不是让人以为这个参数没有。手填项（mode=manual）永远出现，与这个开关无关。
    """
    body = text or ""
    out: List[Dict[str, Any]] = []
    for slot in catalog:
        if not slot_applies(slot, category):
            continue
        found = slot_matches(body, slot)
        counts: Dict[str, int] = {}
        for hit in found:
            counts[hit["value"]] = counts.get(hit["value"], 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        # 位置认出来的那一个才是"这一稿的场景"：词表里的另一个词（河边）在正文里出现次数更多，
        # 但它是顺带提到的别处，不是开场场景——拿它当 current 会把人引到错的替换起点上。
        current = ordered[0][0] if ordered else None
        probe_first = next((h["value"] for h in found if h.get("probe_hit")), "")
        if probe_first and current != probe_first:
            current = probe_first
        if not ordered and not (include_unmatched or slot.get("mode") == MODE_MANUAL):
            continue
        occurrences = [{"value": v, "count": c} for v, c in ordered]
        if current and occurrences and occurrences[0]["value"] != current:
            # 把"系统认出来的那一个"排在第一个，界面默认选中它；别的值仍然列得出来
            occurrences.sort(key=lambda o: o["value"] != current)
        # 用户口径（11-10）：「把原提示词中对应的内容也放出来，这样可以做一个对比」——
        # 光给一个「当前：河边」看不出它是哪句里的哪个成分，替换点前后那整行才是人对账看的东西。
        current_hit = next((h for h in found if h["value"] == current), found[0] if found else None)
        out.append({
            "key": slot["key"],
            "label": slot["label"],
            "mode": slot["mode"],
            "current": current,
            "context": _line_context(body, current_hit["start"]) if current_hit else "",
            "occurrences": occurrences,
            "pool": list(slot.get("pool") or []),
            "custom": True,
            "categories": list(slot.get("categories") or []),
            "note": _slot_note_for_ui(slot),
            # 告诉界面：这一槽位不碰「钩子原文／①」那两行（换动物不会把剧名换掉）
            "protected": bool(slot.get("skip_lines")) and slot.get("mode") != MODE_PATTERN,
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
    - 带 `key` 且槽位是 literal／manual，或**不带 key（自定义输入）** → 逐字全局替换 `from` → `to`，
      但**跳过受保护行**（`钩子原文：` 那行是过审文案、`生成【…】` 那行里有《剧名》——
      把「鲸鱼」全文换成「猫」会顺手造出一部不存在的剧，11-10 现网样例实测出来的坑）。

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
        key = _clean_text(edit.get("key"), 60)
        raw_from = edit.get("from")
        slot = by_key.get(key) if key else None
        is_manual = slot is not None and slot.get("mode") == MODE_MANUAL
        # 手填项换的是整句（台词／泄密内容），词面 60 字、值 200 字的帽儿会把它截断成半句话
        value_limit = MAX_MANUAL_VALUE_LEN if is_manual else MAX_VALUE_LEN
        anchor_limit = MAX_MANUAL_VALUE_LEN if is_manual else MAX_ANCHOR_LEN
        to = _clean_text(edit.get("to"), value_limit)
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
        src = _clean_text(raw_from, anchor_limit)
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
            all_hits = _matches_for_pattern(body, slot.get("pattern") or "")
            hits = [h for h in all_hits if h["value"] == src]
            found_any = bool(all_hits) or bool(hits)
            count = len(hits)
            if count:
                body = _replace_spans(body, [(h["start"], h["end"]) for h in hits], to)
        else:
            skip = (slot or {}).get("skip_lines", DEFAULT_SKIP_LINES) or ""
            allowed = _allowed_spans(body, skip)
            all_spans = _find_all(body, src)
            spans = [s for s in all_spans if _span_ok(s, allowed)]
            count = len(spans)
            found_any = bool(all_spans)
            if count:
                body = _replace_spans(body, spans, to)
            skipped = len(all_spans) - count
            if skipped:
                notes.append(
                    f"「{src}」在受保护行里还有 {skipped} 处没动"
                    "（「钩子原文」是过审那句、①行里有剧名，自动替换不碰；要改请在正文里手改）"
                )
        replaced.append({
            "key": key,
            "label": (slot or {}).get("label") or key or "自定义",
            "mode": (slot or {}).get("mode") or MODE_LITERAL,
            "from": src,
            "to": to,
            "count": count,
        })
        if not count and not found_any:
            notes.append(f"原文里没找到「{src}」，这一条没改")
    if len(body) > 20000:
        notes.append(f"组完 {len(body)} 字，比投递稿长度上限还长，投板时会被拦，先删点")
    return body, replaced, notes


def clean_value_list(values: Any, limit: int = MAX_MANUAL_VALUE_LEN) -> List[str]:
    """界面传进来的一列值：去空、去重、保序（顺序＝配对时的行序，不许打乱）。"""
    items = values if isinstance(values, (list, tuple)) else ([values] if values else [])
    return _clean_words(items, limit, MAX_VALUES_PER_PARAM)


def expand_matrix(
    values: Optional[Dict[str, Any]],
    mode: str = MATRIX_ZIP,
    labels: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    """「每个参数填了多个值」→ 展开成一条条钩子（11-10 用户口径：按行配对为主，可切全组合）。

    - `zip`（默认，按行配对）：行数＝填得最多的那个参数；**只填一个值的参数每行复用同一个**
      （"场景换 3 个、动物不换"这种最常用）；两个参数都填了多个、个数又对不齐 →
      **不猜**，直接报错点名是哪两个（猜错的话一线要对着 6 条废单一条一条删）。
    - `product`（全组合）：笛卡尔积，行数超过 `MAX_MATRIX_ROWS` 当场报错，
      免得手滑填出 20×20＝400 张单白烧号池。

    返回 `(行, 备注)`，行是 `{key: 值}`。纯函数、不花钱、不落库——
    真正"一行变一张生产单"在批 P 的 `produce` 扇出口做，这里只管算行。
    """
    if mode not in MATRIX_MODES:
        raise ValueError(f"展开方式只认「按行配对」（{MATRIX_ZIP}）或「全组合」（{MATRIX_PRODUCT}），收到的是：{mode}")
    cols: Dict[str, List[str]] = {}
    for key, raw in (values or {}).items():
        k = _clean_text(key, 60)
        col = clean_value_list(raw)
        if k and col:
            cols[k] = col
    names = labels or {}

    def shown(key: str) -> str:
        """报错话术里要说人话（「场景」），不要说 `a_scene`。"""
        return names.get(key) or key

    if not cols:
        return [], ["没填任何参数值，展开不出行"]
    multi = {k: len(v) for k, v in cols.items() if len(v) > 1}
    notes: List[str] = []
    if mode == MATRIX_PRODUCT:
        total = 1
        for n in multi.values():
            total *= n
        if total > MAX_MATRIX_ROWS:
            filled = "、".join(f"「{shown(k)}」{n} 个" for k, n in multi.items())
            raise ValueError(
                f"全组合会展开成 {total} 条，超过上限 {MAX_MATRIX_ROWS} 条："
                f"现在填了 {filled}。少填几个值，或改用按行配对"
            )
        keys = list(cols)
        rows = [dict(zip(keys, combo)) for combo in itertools.product(*(cols[k] for k in keys))]
        notes.append("全组合：" + "×".join(str(len(cols[k])) for k in keys) + f"＝{len(rows)} 条")
        return rows, notes
    if len(set(multi.values())) > 1:
        detail = "、".join(f"「{shown(k)}」{n} 个" for k, n in multi.items())
        raise ValueError(
            f"按行配对要求填多个值的参数个数一样，现在对不齐：{detail}。"
            "要么补齐到一样多（少的那几个重复填一遍），要么切「全组合」"
        )
    rows_n = max(multi.values()) if multi else 1
    out: List[Dict[str, str]] = []
    for i in range(rows_n):
        out.append({k: (v[i] if len(v) > 1 else v[0]) for k, v in cols.items()})
    single = [k for k, v in cols.items() if len(v) == 1]
    if single and rows_n > 1:
        notes.append("、".join(shown(k) for k in single) + "只填了一个值，" + f"{rows_n} 条里都用它")
    return out, notes


def compose_variants(
    base_text: Optional[str],
    catalog: List[Dict[str, Any]],
    base_values: Optional[Dict[str, Any]],
    rows: List[Dict[str, str]],
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """把展开出来的每一行套到同一份底稿上，得到 N 份可投递的正文（0 元、不落库）。

    `base_values` 是"这一份稿子里这个参数现在是什么"（认出来的、或人手填进去的原值）。
    原值缺失的参数**这一行不做替换**，并在 `missing` 里点名——不是把旧值当新值用，
    也不是悄悄跳过：手填项（台词／泄密内容）本来就得人给原句。
    """
    by_key = {s["key"]: s for s in catalog}
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows or [], start=1):
        edits: List[Dict[str, Any]] = []
        missing: List[str] = []
        for key, to in (row or {}).items():
            slot = by_key.get(key)
            if slot is not None and not slot_applies(slot, category):
                missing.append(slot["label"])
                continue
            src = _clean_text((base_values or {}).get(key), MAX_MANUAL_VALUE_LEN)
            if not src:
                missing.append((slot or {}).get("label") or key)
                continue
            edits.append({"key": key, "from": src, "to": _clean_text(to, MAX_MANUAL_VALUE_LEN)})
        text, replaced, notes = apply_edits(base_text, catalog, edits)
        if missing:
            notes = notes + [
                f"这些参数没有原值，这一条没换：{'、'.join(missing)}（手填项要自己从稿子里复制原句）"
            ]
        out.append({
            "seq": idx,
            "values": dict(row or {}),
            "text": text,
            "replaced": replaced,
            "notes": notes,
            "missing": missing,
            "changed": text != (base_text or ""),
        })
    return out
