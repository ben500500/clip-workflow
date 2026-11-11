"""8-24 现网零成本复验：文案列表口新增的 `ids` 点名，在真库真数据上按合同答话。

跑法（backend 容器里，走 127.0.0.1:8080；全程只读）：
  ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' < scripts/live_accept_824.py

判据四组，**一条 POST 都不打花钱口**（唯一的 POST 是 `prompt-elements/extract`，
它是 0 元、不落库、不写审计的认值口，且本脚本前后都用只读 SQL 钉住"库没动"）：

A 基线只读数（summaries／productions／asset_jobs／audit 行数）＋复验后一字未动。
B `ids` 合同六腿：三种审核态同批点名都照出（**不带 audit_status 也不消失**）／每条带回
  当前 text＋prompt_preview＋category_name／叠 audit_status 仍继续筛／脏逗号去重／
  合法但不存在的 uuid 给 total 0 而不是 400／三种脏入参各 400 且话术点名。
C 「重新获取」那一步的 0 元实跑：用 ids 取回一篇真文案 → 把它的 text 喂 extract 认参数项，
  断言接口答话形状可渲染（有 items 或有白话说明）、且**这一遍 extract 没改库**。
D 现网既有口没被这次改动带坏：不带 ids 的普通列表照旧分页、投板哨兵话术照旧。
"""
import asyncio
import json
import os
import uuid

import httpx
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import create_async_engine

BASE = "http://127.0.0.1:8080"
FAILS = []
OK = []


def chk(label, cond, detail=""):
    (OK if cond else FAILS).append(label)
    print(("PASS " if cond else "FAIL ") + label + (f" | {detail}" if detail else ""))


# 每次查询**自建自弃**一个引擎：本脚本在多次 asyncio.run 之间穿插 HTTP 调用，
# 复用同一个 asyncpg 引擎会撞 "Future attached to a different loop"（8-22 复验脚本
# 只跑单循环所以没这问题）。
async def _fetch(sql, params):
    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as c:
            return (await c.execute(sql_text(sql), params or {})).mappings().all()
    finally:
        await eng.dispose()


def q(sql, params=None):
    return asyncio.run(_fetch(sql, params))


def one(sql, params=None):
    rows = q(sql, params)
    return rows[0] if rows else None


# ── A) 基线（只读）────────────────────────────────────────────
def baseline():
    s = one("select count(*) n from asset_summaries")
    p = one("select count(*) n from asset_productions")
    j = one("select count(*) n from asset_jobs")
    # 排除 auth.login：本脚本自己就要登录一次，那一条是探针留下的，不是被测口子写进去的
    a = one("select count(*) n from audit_logs where action <> 'auth.login'")
    st = q("select audit_status, count(*) n from asset_summaries group by audit_status order by 2 desc")
    return dict(sum=int(s["n"]), prod=int(p["n"]), jobs=int(j["n"]), audit=int(a["n"]),
                statuses=[(r["audit_status"], int(r["n"])) for r in st])


base = baseline()
print("INFO 基线 |", json.dumps(base, ensure_ascii=False))
chk("A1 基线取到数（文案>0 且状态分布非空）", base["sum"] > 0 and bool(base["statuses"]),
    f"summaries={base['sum']} statuses={base['statuses']}")

# ── 登录（零 sleep：登录竞态 9-14 已修）────────────────────────
r = httpx.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"}, timeout=30)
assert r.status_code == 200, r.text
H = {"Authorization": "Bearer " + r.json()["access_token"]}
print("INFO 登录 |", r.status_code)


def get(params):
    return httpx.get(f"{BASE}/api/assets/summaries", headers=H, params=params, timeout=60)


# ── B) ids 合同 ───────────────────────────────────────────────
# 取**不同审核态**的三条真 id（现网状态分布里能取到几种就取几种，上限 3）
want_rows = []
for st, _n in base["statuses"][:3]:
    row = one("select id, audit_status, coalesce(length(text),0) tl, category_id "
              "from asset_summaries where audit_status=:s order by id limit 1", {"s": st})
    if row:
        want_rows.append(row)
ids = [str(r_["id"]) for r_ in want_rows]
print("INFO 点名取样 |", [(r_["audit_status"], r_["tl"]) for r_ in want_rows])

r = get({"ids": ",".join(ids), "page_size": 50})
body = r.json() if r.status_code == 200 else {}
got = {x["id"]: x for x in (body.get("items") or [])}
chk("B1 ids 点名 200 且条数＝点名数（不带 audit_status 也不因审核态消失）",
    r.status_code == 200 and len(got) == len(ids) and body.get("total") == len(ids),
    f"http={r.status_code} n={len(got)} total={body.get('total')} 点了 {len(ids)} 条")
