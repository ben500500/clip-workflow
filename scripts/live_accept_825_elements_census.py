"""现网零成本普查：已导入的文案，换皮参数到底认出几项（**开单屏同一套算法、同一条接口**）。

跑法（163 后端容器里，全程 0 元、只读、不写库；改输出路径用 `OUT=`）：
    ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' \\
      < scripts/live_accept_825_elements_census.py
    # 取回明细：docker exec clip-backend cat /tmp/survey_elements.json > 本地（scp 拿不到容器 /tmp）

口径说明（为什么这样测才对得上界面实况）：
  - 原值**不落库**：`extract` 是纯文本进、纯文本出。所以"这批文案读没读过"没有存量可查，
    只能按开单屏当时的算法现算一遍，看能认出什么。
  - 认的范围由 `slot_applies(slot, category)` 决定：**文案没挂原型 → 0 项**（A–F 的槽位都带
    categories；原型 G 字典里没配参数项）。这 17 条（G 14 ＋ 未挂 3）是**结构性 0 项**，
    不是缺陷，看总数时先扣掉。
  - 稿子取 `prompt_preview ?? text`（与开单屏 serverDraft 同口径：认的是库里那份稿子）。
  - 混批不传 category 是界面真实行为（原型不止一种时前端传 `category: undefined`），所以这里
    **按原型分组**逐组测，才等于人进开单屏一次只挑一种型时的结果。
  - 与 `diff_prompt_elements_widen.py`（离线新旧对照）配成一对：离线那份算"改了会怎样"，
    这份算"现网实际怎样"。**两份数对不上＝生效字典不是出厂表**（十有八九是 `system_config`
    里有条运营覆盖），这本身就是一条判据。

基线（供下任一眼看出动了没有）：
  - 11-11 批 8-25 改词表**前**：认出 ≥1 项 29 条／认出值总数 31（动物 9、场景 13、财富 5、
    偷听对象 3、施暴者 1），结构性摆不出参数项 17 条。
  - 改**后**（现网 `1a67bb5` 复跑）：认出 ≥1 项 **33** 条／认出值总数 **39**（动物 14、场景 15、
    弱势对象 1，其余不变），结构性仍是 17 条。
"""
import asyncio
import json
import os
from collections import defaultdict
from typing import Any, Dict, List

import httpx
from sqlalchemy import text as SQLText
from sqlalchemy.ext.asyncio import create_async_engine

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")   # 容器内监听 8080，不是 8000
OUT = os.environ.get("OUT", "/tmp/survey_elements.json")
ENGINE = create_async_engine(os.environ["DATABASE_URL"])


async def rows() -> List[Dict[str, Any]]:
    async with ENGINE.connect() as c:
        r = await c.execute(SQLText("""
            select s.id::text as id, s.audit_status, s.word_count,
                   coalesce(length(s.text), 0) as text_len,
                   (s.prompt_preview is not null) as has_preview,
                   coalesce(c.name, '') as category_name
            from asset_summaries s
            left join asset_categories c on c.id = s.category_id
            order by category_name, s.created_at
        """))
        return [dict(m) for m in r.mappings().all()]


async def bodies(ids: List[str]) -> Dict[str, str]:
    """取每条的开单屏口径稿子（prompt_preview ?? text）。"""
    out: Dict[str, str] = {}
    async with ENGINE.connect() as c:
        for i in ids:
            r = await c.execute(SQLText(
                "select coalesce(prompt_preview, text) as t from asset_summaries where id = :i"
            ), {"i": i})
            out[i] = (r.scalar() or "")
    return out


