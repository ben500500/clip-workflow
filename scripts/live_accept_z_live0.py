"""批 Z 现网取证里**一分钱不花**那一半：新口答话形状 + 老口没被带坏 + 库真没动。

跑法（163 后端容器里，走 127.0.0.1:8080；全程只读／0 元）：
    ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' \\
      < scripts/live_accept_z_live0.py

六组判据（每条都真打接口，不靠"代码里写了"）：
A 基线只读数（summaries／productions／asset_jobs／audit_logs 排除 auth.login／
  `asset_element_guesses` 行数）＋复跑后一字未动 —— 这是"本脚本自己没写库"的证据。
B 迁移与缓存表本体：`alembic_version.version_num` 到 0069、表 7 列齐、
  `(body_hash, slot_key)` 唯一索引在。⚠️ 8-22 教训：新表可能靠 `create_all` 自愈、
  版本号也可能只是 stamp 上去的，所以**版本号与表本体都要验，幂等靠索引验**。
C 词表口（0 元、可复现）：GET 字典 + POST extract 真稿，每格字段一个不少。
D 模型补位口的**四条 0 元腿**（一次模型都不问）：
  ① 正文全空白 → 「该认的词表都认出来了…（0 元）」；② `only_missing` 给空数组；
  ③ `only_missing` 给字典里没配的键（应被 `allowed` 过滤掉）；④ 没稿子 → 白话 400。
  ①②③都断 `paid=false` 且 `from_model={}`，并断新字段（`paid/auto/from_cache/
  from_model/skipped`）在响应里存在——前端按来源标徽标靠的就是这几个键。
E 老口没带坏：投板两道哨兵（`ids=[]` 白话 400、点名了不存在的单 → 白话 400「整批未投」，
  都不落库不建任务）＋文案列表 `ids` 点名（脏逗号去重／合法不存在给 total 0）＋普通分页。
  ⚠️ 「带不带 `confirm=true`」那一条要一张 `order_ready 且没 board_tid` 的单才打得到闸门；
  现网 5 张全是 `success`（有 tid，点名会归进 `to_recover` 走真回读，不算只读），
  所以那条只由本机用例钉，这里如实换成同族的不存在 id 哨兵。
F 复跑基线 == A（含 audit 与缓存行数）。

不验的（另说）：旋钮 `ASSET_ELEMENT_AUTO_GUESS=false` 那一支在现网翻不了 env，
它的证据是容器 `printenv=true` + 代码 grep（`evidence163_z.sh`）＋本机用例里的负向断言。
"""
import asyncio
import json
import os
import uuid
from typing import Any, Dict, List

import httpx
from sqlalchemy import text as SQLText
from sqlalchemy.ext.asyncio import create_async_engine

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")   # 容器内监听 8080，不是 8000
FAILS: List[str] = []
OK: List[str] = []


def chk(label: str, cond: bool, detail: str = "") -> None:
    (OK if cond else FAILS).append(label)
    print(("PASS " if cond else "FAIL ") + label + (f" | {detail}" if detail else ""))