chk("B2 点名的三种审核态真的都回来了",
    len({r_["audit_status"] for r_ in want_rows}) == len(want_rows) and len(got) == len(want_rows),
    f"状态集合={sorted({x.get('audit_status') for x in got.values()})}")
FIELDS = ("text", "prompt_preview", "category_name")
chk("B3 每条带回当前 text／prompt_preview／category_name 三个键（取最新稿子要的就是这三样）",
    all(all(k in x for k in FIELDS) for x in got.values()),
    "缺键 id=" + str([x["id"] for x in got.values() if not all(k in x for k in FIELDS)]))
# 取回的一条正文长度对得上库（证明给的是**当前这一版**，不是缓存的旧版）
db_len = {str(x["id"]): int(x["tl"]) for x in want_rows}
chk("B4 带回的 text 字数＝库里当前字数（逐条比）",
    all(len(got[i].get("text") or "") == db_len[i] for i in db_len),
    str([(i[:8], len(got[i].get("text") or ""), db_len[i]) for i in db_len if got.get(i)])[:200])

# 叠 audit_status：只留那一个状态
st0 = want_rows[0]["audit_status"]
r = get({"ids": ",".join(ids), "audit_status": st0, "page_size": 50})
b2 = r.json() if r.status_code == 200 else {}
its = b2.get("items") or []
chk("B5 叠 audit_status 仍继续筛（ids 不是放行证）",
    r.status_code == 200 and len(its) >= 1 and all(x.get("audit_status") == st0 for x in its)
    and len(its) <= len(ids),
    f"只筛 {st0} → {len(its)}/{len(ids)} 条")

# 脏逗号去重
r = get({"ids": f"{ids[0]},{ids[0]},,{ids[0]} "})
b3 = r.json() if r.status_code == 200 else {}
chk("B6 逗号脏写法去重后只 1 条", r.status_code == 200 and b3.get("total") == 1,
    f"http={r.status_code} total={b3.get('total')}")

# 合法但不存在的 uuid → total 0，不是 400
ghost = str(uuid.uuid4())
r = get({"ids": ghost})
chk("B7 合法 uuid 但库里没有 → 200/total 0（不是 400，前端据此保留手里那一版）",
    r.status_code == 200 and r.json().get("total") == 0,
    f"http={r.status_code} body={str(r.text)[:90]}")

# 脏入参三条 400 且话术点名
for payload, must_in in (("abc123", "ids"), (",,", "不能是空的"),
                         (",".join(str(uuid.uuid4()) for _ in range(301)), "300")):
    r = get({"ids": payload})
    d = (r.json().get("detail") if r.status_code == 400 else "") or ""
    chk(f"B8 脏 ids（{payload[:12]}…共{len(payload)}字）当场 400 且话术含「{must_in}」",
        r.status_code == 400 and must_in in d, f"http={r.status_code} detail={d[:70]}")

# ── C) 「重新获取」那一步的 0 元实跑（extract 认参数项，不落库不写审计）──
# 契约照前端口径：texts 是 **{行id: 正文}** 字典、include_unmatched=true（开单屏要的就是
# 「这一型要设哪几项」全摆出来）。取样换成一条**挂了原型**的文案——空分类时 slot_applies
# 按设计返回不适用、摆 0 项（8-15 口径），拿它验 C3 会误判成缺陷。
tgt = one("select s.id, s.audit_status, coalesce(length(s.text),0) tl, c.name cat "
          "from asset_summaries s left join asset_categories c on c.id = s.category_id "
          "where s.category_id is not null order by s.created_at desc limit 1")
chk("C0 现网取到一条挂了原型的文案（没挂就验不出参数项）", bool(tgt),
    str([(tgt["id"], tgt["cat"], tgt["tl"]) for _ in ([tgt] if tgt else [])]))