async def main() -> None:
    login = httpx.post(f"{BASE}/api/auth/login",
                       json={"username": "admin", "password": "admin123"}, timeout=30)
    login.raise_for_status()
    H = {"Authorization": f"Bearer {login.json()['access_token']}"}

    all_rows = await rows()
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        by_cat[r["category_name"] or "（未挂原型）"].append(r)

    print(f"现网文案总数 = {len(all_rows)}")
    print(f"其中未挂原型 = {len(by_cat['（未挂原型）'])} 条")
    print("按原型分布：" + " / ".join(
        f"{k or '（空名）'}:{len(v)}" for k, v in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))
    ))

    summary = []
    for cat, group in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        ids = [g["id"] for g in group]
        texts = await bodies(ids)
        found_map: Dict[str, List[dict]] = {}
        notes: List[str] = []
        for chunk_start in range(0, len(ids), 50):   # _MAX_EXTRACT_ITEMS = 50
            chunk = ids[chunk_start:chunk_start + 50]
            resp = httpx.post(
                f"{BASE}/api/assets/prompt-elements/extract", headers=H,
                json={"texts": {i: texts[i] for i in chunk},
                      "category": cat if cat != "（未挂原型）" else None,
                      "include_unmatched": True},
                timeout=60,
            )
            resp.raise_for_status()
            d = resp.json()
            found_map.update(d.get("items") or {})
            notes = d.get("notes") or []
        n_slots = sum(1 for f in next(iter(found_map.values()), []) or [])
        per = []
        for g in group:
            fl = found_map.get(g["id"]) or []
            hit = [f for f in fl if f.get("current")]
            miss = [f["label"] for f in fl if not f.get("current")]
            per.append({
                "id": g["id"][:8], "audit": g["audit_status"], "len": g["text_len"],
                "preview": g["has_preview"],
                "slots": len(fl), "hit": len(hit), "miss": miss,
                "hit_labels": [f"{f['label']}={f['current']}" for f in hit],
            })
        summary.append({
            "category": cat, "count": len(group),
            "slots_for_this_cat": n_slots,
            "avg_hit": round(sum(p["hit"] for p in per) / len(per), 2) if per else 0,
            "zero_hit_rows": sum(1 for p in per if p["hit"] == 0),
            "no_slot_rows": sum(1 for p in per if p["slots"] == 0),
            "notes": notes,
            "rows": per,
        })

    print("\n=== 每组汇总 ===")
    for s in summary:
        print(f"[{s['category'] or '（空名）'}] 文案 {s['count']} 条｜该型摆 {s['slots_for_this_cat']} 项"
              f"｜平均自动认出 {s['avg_hit']} 项｜0 认出的 {s['zero_hit_rows']} 条｜摆不出参数项的 {s['no_slot_rows']} 条"
              f"｜notes={s['notes']}")

    hit_copies = sum(max(0, s["count"] - s["zero_hit_rows"] - s["no_slot_rows"]) for s in summary)
    hit_values = sum(len(p["hit_labels"]) for s in summary for p in s["rows"])
    no_slot = sum(s["no_slot_rows"] for s in summary)
    per_label: Dict[str, int] = defaultdict(int)
    for s in summary:
        for p in s["rows"]:
            for lab in p["hit_labels"]:
                per_label[lab.split("=")[0]] += 1
    print("\n=== 总口径（与 8-25 基线行比对用）===")
    print(f"文案 {len(all_rows)} 条｜结构性摆不出参数项 {no_slot} 条｜"
          f"可认的 {len(all_rows) - no_slot} 条里认出 ≥1 项的 **{hit_copies}** 条"
          f"｜认出值总数 **{hit_values}**")
    print("按参数项：" + "／".join(f"{k} {v}" for k, v in sorted(per_label.items(), key=lambda kv: -kv[1])))

    print("\n=== 逐条（认出什么／还缺什么）===")
    for s in summary:
        print(f"\n--- {s['category'] or '（空名）'} ---")
        for p in s["rows"]:
            print(f"  {p['id']} {p['audit']:<9} {p['len']:>5}字 稿={p['preview'] and '预览' or '正文'} "
                  f"参数项 {p['slots']}｜认出 {p['hit']}｜缺 {p['miss']}")
            if p["hit_labels"]:
                print(f"        认出：{'；'.join(p['hit_labels'])}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"totals": {"copies": len(all_rows), "no_slot": no_slot,
                              "hit_copies": hit_copies, "hit_values": hit_values,
                              "per_label": per_label},
                   "groups": summary}, f, ensure_ascii=False, indent=1)
    print(f"\n明细已落 {OUT}")
    await ENGINE.dispose()


asyncio.run(main())
