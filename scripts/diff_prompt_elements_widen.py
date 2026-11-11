"""换皮参数词表改动前后的**离线对照**：同一批现网稿子，分别喂老字典（某个 git 版本）和新字典（工作区）。

为什么能离线跑：`app/services/asset_prompt_elements.py` 只 import 标准库
（itertools／logging／re／typing），识别这一层不连库、不连模型、不花钱。所以「这次改词表
到底多认出几条」不用等部署就能算准，部署后那遍（`live_accept_825_elements_census.py`）
只是拿真接口复核这里的数——**两边对不上就是生效字典和出厂表不是同一份**（多半是
`system_config` 里有条运营覆盖），这本身也是一条判据。

跑法（本机，仓库根或任意目录都行）：
    1) 先在 163 容器内只读导出语料（现网 88 条口径稿子，不进 git）：
       ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' <<'PY'
       import asyncio, json, os
       from sqlalchemy import text as T
       from sqlalchemy.ext.asyncio import create_async_engine
       E = create_async_engine(os.environ["DATABASE_URL"])
       async def m():
           async with E.connect() as c:
               r = await c.execute(T("select s.id::text id, coalesce(cat.name,'') category, "
                                     "s.audit_status, coalesce(s.prompt_preview, s.text) body "
                                     "from asset_summaries s left join asset_categories cat on cat.id=s.category_id"))
               print(json.dumps([dict(x) for x in r.mappings().all()], ensure_ascii=False))
           await E.dispose()
       asyncio.run(m())
       PY
       > /tmp/prod_bodies.json
    2) 本脚本：
       python3 scripts/diff_prompt_elements_widen.py --corpus /tmp/prod_bodies.json
       # 老字典默认取 bff4eca（11-11 批 8-25「按 docx 补宽」之前的那一份出厂表）
       python3 scripts/diff_prompt_elements_widen.py --corpus … --old-ref <ref>

口径说明：
  - 认的范围由 `slot_applies(slot, category)` 决定：**稿子没挂原型 → 0 项**（11-10 定的口径），
    所以"认出 0 项"里有结构性的一部分，别当成缺陷。
  - 语料取 `prompt_preview ?? text`＝开单屏 serverDraft 那一版；识别**按开单屏当时的算法现算**，
    原值本来就不落库，没有存量可查。
  - 「认出值的总次数」数的是「槽位 × 命中的值」这一层，与普查脚本按条统计的口径不同，别互相换算。
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REL = "backend/app/services/asset_prompt_elements.py"
# 8-25 之前的最后一份出厂表：改词表这件事本身没有别的提交混在里面
DEFAULT_OLD_REF = "bff4eca"


def load(tag: str, src: Path):
    spec = importlib.util.spec_from_file_location(f"elements_{tag}_{abs(hash(str(src)))}", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def recognized(mod, body: str, category: str):
    """按开单屏同一套判据现算：槽位适用 → slot_matches → 取值。"""
    out = {}
    for slot in mod.normalize_catalog(mod.DEFAULT_PROMPT_ELEMENTS):
        if not mod.slot_applies(slot, category or None):
            continue
        vals = [h["value"] for h in mod.slot_matches(body, slot)]
        if vals:
            out[slot["key"]] = vals
    return out


def anchors_of(mod, category: str):
    """每个适用槽位的词面集合，给「半词命中」自查用。"""
    return {
        slot["key"]: {a for a in slot["anchors"]} | {a for a in slot["pool"]}
        for slot in mod.normalize_catalog(mod.DEFAULT_PROMPT_ELEMENTS)
        if mod.slot_applies(slot, category or None)
    }


def census(mod, rows):
    per_copy, hits = {}, Counter()
    for r in rows:
        got = recognized(mod, r["body"] or "", r["category"])
        per_copy[r["id"]] = got
        for k, vs in got.items():
            hits[k] += len(vs)
    n_copies = sum(1 for g in per_copy.values() if g)
    return per_copy, hits, n_copies


def half_word_hits(mod, rows, per_copy):
    """认出的值如果是某个更长词面的一部分，替换就会留残渣——逐处查，不是逐词猜。

    判据：命中的值 v 在正文里的这一次出现，与同槽位另一条更长词面 a 的某次 occurrence
    **跨度重叠**（a 把 v 包在里面）。11-11 批 8-25 就是靠这条把「猫头鹰认成猫」钉掉的。
    """
    bad = []
    for r in rows:
        body = r["body"] or ""
        allowed = anchors_of(mod, r["category"])
        for key, vals in per_copy[r["id"]].items():
            for v in vals:
                for a in allowed.get(key, ()):
                    if a == v or not a.startswith(v) or len(a) <= len(v):
                        continue
                    i = body.find(v)
                    while i != -1:
                        if any(j <= i < j + len(v) for j in _occurrences(body, a)):
                            bad.append((r["id"][:8], key, v, a))
                            break
                        i = body.find(v, i + len(v))
    return bad


def _occurrences(body: str, word: str):
    i, out = body.find(word), []
    while i != -1:
        out.append(i)
        i = body.find(word, i + 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, help="只读导出的现网语料 JSON（见模块 docstring）")
    ap.add_argument("--old-ref", default=DEFAULT_OLD_REF, help=f"老字典的 git 版本（默认 {DEFAULT_OLD_REF}）")
    ap.add_argument("--new-src", default=None, help="新字典文件路径（默认取工作区那份，含未提交改动）")
    args = ap.parse_args()

    rows = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        old_path = Path(td) / "old_elements.py"
        old_path.write_bytes(subprocess.check_output(["git", "-C", str(REPO), "show", f"{args.old_ref}:{REL}"]))
        OLD = load("old", old_path)
    if args.new_src:
        NEW = load("new", Path(args.new_src))
    else:
        with tempfile.TemporaryDirectory() as td:
            new_path = Path(td) / "new_elements.py"
            new_path.write_bytes((REPO / REL).read_bytes())
            NEW = load("new", new_path)

    old_c, old_h, old_n = census(OLD, rows)
    new_c, new_h, new_n = census(NEW, rows)
    no_cat = sum(1 for r in rows if not r["category"])

    print(f"语料 {len(rows)} 条（未挂原型的 {no_cat} 条结构性 0 项）")
    print(f"至少认出 1 项的文案：老 {old_n} 条 → 新 {new_n} 条（{new_n - old_n:+d}）")
    print(f"认出值的总次数　　：老 {sum(old_h.values())} 次 → 新 {sum(new_h.values())} 次"
          f"（{sum(new_h.values()) - sum(old_h.values()):+d}）\n")

    print("=== 每个槽位认出次数（老 → 新）===")
    for k in sorted(set(old_h) | set(new_h)):
        o, n = old_h.get(k, 0), new_h.get(k, 0)
        mark = "  ← 从 0 到有" if o == 0 and n else ("  ↑" if n > o else ("  ⚠️↓ 变少" if n < o else ""))
        print(f"  {k:<12} {o:>3} → {n:>3}{mark}")

    print("\n=== 逐条变化（只在有增减时打印）===")
    added_words, lost = Counter(), []
    for r in rows:
        o, n = old_c[r["id"]], new_c[r["id"]]
        if o == n:
            continue
        gain = {k: sorted(set(n.get(k, [])) - set(o.get(k, []))) for k in n if set(n.get(k, [])) - set(o.get(k, []))}
        drop = {k: sorted(set(o.get(k, [])) - set(n.get(k, []))) for k in o if set(o.get(k, [])) - set(n.get(k, []))}
        for v in gain.values():
            added_words.update(v)
        code = r["id"][:8]
        print(f"  {code} [{r['category'] or '未挂'}] {r['audit_status']}："
              f"{'+'.join(f'{k}={v}' for k, v in gain.items()) or '（无新认）'}"
              + (f"  −{'+'.join(f'{k}={v}' for k, v in drop.items())}" if drop else ""))
        if drop:
            lost.append((code, drop, gain))

    print("\n=== 新认出的值（去重计数）===")
    print(dict(added_words.most_common(40)))

    print("\n=== 回归核对：老字典认出的值，新字典还在不在 ===")
    if not lost:
        print("  无任何槽位丢值。")
    for code, drop, gain in lost:
        print(f"  {code} 丢 {drop}｜同条新增 {gain}")

    bad = half_word_hits(NEW, rows, new_c)
    print("\n=== 半词自查：认出的值是不是被更长的词面包住（换掉会留残渣）===")
    for code, key, v, a in bad:
        print(f"  ⚠️ {code} {key}: 认出「{v}」但正文里它嵌在「{a}」里 → 该登记整词形态")
    print(f"  命中 {len(bad)} 处（0＝长词面优先把所有复合形态都吃下了）")

    # 丢值不一定是错：半词修正（猫→猫头鹰）就是"该丢"。所以只把数摆出来，退出码留给判据。
    if bad:
        print("\n结论：新字典有半词命中，别上线。")
        return 1
    print("\n结论：无半词命中。丢值若全是整词修正（值由短词变长词），属正确性变好。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
