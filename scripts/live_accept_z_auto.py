"""批 Z 现网**第一枪自动补位**：真花钱问一次模型 → 同一份稿子再请求一次必须 0 元 → 全量覆盖率重测。

跑法（163 后端容器里，走 127.0.0.1:8080；`MODE` 四档，默认 `check`）：
    ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -u -' \\
      < scripts/live_accept_z_auto.py
    MODE=estimate 同上一条        # 先量再放：只数「这次真花钱要打掉几格」，一个字的模型都不问
    MODE=check                    # 只点最短的两篇真稿各打一枪（钱最少的一档）
    MODE=full                     # 全部仍空着格子的文案按原型分组补完（≤5 篇／批）＋ 覆盖率重测
    MODE=retry                    # 只补没落进缓存的那几批（比如某批 500 掉了）；跳过第一枪那两篇
  花钱之前**一律先跑 MODE=estimate**（8-26 自己留在进度总览里的硬前置：「第一次现网自动花钱的
  量级要按认不出的格子数 × 篇数预估后再放」）。别只看结尾那行 PASS/FAIL 计数：**0 红 ≠ 全绿**，先确认日志里有
  `INFO 批 N`／`INFO 第一枪`——闸门写错模式时这脚本会一批都不打却报成干净。
  ⚠️ 明细 JSON 落在**容器** `/tmp`，`docker compose up -d` 重建容器就没了；要留证就当场吐回宿主机。

为什么这一枪必须真打（8-26 遗留的那句提醒）：
  - 本机 648 条用例里模型那一路是打桩的，缓存命中／`only_missing` 不重复花钱／
    `dropped` 丢弃编造值这三条只证明了**形状**，没证明现网 mimo 真能抄回逐字原文；
  - 8-23 只真跑过**人工点**那一支（1 篇 3 格），自动补位这一支在现网从没出过钱。

判据三组：
① 第一枪（`auto=true` + `only_missing`＝词表没认出的那几格）：
   `paid=true`、`model` 非空、`from_model` 有行；抄回来的每个值**逐字**出现在这份稿子里
   （不在＝模型编的，必须进 `dropped`）；`asset_element_guesses` 行数增加；
   `audit_logs` 恰好多 1 条 `asset.prompt_elements.guess_values`；文案 `md5/updated_at` 一字未动。
② 同一请求原样再打一次：`paid=false`、值全在 `from_model`→改由 `from_cache` 端出、
   且两次的 `values` **逐字相同**；缓存行数与 audit 不再变（这一条就是"只花一次钱"的现网证据）。
③ `MODE=full`：把全部挂原型且仍有空格的文案按原型分组、每组 ≤5 篇一批自动补完，
   输出批 Z 之后的**覆盖率口径**（认出 ≥1 项的篇数／格子总数／按参数项分布／仍全空的篇数），
   替掉 8-25 那句"38 条残留"——那个数只测词表那一遍，测不到自动补位。

花的钱：一次一批 ≈ 与出文案同档（11-04 实测 0.19 元／批）。全量约 15 批、稿子合计 3.4 千字。
"""
import asyncio
import hashlib
import json
import os
from collections import defaultdict
from typing import Any, Dict, List

import httpx
from sqlalchemy import text as SQLText
from sqlalchemy.ext.asyncio import create_async_engine

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
MODE = os.environ.get("MODE", "check")            # check＝只打第一枪；full＝全量补完
OUT = os.environ.get("OUT", "/tmp/z_auto.json")
FAILS: List[str] = []
OK: List[str] = []


def chk(label: str, cond: bool, detail: str = "") -> None:
    (OK if cond else FAILS).append(label)
    print(("PASS " if cond else "FAIL ") + label + (f" | {detail}" if detail else ""))