# 每次查询**自建自弃**一个引擎：本脚本在多次 asyncio.run 之间穿插同步 HTTP 调用，
# 复用同一个 asyncpg 引擎会撞 "Future attached to a different loop"（8-24 复验脚本踩过）。
async def _fetch(sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as c:
            r = await c.execute(SQLText(sql), params or {})
            return [dict(m) for m in r.mappings().all()]
    finally:
        await eng.dispose()


def q(sql: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    return asyncio.run(_fetch(sql, params))


def one(sql: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    rows = q(sql, params)
    return rows[0] if rows else {}


# ── A) 基线 ──────────────────────────────────────────────────
def baseline() -> Dict[str, int]:
    return dict(
        sum=int(one("select count(*) n from asset_summaries")["n"]),
        prod=int(one("select count(*) n from asset_productions")["n"]),
        jobs=int(one("select count(*) n from asset_jobs")["n"]),
        # 排除 auth.login：探针自己就要登录一次，那条不是被测口子写进去的
        audit=int(one("select count(*) n from audit_logs where action <> 'auth.login'")["n"]),
        cache=int(one("select count(*) n from asset_element_guesses")["n"]),
    )


# ── B) 迁移号与缓存表本体 ────────────────────────────────────
ver = one("select version_num from alembic_version")
chk("B1 alembic 版本号到 0069", str(ver["version_num"]).startswith("0069"),
    f"version_num={ver['version_num']}")
cols = q("select column_name from information_schema.columns "
         "where table_name = 'asset_element_guesses' order by ordinal_position")
names = [c["column_name"] for c in cols]
want = ["id", "body_hash", "slot_key", "value", "model", "category", "created_at"]
chk("B2 缓存表 7 列齐且顺序对", names == want, f"列={names}")
idx = q("select indexname, indexdef from pg_indexes where tablename = 'asset_element_guesses'")
two_col = [i["indexname"] for i in idx
           if "body_hash" in i["indexdef"] and "slot_key" in i["indexdef"]]
chk("B3 (body_hash, slot_key) 唯一索引在（「同一格只花一次钱」的真凭据）", bool(two_col),
    f"索引={[i['indexname'] for i in idx]}")

base = baseline()
print("INFO 基线 |", json.dumps(base, ensure_ascii=False))
chk("A1 基线取到数（文案>0 且缓存表可读）", base["sum"] > 0 and base["cache"] >= 0,
    f"summaries={base['sum']} cache={base['cache']}")

# ── 登录（零 sleep：登录竞态 9-14 已修）───────────────────────
login = httpx.post(f"{BASE}/api/auth/login",
                   json={"username": "admin", "password": "admin123"}, timeout=30)
assert login.status_code == 200, login.text
H = {"Authorization": f"Bearer {login.json()['access_token']}"}
print("INFO 登录 |", login.status_code)

# ── C) 词表口（0 元）────────────────────────────────────────
cat = httpx.get(f"{BASE}/api/assets/prompt-elements", headers=H, timeout=30)
cd = cat.json()
chk("C1 字典口 200 且有生效参数项", cat.status_code == 200 and bool(cd.get("effective")),
    f"生效 {len(cd.get('effective') or [])} 行｜has_override={cd.get('has_override')}")

# 取最长那篇挂原型的真稿（与开单屏同口径：认的是 prompt_preview ?? text）
drafts = q("""
    select s.id::text as id, c.name as category_name,
           coalesce(length(coalesce(s.prompt_preview, s.text)), 0) as len,
           coalesce(s.prompt_preview, s.text) as body
    from asset_summaries s
    join asset_categories c on c.id = s.category_id
    order by len desc limit 6
""")
drafts = [d for d in drafts if d["len"] <= 100]   # 别拿反推长提示词做花钱判据（那是另一批要验的量级）
chk("C2 取到挂原型的真稿", len(drafts) >= 3,
    f"{len(drafts)} 条｜最长 {drafts[0]['len']} 字｜原型={drafts[0]['category_name'][:12]}")
pick = drafts[0]

ext = httpx.post(f"{BASE}/api/assets/prompt-elements/extract", headers=H, json={
    "texts": {pick["id"]: pick["body"]}, "category": pick["category_name"],
    "include_unmatched": True,
}, timeout=120)
ed = ext.json()
cells = next(iter(ed["items"].values()), []) if isinstance(ed.get("items"), dict) else []
chk("C3 extract 0 元仍答话", ext.status_code == 200 and bool(cells),
    f"该型摆 {len(cells)} 格｜字典 slot_labels={str(ed.get('slot_labels'))[:60]}")
need_fields = {"key", "label", "mode", "current", "context", "occurrences",
               "pool", "custom", "categories", "note", "protected"}
missing_fields = sorted(need_fields - set(cells[0].keys())) if cells else ["<空>"]
chk("C4 每格字段齐（前端徽标／浮窗要的都在）", not missing_fields, f"缺={missing_fields}")
hit = [c for c in cells if c.get("current")]
gap = [c for c in cells if not c.get("current")]
print(f"INFO 这篇真稿词表认出 {len(hit)} 格／还空 {len(gap)} 格："
      f"{[c['label'] for c in gap]}")

# ── D) 模型补位口的四条 0 元腿 ───────────────────────────────
def guess(payload: Dict[str, Any]) -> Dict[str, Any]:
    r = httpx.post(f"{BASE}/api/assets/prompt-elements/guess-values", headers=H,
                   json=payload, timeout=600)
    is_json = str(r.headers.get("content-type", "")).startswith("application/json")
    return {"status": r.status_code, "body": r.json() if is_json else {"detail": r.text}}


leg1 = guess({"texts": {pick["id"]: "   "}, "category": pick["category_name"],
              "auto": True, "use_cache": True})
b1 = leg1["body"]
chk("D1 正文空白 → 200 且 paid=false（一次模型都没问）",
    leg1["status"] == 200 and b1.get("paid") is False and b1.get("from_model") == {},
    f"status={leg1['status']} notes={str(b1.get('notes'))[:56]}")
chk("D2 白话说清「没问模型（0 元）」",
    any("0 元" in str(n) for n in b1.get("notes") or []), f"notes={str(b1.get('notes'))[:110]}")

leg2 = guess({"texts": {pick["id"]: pick["body"]}, "category": pick["category_name"],
              "auto": True, "use_cache": True, "only_missing": {pick["id"]: []}})
chk("D3 only_missing 给空数组 → 同样 0 元",
    leg2["status"] == 200 and leg2["body"].get("paid") is False
    and (leg2["body"].get("values") or {}) == {},
    f"paid={leg2['body'].get('paid')}")

leg3 = guess({"texts": {pick["id"]: pick["body"]}, "category": pick["category_name"],
              "auto": True, "use_cache": True, "only_missing": {pick["id"]: ["__没配过的键__"]}})
chk("D4 字典里没配的键被过滤掉 → 0 元且没编值",
    leg3["status"] == 200 and leg3["body"].get("paid") is False
    and (leg3["body"].get("values") or {}) == {},
    f"paid={leg3['body'].get('paid')} dropped={str(leg3['body'].get('dropped'))[:60]}")

leg4 = guess({"texts": {}, "category": pick["category_name"], "auto": True})
chk("D5 没稿子当场白话 400", leg4["status"] == 400 and "没有稿子正文" in str(leg4["body"]),
    f"status={leg4['status']} detail={str(leg4['body'].get('detail'))[:50]}")

new_keys = {"paid", "auto", "from_cache", "from_model", "skipped",
            "values", "dropped", "notes", "model", "slot_count", "text_count", "total_chars"}
absent = sorted(new_keys - set(b1.keys()))
chk("D6 合同字段齐（前端标「词表／模型抄回／上次抄回」靠这几个键）", not absent, f"缺={absent}")

# ── E) 老口没被带坏 ──────────────────────────────────────────
d0 = httpx.post(f"{BASE}/api/assets/productions/dispatch", headers=H,
                json={"ids": [], "confirm": True}, timeout=60)
chk("E1 投板哨兵仍答「请点名要投板的生产单」（AIVIDEO_AUTH 通道健在）",
    d0.status_code == 400 and "请点名要投板" in str(d0.json().get("detail", "")),
    f"status={d0.status_code} detail={str(d0.json().get('detail'))[:60]}")

ready = q("select id::text as i, hook_code, status from asset_productions "
          "where status = 'order_ready' and board_tid is null order by created_at limit 3")
print("INFO 未投的 order_ready 单 |", json.dumps(ready, ensure_ascii=False)[:160])
if ready:
    d1 = httpx.post(f"{BASE}/api/assets/productions/dispatch", headers=H,
                    json={"ids": [ready[0]["i"]], "confirm": False}, timeout=60)
    dd = str(d1.json().get("detail", "")) if d1.headers.get(
        "content-type", "").startswith("application/json") else d1.text
    chk("E2 真单不带 confirm → 白话 400（逐批人工确认这道闸还在）",
        d1.status_code == 400 and "confirm=true" in dd,
        f"status={d1.status_code} detail={dd[:70]}")
else:
    # 现网没这张单时**不能**拿已投过的单去点名——`_dispatch_gate` 会把带 tid 的单归进
    # `to_recover`，那是一次真的板面回读（还会写 `board_last_status`），不属于"0 元只读"。
    # 改点一个合法但不存在的 uuid：这条 400 在闸门之前、连库都不查第二遍，纯白话成因。
    d2 = httpx.post(f"{BASE}/api/assets/productions/dispatch", headers=H,
                    json={"ids": [str(uuid.uuid4())], "confirm": True}, timeout=60)
    dd2 = str(d2.json().get("detail", "")) if d2.headers.get(
        "content-type", "").startswith("application/json") else d2.text
    chk("E2 现网无「order_ready 且没 tid」的单（confirm 闸改由本机用例钉）；"
        "改验不存在的 id → 白话 400 说「整批未投」",
        d2.status_code == 400 and "整批未投" in dd2,
        f"status={d2.status_code} detail={dd2[:70]}")

ids = [r["id"] for r in drafts[:3]]
lst = httpx.get(f"{BASE}/api/assets/summaries", headers=H,
                params={"ids": ",".join(ids) + f",{ids[0]},,,"}, timeout=30)
lb = lst.json()
chk("E3 文案列表 ids 点名：脏逗号去重、按真 id 出 3 条",
    lst.status_code == 200 and lb.get("total") == 3,
    f"status={lst.status_code} total={lb.get('total')}")
row = (lb.get("items") or [{}])[0]
chk("E4 点名的每条带回 text／prompt_preview／category_name",
    all(k in row for k in ("text", "prompt_preview", "category_name")),
    f"字段={sorted(row.keys())[:6]}…")
ghost = httpx.get(f"{BASE}/api/assets/summaries", headers=H,
                  params={"ids": str(uuid.uuid4())}, timeout=30)
chk("E5 合法但不存在的 uuid 给 total=0 而不是 400",
    ghost.status_code == 200 and ghost.json().get("total") == 0,
    f"status={ghost.status_code} total={ghost.json().get('total')}")
plain = httpx.get(f"{BASE}/api/assets/summaries", headers=H,
                  params={"page": 1, "page_size": 5}, timeout=30)
chk("E6 不带 ids 的普通列表照旧分页",
    plain.status_code == 200 and len(plain.json().get("items") or []) > 0,
    f"total={plain.json().get('total')}")
risk = httpx.get(f"{BASE}/api/assets/risk-lexicon", headers=H, timeout=30)
chk("E7 风险词库口没被带坏（读全员）", risk.status_code == 200, f"status={risk.status_code}")

# ── F) 复跑基线 == A ────────────────────────────────────────
after = baseline()
chk("F1 复跑与基线一字未动（本脚本没写库、没花钱）", after == base,
    f"前={base} 后={after}")
login_rows = one("select count(*) n from audit_logs where action = 'auth.login'")
print(f"INFO 本次自留 auth.login 行数（已从基线口径排除）= {login_rows['n']}")

print("\n=== 汇总 ===")
print(f"PASS {len(OK)} / FAIL {len(FAILS)}")
if FAILS:
    print("失败条目：" + "；".join(FAILS))
    raise SystemExit(1)
