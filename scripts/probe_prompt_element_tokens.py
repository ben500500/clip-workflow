"""换皮参数**补词前的撞词普查**：候选词现网到底怎么写，照字面加进去会不会切半句。

跑法（163 后端容器里，0 元、只读；容器内写的 /tmp 与 ssh 的 /tmp 不是一个命名空间，
取回明细要用 `docker exec clip-backend cat /tmp/xxx.json > 本地`，scp 拿不到）：
    ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' \\
      < scripts/probe_prompt_element_tokens.py

为什么要这一步（不是形式主义）：
  - `literal` 槽位的原值是拿去**逐字全局替换**的。设定表写的是「狐」「鹰」这种单字，
    现网稿子里却是「白狐／狐狸／猫头鹰」——只加单字，`_matches_for_anchors` 会把复合词里
    的一个字认成值，人照它换就产出「猫头雕」这种坏稿。
  - `_matches_for_anchors` 是**长词面优先、同段不重复占用**。所以把复合形态一起放进词面表，
    长的那个会赢，单字只在真正独立出现时才当值——这是既守住「只并设定表的词」、
    又不产出坏稿的唯一做法（11-11 批 8-25 就是这么落的）。
  - 本脚本给的就是判据：每个候选词在现网稿子里的出现次数＋左右邻字（邻字成词才补形态，
    没出现过就照原样加），末尾再反向捞一遍「稿子里实际出现的动物形态」，
    用来回答**并完词表之后还剩多少值认不出来**——那批残留词就是下一轮补词／上位置认法的依据。

改候选词只需要动 DOCX_TOKENS；「现网已生效词面」不再手抄，直接从模块里的出厂表读，
免得这张表和真表漂移（批 8-25 之前就漂移过一次）。
"""
import asyncio
import json
import os
import sys
from collections import Counter
from typing import Dict, List

sys.path.insert(0, "/app")  # 容器内后端代码根
from app.services import asset_prompt_elements as pe  # noqa: E402
from sqlalchemy import text as SQLText  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

ENGINE = create_async_engine(os.environ["DATABASE_URL"])
OUT = os.environ.get("OUT", "/tmp/probe_prompt_element_tokens.json")

# 候选词（键＝槽位，值＝词表；这里是《钩子模版换皮参数设定.docx》A–F 六型那串斜杠词）
DOCX_TOKENS: Dict[str, List[str]] = {
    "a_animal": ["猫", "狗", "狐", "黄鼠狼", "孔雀", "鹰", "雕像", "佛像"],
    "b_scene": ["房梁", "引擎盖", "床底", "屋顶"],
    "b_target": ["老板", "对手", "亲戚"],
    "b_secret": ["股票", "遗产", "阴谋"],          # manual 槽，只为完整性一并测
    "c_scene": ["老宅灶台", "枯井", "墙缝", "火葬场"],
    "c_treasure": ["金牙", "黄金碗", "金砖", "暗门金库"],
    "d_weak": ["老人", "孕妇", "婆婆", "妻子"],
    "d_abuser": ["儿媳", "丈夫", "长子"],
    "e_power": ["催生植物", "木耳双胞胎", "徒手神力"],
}

# 反向捞动物形态时用的字族（要治别的槽位就照这个形状再加一组）
ANIMAL_TAIL = set("猫狗狼狐鹰雕蛇鸦雀牛虎狮马兔猪鸡鹿鹤龟鱼猴鼠熊豹羊驴驼犀鲲鲤鲨鳝獴獾狸鸮")
ANIMAL_HEAD = set("黑白花黄大小金灰棕红雪白野老家胖瘦呆俊幼成")


async def load() -> Dict[str, tuple]:
    async with ENGINE.connect() as c:
        r = await c.execute(SQLText("""
            select p.id::text as id, coalesce(c2.name, '') as cat,
                   coalesce(p.prompt_preview, p.text) as t
            from asset_summaries p
            left join asset_categories c2 on c2.id = p.category_id
            order by cat, p.created_at
        """))
        return {m["id"]: (m["cat"], m["t"] or "") for m in r.mappings().all()}