# 每次查询自建自弃引擎（穿插同步 HTTP，复用同一 asyncpg 引擎会撞跨 loop 的 Future）
async def _fetch(sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as c:
            r = await c.execute(SQLText(sql), params or {})
            return [dict(m) for m in r.mappings().all()]
    finally:
        await eng.dispose()


def q(sql: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    return asyncio.run(_fetch(sql, params or {}))


def one(sql: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    rows = q(sql, params)
    return rows[0] if rows else {}


login = httpx.post(f"{BASE}/api/auth/login",
                   json={"username": "admin", "password": "admin123"}, timeout=30)
assert login.status_code == 200, login.text
H = {"Authorization": f"Bearer {login.json()['access_token']}"}
print("INFO 登录 |", login.status_code, "MODE =", MODE)


def extract(texts: Dict[str, str], category: str) -> Dict[str, Any]:
    r = httpx.post(f"{BASE}/api/assets/prompt-elements/extract", headers=H, json={
        "texts": texts, "category": category, "include_unmatched": True}, timeout=300)
    r.raise_for_status()
    return r.json()


def guess(texts: Dict[str, str], category: str, only_missing: Dict[str, List[str]],
          auto: bool = True) -> Dict[str, Any]:
    r = httpx.post(f"{BASE}/api/assets/prompt-elements/guess-values", headers=H, json={
        "texts": texts, "category": category, "auto": auto,
        "use_cache": True, "only_missing": only_missing}, timeout=900)
    is_json = str(r.headers.get("content-type", "")).startswith("application/json")
    return {"status": r.status_code, "body": r.json() if is_json else {"detail": r.text}}


def counts() -> Dict[str, int]:
    return dict(
        cache=int(one("select count(*) n from asset_element_guesses")["n"]),
        audit_guess=int(one("select count(*) n from audit_logs "
                            "where action = 'asset.prompt_elements.guess_values'")["n"]),
    )


# 全部挂原型的文案（开单屏同口径：认 prompt_preview ?? text）
rows = q("""
    select s.id::text as id, c.name as category,
           coalesce(length(coalesce(s.prompt_preview, s.text)), 0) as len,
           coalesce(s.prompt_preview, s.text) as body,
           s.updated_at, md5(coalesce(s.prompt_preview, s.text)) as body_md5
    from asset_summaries s
    join asset_categories c on c.id = s.category_id
    order by c.name, s.created_at
""")
by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
for r in rows:
    by_cat[r["category"]].append(r)
print(f"INFO 挂原型文案 {len(rows)} 条／{len(by_cat)} 组")

# 词表先过一遍，算出每条还空着哪几格
gap: Dict[str, Dict[str, Any]] = {}
for cat, group in by_cat.items():
    ids = [g["id"] for g in group]
    texts = {g["id"]: g["body"] for g in group}
    found: Dict[str, List[dict]] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        found.update(extract({k: texts[k] for k in chunk}, cat).get("items") or {})
    for g in group:
        cells = found.get(g["id"]) or []
        blanks = [str(c["key"]) for c in cells if not c.get("current")]
        hit = [c for c in cells if c.get("current")]
        if blanks:
            gap[g["id"]] = {"id": g["id"], "cat": cat, "body": g["body"], "len": g["len"],
                            "updated_at": str(g["updated_at"]), "body_md5": g["body_md5"],
                            "blanks": blanks, "hit": len(hit), "hit_labels":
                            [f"{c['label']}={c['current']}" for c in hit],
                            "blank_labels": [str(c["label"]) for c in cells
                                             if not c.get("current")]}
print(f"INFO 词表后仍有空格的文案 = {len(gap)} 条｜空格总数 = {sum(len(v['blanks']) for v in gap.values())}"
      f"｜稿子合计 {sum(v['len'] for v in gap.values())} 字")

# ── MODE=estimate：只算「这次真花钱要打掉多少格」，一个字的模型都不问 ──
# 花钱量级要先预估再放（用户 11-11 口径），尤其是补跑那些上次 500 掉的批次。
if MODE == "estimate":
    per_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"rows": 0, "cells": 0, "uncached": 0})
    for v in gap.values():
        h = hashlib.sha256(v["body"].encode()).hexdigest()
        known = {r["slot_key"] for r in q(
            "select slot_key from asset_element_guesses where body_hash = :h", {"h": h})}
        pc = per_cat[v["cat"]]
        pc["rows"] += 1
        pc["cells"] += len(v["blanks"])
        pc["uncached"] += len([k for k in v["blanks"] if k not in known])
    print("=== 预估（真要打模型的格子＝空格 − 已问过的那格）===")
    tot = 0
    for cat, pc in sorted(per_cat.items(), key=lambda kv: -kv[1]["uncached"]):
        if pc["uncached"]:
            print(f"  {cat[:14]:<14}｜待问 {pc['uncached']:>3} 格｜{pc['rows']} 篇有空格"
                  f"（空格共 {pc['cells']}）")
            tot += pc["uncached"]
        else:
            print(f"  {cat[:14]:<14}｜0 格（全在缓存里，这一组 0 元）")
    print(f"合计要打 {tot} 格｜按 ≤5 篇/次分批 ≈ {sum(1 for c in per_cat.values() if c['uncached'])}"
          f" 组里有活；11-04 实测一档 ≈0.19 元/批，据此预估这一枪最多几毛钱")
    raise SystemExit(0)

# ── ① 第一枪（2 篇：在 ≤100 字的真稿里挑最长的，稿子越短越可能确实没写那一格）──
short_enough = [v for v in gap.values() if v["len"] <= 100] or list(gap.values())
picks = sorted(short_enough, key=lambda v: -v["len"])[:2]
# MODE=retry：只补没落进缓存的那几批（比如某批 500 掉了）。第一枪那 2 篇此时
# 早就全在缓存里，再打只会拿到 paid=false，把 G1 判成假红——这里直接跳过。
if MODE == "retry":
    print("INFO MODE=retry：跳过第①段第一枪，只跑第③段按原型分批补完")
    picks = []
pre = counts()
print("INFO 花钱前 |", json.dumps(pre, ensure_ascii=False))
paid_rows: List[Dict[str, Any]] = []
for p in picks:
    print(f"INFO 点枪 | {p['id'][:8]} {p['cat'][:10]} {p['len']}字 空格 {p['blank_labels']} "
          f"｜词表已认出 {p['hit']} 格")
    first = guess({p["id"]: p["body"]}, p["cat"], {p["id"]: p["blanks"]})
    b = first["body"]
    ok_status = first["status"] == 200
    chk(f"G1[{p['id'][:8]}] 第一枪 200 且 paid=true", ok_status and b.get("paid") is True,
        f"status={first['status']} detail={str(b.get('detail'))[:60]}")
    vals = (b.get("values") or {}).get(p["id"], {})
    chk(f"G2[{p['id'][:8]}] 模型名回显＋至少补到一格", bool(b.get("model")) and len(vals) >= 1,
        f"model={b.get('model')} 补到={len(vals)}/{len(p['blanks'])}")
    fake = {k: v for k, v in vals.items() if str(v) not in p["body"]}
    chk(f"G3[{p['id'][:8]}] 抄回的每个值逐字在这份稿子里（编的一律没进 values）",
        not fake, f"越界={json.dumps(fake, ensure_ascii=False)[:120]}")
    dropped = b.get("dropped") or []
    if fake:
        chk(f"G4[{p['id'][:8]}] 越界的值都进了 dropped 白话", all(
            any(str(v)[:6] in str(d) for d in dropped) for v in fake.values()),
            f"dropped={str(dropped)[:160]}")
    after = counts()
    chk(f"G5[{p['id'][:8]}] 结果落进缓存表（行数增加）", after["cache"] > pre["cache"],
        f"cache {pre['cache']}→{after['cache']}")
    # 同一篇第二次问＝同一把 body_hash＋同一格，缓存里必须能查到
    hit_cache = q("select slot_key, value, model from asset_element_guesses "
                  "where body_hash = :h order by slot_key", {"h": hashlib.sha256(
                      p["body"].encode()).hexdigest()})
    # 11-11 修法之后的口径：问过的**每一格**都要有一行，抄到的存原文、没抄到的存空串。
    # （改之前这里只存抄到的，结果没抄到的那格每次打开都重新花钱问同一个空。）
    # ⚠️ 判据本身也跟着改过一版：原来那条 `all(缓存值 == 本次补到的值)` 把**空串行**也拿去
    # 和 `vals` 比，于是修法生效后这里必红（空串行天然不在 vals 里）——那是判据落后，
    # 不是现网没记。现在按「问过的每格恰有一行＋抄到的那几格逐字一致＋没抄到的那几格是空串」判。
    chk(f"G6[{p['id'][:8]}] 问过的每一格都落了行，抄到的那几格值一致",
        {c["slot_key"] for c in hit_cache} == set(p["blanks"]) and all(
            (c["value"] or "") == vals[c["slot_key"]]
            for c in hit_cache if c["slot_key"] in vals),
        f"缓存 {sorted(c['slot_key'] for c in hit_cache)}／空格 {sorted(p['blanks'])}"
        f"／补到 {sorted(vals)}")
    empty_cached = [c["slot_key"] for c in hit_cache if not (c["value"] or "").strip()]
    chk(f"G6b[{p['id'][:8]}] 没抄到的那格记成空串＝已知答案（不再重复花钱问）",
        set(empty_cached) == set(p["blanks"]) - set(vals),
        f"空串行={empty_cached} 空格={p['blanks']} 补到={list(vals)}")
    # 二次请求：同一份稿子原样再打一次必须 0 元
    second = guess({p["id"]: p["body"]}, p["cat"], {p["id"]: p["blanks"]})
    s = second["body"]
    chk(f"G7[{p['id'][:8]}] 同一请求再打一次 paid=false（没再问模型）",
        second["status"] == 200 and s.get("paid") is False,
        f"status={second['status']} model={s.get('model')}")
    v2 = (s.get("values") or {}).get(p["id"], {})
    chk(f"G8[{p['id'][:8]}] 两次的值逐字相同且全部来自 from_cache",
        json.dumps(v2, ensure_ascii=False, sort_keys=True)
        == json.dumps(vals, ensure_ascii=False, sort_keys=True)
        and sorted((s.get("from_cache") or {}).get(p["id"], [])) == sorted(vals.keys())
        and (s.get("from_model") or {}).get(p["id"], {}) == {},
        f"from_cache={len((s.get('from_cache') or {}).get(p['id'], []))} 格")
    chk(f"G9[{p['id'][:8]}] 二次请求没再写缓存／没再落审计", counts() == after,
        f"{json.dumps(counts(), ensure_ascii=False)}")
    now = one("select md5(coalesce(prompt_preview, text)) as body_md5, updated_at "
              "from asset_summaries where id = :i", {"i": p["id"]})
    chk(f"G10[{p['id'][:8]}] 这一枪只认不写：稿子 md5 与 updated_at 与打枪前一字未动",
        str(now["body_md5"]) == str(p["body_md5"]) and str(now["updated_at"]) == str(p["updated_at"]),
        f"前 md5={str(p['body_md5'])[:10]} updated_at={p['updated_at']} ｜ "
        f"后 md5={str(now['body_md5'])[:10]} updated_at={now['updated_at']}")
    paid_rows.append({"id": p["id"], "blanks": p["blanks"], "first": b, "second": s})

aud = q("select action, count(*) n from audit_logs where action = "
        "'asset.prompt_elements.guess_values' group by action")
print(f"INFO 现网 guess_values 审计行 = {aud}")

# ── ③ MODE=full：把剩下的空格全补完，重测覆盖率 ────────────
coverage: Dict[str, Any] = {}
if MODE in ("full", "retry"):
    done = {p["id"] for p in paid_rows}
    batches = 0
    paid_calls = 0
    per_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for gid, info in gap.items():
        per_cat[info["cat"]].append(info)
    for cat, group in sorted(per_cat.items(), key=lambda kv: -len(kv[1])):
        todo = [g for g in group if g["id"] not in done]
        # 服务端 `select_guess_batch` 自己也按 ≤5 篇／12000 字收，这里先按同口径切，
        # 免得一次塞 20 篇只回了前 5 篇却以为全补完了
        buf: List[Dict[str, Any]] = []
        chunks: List[List[Dict[str, Any]]] = []
        for g in todo:
            if len(buf) >= 5 or (buf and sum(x["len"] for x in buf) + g["len"] > 12000):
                chunks.append(buf)
                buf = []
            buf.append(g)
        if buf:
            chunks.append(buf)
        for ch in chunks:
            texts = {c["id"]: c["body"] for c in ch}
            only = {c["id"]: c["blanks"] for c in ch}
            before = counts()
            res = guess(texts, cat, only)
            batches += 1
            b = res["body"]
            if res["status"] != 200:
                print(f"FAIL 批次非 200 | {cat[:10]} {len(ch)} 篇 → {str(b.get('detail'))[:100]}")
                FAILS.append(f"批次 HTTP {res['status']}（{cat}）")
                continue
            if b.get("paid"):
                paid_calls += 1
            after = counts()
            print(f"INFO 批 {batches} | {cat[:12]} {len(ch)} 篇｜paid={b.get('paid')} "
                  f"补到={sum(len(v) for v in (b.get('from_model') or {}).values())}格"
                  f"｜缓存命中={sum(len(v) for v in (b.get('from_cache') or {}).values())}格"
                  f"｜丢弃={len(b.get('dropped') or [])}｜skipped={len(b.get('skipped') or [])}"
                  f"｜cache {before['cache']}→{after['cache']}")
            if b.get("skipped"):
                print(f"     这批装不下被分批留下的稿子：{b['skipped']}")
    # 补完后再走一遍纯 0 元口径：词表认出的 ＋ 缓存里有的
    filled_rows = 0
    filled_cells = 0
    per_label: Dict[str, int] = defaultdict(int)
    still_empty: List[str] = []
    detail_rows: List[Dict[str, Any]] = []
    for cat, group in by_cat.items():
        ids = [g["id"] for g in group]
        texts = {g["id"]: g["body"] for g in group}
        found: Dict[str, List[dict]] = {}
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            found.update(extract({k: texts[k] for k in chunk}, cat).get("items") or {})
        for g in group:
            cells = found.get(g["id"]) or []
            if not cells:
                continue
            hashes = hashlib.sha256(g["body"].encode()).hexdigest()
            cached = q("select slot_key, value from asset_element_guesses where body_hash = :h",
                       {"h": hashes})
            cmap = {c["slot_key"]: c["value"] for c in cached}
            got = []
            for c in cells:
                val = c.get("current") or cmap.get(str(c["key"]), "")
                if val:
                    got.append((str(c["label"]), str(val)))
            if got:
                filled_rows += 1
                filled_cells += len(got)
                for lab, _ in got:
                    per_label[lab] += 1
            else:
                still_empty.append(g["id"][:8])
            detail_rows.append({"id": g["id"][:8], "cat": cat[:6], "len": g["len"],
                                "cells": len(cells), "filled": len(got),
                                "filled_labels": [f"{a}={b}" for a, b in got]})
    coverage = {
        "drafts_with_slots": len(detail_rows),
        "filled_rows": filled_rows,
        "filled_cells": filled_cells,
        "still_empty": still_empty,
        "per_label": dict(sorted(per_label.items(), key=lambda kv: -kv[1])),
        "batches": batches,
        "paid_calls_this_run": paid_calls,
        "cache_rows": counts()["cache"],
    }
    print("\n=== 批 Z 之后的覆盖率口径（词表认出的 ＋ 模型补回且逐字在稿里的）===")
    print(f"有参数项的文案 {coverage['drafts_with_slots']} 条｜补完仍有值的 **{filled_rows}** 条"
          f"｜格子总数 **{filled_cells}**｜全空的 {len(still_empty)} 条：{still_empty[:12]}")
    print("按参数项：" + "／".join(f"{k} {v}" for k, v in coverage["per_label"].items()))
    print(f"本次共打 {batches} 批，其中花钱 {paid_calls} 批；缓存表现有 {coverage['cache_rows']} 行")

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"mode": MODE, "gap_rows": len(gap), "picks": paid_rows,
               "coverage": coverage}, f, ensure_ascii=False, indent=1, default=str)
print(f"\n明细已落 {OUT}")
print("\n=== 汇总 ===")
print(f"PASS {len(OK)} / FAIL {len(FAILS)}")
if FAILS:
    print("失败条目：" + "；".join(FAILS))
    raise SystemExit(1)