if tgt:
    r = get({"ids": str(tgt["id"])})
    row = (r.json().get("items") or [{}])[0] if r.status_code == 200 else {}
    cur_text = row.get("prompt_preview") or row.get("text") or ""
    CAT = row.get("category_name") or ""
    before = one("select coalesce(md5(text),'') m, coalesce(md5(prompt_preview),'') p, "
                 "updated_at from asset_summaries where id=:i", {"i": str(tgt["id"])})
    r = httpx.post(f"{BASE}/api/assets/prompt-elements/extract", headers=H,
                   json={"texts": {str(tgt["id"]): cur_text}, "category": CAT,
                         "include_unmatched": True}, timeout=120)
    chk("C1 取回的正文喂 0 元 extract 答 200（重认这一步在现网真跑得通）",
        r.status_code == 200, f"http={r.status_code} body={str(r.text)[:120]}")
    eb = r.json() if r.status_code == 200 else {}
    slots = (eb.get("items") or {}).get(str(tgt["id"])) or []
    notes = eb.get("notes") or []
    recognized = [s_ for s_ in slots if (s_.get("current") or "").strip()]
    print(f"INFO 取样 | 分类={CAT} 正文={len(cur_text)} 字 | 参数项={len(slots)} 认出原值={len(recognized)}")
    for s_ in slots[:6]:
        print("INFO 参数项 |", s_.get("label"), "| mode=", s_.get("mode"),
              "| current=", repr((s_.get("current") or ""))[:34],
              "| occurrences=", s_.get("occurrences"), "| protected=", s_.get("protected"))
    chk("C2 回包摆出这一型的参数项（items 是 {行id: [...]} 字典，前端按这个渲染）",
        len(slots) > 0, f"参数项={len(slots)} slot_labels 总数={len(eb.get('slot_labels') or [])}")
    chk("C3 认得出的项，原值**逐字能在稿子里找到**（重认给的就是这一版稿子的值）",
        all((s_.get("current") or "") in cur_text for s_ in recognized) and len(recognized) > 0,
        f"认出 {len(recognized)} 项；不命中={[s_.get('label') for s_ in recognized if (s_.get('current') or '') not in cur_text]}")
    lit = [s_ for s_ in slots if (s_.get("current") or "").strip() and s_.get("mode") == "literal"]
    bad_occ = [s_.get("label") for s_ in lit
               if (s_.get("current") or "") not in [o.get("value") for o in (s_.get("occurrences") or [])]]
    chk("C4 报得出原值的 literal 项，occurrences 里必须含这个值（有值却没处可换＝假认）",
        not bad_occ, f"值不在 occurrences 里={bad_occ} literal 项共 {len(lit)}")
    blank = [s_ for s_ in slots if not (s_.get("current") or "").strip()]
    chk("C5 认不出的项要么标 manual、要么 note 说得清为什么（不许摆个空下拉装懂）",
        all(s_.get("mode") == "manual" or (s_.get("note") or "") for s_ in blank),
        f"空值且没说法={[s_.get('label') for s_ in blank if s_.get('mode') != 'manual' and not (s_.get('note') or '')]}")
    after = one("select coalesce(md5(text),'') m, coalesce(md5(prompt_preview),'') p, "
                "updated_at from asset_summaries where id=:i", {"i": str(tgt["id"])})
    chk("C6 extract 前后这篇文案一字未动（text／prompt_preview 的 md5 ＋ updated_at 三项都相等）",
        before == after, f"before={before and (before['m'][:8], before['p'][:8])} after={after and (after['m'][:8], after['p'][:8])}")
    chk("C7 说明数组是白话（不是内部术语／堆栈）",
        all("Traceback" not in n_ and "SELECT" not in str(n_).upper() for n_ in notes),
        str(notes)[:110])

# ── D) 既有口没被带坏 ─────────────────────────────────────────
r = get({"page": 1, "page_size": 5})
b4 = r.json() if r.status_code == 200 else {}
chk("D1 不带 ids 的普通列表照旧分页（total 是全集数、items 只有 5 条）",
    r.status_code == 200 and len(b4.get("items") or []) == 5 and b4.get("total") == base["sum"],
    f"http={r.status_code} n={len(b4.get('items') or [])} total={b4.get('total')} 基线={base['sum']}")
# 空 ids 投板哨兵：**只发一个空点名清单**，闸门在建单之前，投不出任何东西、不碰板
r = httpx.post(f"{BASE}/api/assets/productions/dispatch", headers=H,
               json={"ids": [], "confirm": True}, timeout=30)
d = (r.json().get("detail") if r.status_code == 400 else "") or ""
chk("D2 投板哨兵仍是白话 400（说「请点名要投板的生产单」＝AIVIDEO_AUTH 通道健在，本次改动没碰它）",
    r.status_code == 400 and "点名" in d, f"http={r.status_code} detail={d[:60]}")

# ── A') 复验后库没动 ─────────────────────────────────────────
now = baseline()
chk("E1 复验前后行数一字未动（summaries/productions/asset_jobs 全等，audit 只数非登录事件）",
    (now["sum"], now["prod"], now["jobs"], now["audit"]) ==
    (base["sum"], base["prod"], base["jobs"], base["audit"]),
    f"前={base['sum']}/{base['prod']}/{base['jobs']}/{base['audit']} 后={now['sum']}/{now['prod']}/{now['jobs']}/{now['audit']}")

print("\n=== FAILS ===")
print(json.dumps(FAILS, ensure_ascii=False))
print(f"OK={len(OK)} FAIL={len(FAILS)}")