def contexts(text: str, token: str) -> List[str]:
    """每次出现的左右邻字（用来判「是不是复合词里的一块」）。"""
    out = []
    i = text.find(token)
    while i != -1:
        l = text[i - 1] if i > 0 else "∅"
        rr = text[i + len(token)] if i + len(token) < len(text) else "∅"
        out.append(f"{l}{token}{rr}")
        i = text.find(token, i + len(token))
    return out


def current_words() -> Dict[str, List[str]]:
    """出厂表里每个槽位**现在**认哪些词面（manual 槽回空，因为它不参与识别）。"""
    return {
        slot["key"]: sorted(set(slot["anchors"]) | set(slot["pool"]))
        for slot in pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS)
    }


def recognized(slot_key: str, body: str, category: str):
    """按开单屏同一判据现算这一个槽位认到啥（用来算「并完词表还剩多少认不出」）。"""
    for slot in pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS):
        if slot["key"] != slot_key:
            continue
        if not pe.slot_applies(slot, category or None):
            return None  # 结构性不摆这一项
        return [h["value"] for h in pe.slot_matches(body, slot)] or []
    return None


async def main() -> None:
    data = await load()
    cur = current_words()
    print(f"现网文案 {len(data)} 条｜出厂表槽位 {len(cur)} 个\n")

    report: Dict[str, Dict[str, dict]] = {}
    for slot, tokens in DOCX_TOKENS.items():
        in_use = set(cur.get(slot, []))
        report[slot] = {}
        kind = next((s["mode"] for s in pe.normalize_catalog(pe.DEFAULT_PROMPT_ELEMENTS)
                     if s["key"] == slot), "?")
        print(f"=== {slot}（{kind}｜生效词面 {len(in_use)} 个：{sorted(in_use)}）===")
        if kind == pe.MODE_MANUAL:
            print("  这一行是手填项：词面不参与识别，加词也不会被读到（`slot_matches` 对 manual 恒回 []）")
        for tk in tokens:
            n, ctx = 0, Counter()
            for _id, (_cat, body) in data.items():
                hits = contexts(body, tk)
                if hits:
                    n += len(hits)
                    ctx.update(hits)
            print(f"  {tk:<8} 出现 {n:>3} 次｜{'已在表内' if tk in in_use else '待补':<8}｜邻字 {dict(ctx.most_common(8))}")
            report[slot][tk] = {"count": n, "in_current": tk in in_use, "ctx": dict(ctx.most_common(20))}
        print()

    # 反向：不开词表，直接从稿子里捞「颜色/大小/老幼 + 动物字」和「动物字 + 动物字」，
    # 用来判断「并完词表之后还剩多少动物值认不出来」。
    seen: Counter = Counter()
    still_missing: Counter = Counter()
    docs_missing = 0
    for _id, (cat, body) in data.items():
        if not cat.startswith(("原型 A", "原型 E")):
            continue
        for i in range(len(body) - 1):
            a, b = body[i], body[i + 1]
            if (a in ANIMAL_HEAD and b in ANIMAL_TAIL) or (a in ANIMAL_TAIL and b in ANIMAL_TAIL):
                seen[body[i:i + 2]] += 1
        got = recognized("a_animal", body, cat)
        if got == []:
            docs_missing += 1
            for w, _n in Counter(
                body[i:i + 2] for i in range(len(body) - 1)
                if (body[i] in ANIMAL_HEAD and body[i + 1] in ANIMAL_TAIL)
                or (body[i] in ANIMAL_TAIL and body[i + 1] in ANIMAL_TAIL)
            ).items():
                still_missing[w] += 1
    print(f"原型 A／E 稿子里实际出现的动物形态（Top 40）：{dict(seen.most_common(40))}")
    print(f"\n当前词表下 a_animal **仍认不出**的 A／E 稿子：{docs_missing} 篇")
    print(f"这些稿子里出现过的动物形态：{dict(still_missing.most_common(40))}")
    print("→ 这一堆就是下一轮的候选：要么是补词（要业务口径点头），要么给 A／E 上位置认法 probe"
          "（场景那条路已经跑通：probe 只认当前值，替换仍按词面全局走）。")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"tokens": report, "residue_docs": docs_missing,
                   "residue_forms": dict(still_missing)}, f, ensure_ascii=False, indent=1)
    print(f"\n明细已落 {OUT}")
    await ENGINE.dispose()


asyncio.run(main())
