"""0 元复算 `live_accept_z_auto.py` 的 G6：把已落库的缓存行摆出来，逐字对上**第一枪**抄回的值。

跑法（163 后端容器内，全程只读、不再打任何接口）：
    ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' \\
      < scripts/live_accept_z_g6_recheck.py

为什么要单独一份：那两篇点枪的稿子已经进缓存，再打一次只会走缓存（`paid=false`），
`G1 期望 paid=true` 反倒会红——所以补绿只能拿**已经落库的行**对**已经落盘的第一枪响应**。

第一枪已经花过钱了，这两篇现在再打只会走缓存（paid=false），所以这里**不再打接口**，
只把 `asset_element_guesses` 的行跟 `/tmp/z_auto.json` 里第一次响应的 `values` 对一遍。

⚠️ 那份 JSON 落在**容器** `/tmp`，`docker compose up -d` 重建容器就没了（11-11 晚实测）。
第二天要重放：要么从本机那趟 stdout 落盘（`/tmp/z_retry_*.log`）里把 `values` 抠回来，
要么改成直接拿现网缓存行对稿子（本脚本判据 ③ 就是这么改的）。
"""
import hashlib
import json
import os

from sqlalchemy import text as SQLText
from sqlalchemy.ext.asyncio import create_async_engine
import asyncio

IDS = ("30acc455", "cfe9d6e9")


async def main():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    async with eng.connect() as c:
        rows = (await c.execute(SQLText(
            "select id::text id, md5(coalesce(prompt_preview, text)) m, "
            "coalesce(prompt_preview, text) body from asset_summaries"))).mappings().all()
        detail = {}
        for r in rows:
            if not str(r["id"]).startswith(IDS):
                continue
            h = hashlib.sha256((r["body"] or "").encode("utf-8")).hexdigest()
            g = (await c.execute(SQLText(
                "select slot_key, value, model, category from asset_element_guesses "
                "where body_hash = :h order by slot_key"), {"h": h})).mappings().all()
            detail[str(r["id"])[:8]] = {
                "hash": h[:10], "rows": [{"k": x["slot_key"], "v": x["value"],
                                          "model": x["model"], "cat": x["category"]}
                                         for x in g]}
        await eng.dispose()

    shot = json.load(open("/tmp/z_auto.json"))
    first = {str(p["id"])[:8]: (p.get("first") or {}) for p in (shot.get("picks") or [])}
    for sid, d in sorted(detail.items()):
        got = {x["k"]: x["v"] for x in d["rows"]}
        vals = (first.get(sid) or {}).get("values", {}).get(
            next((k for k in (first.get(sid) or {}).get("values", {})), ""), {})
        print(f"INFO {sid} hash={d['hash']} 缓存行={json.dumps(got, ensure_ascii=False)}")
        print(f"     第一枪 values={json.dumps(vals, ensure_ascii=False)}")
        pos = {k: v for k, v in got.items() if str(v or "").strip()}
        neg = [k for k, v in got.items() if not str(v or "").strip()]
        ok = pos == vals and set(got) == set(vals) | set(neg) and len(got) == len(vals) + len(neg)
        print(("PASS " if ok else "FAIL ") +
              f"G6[{sid}] 问过的每格恰有一行＋抄到的逐字一致＋没抄到的存空串"
              f" | 正样本={list(pos)} 空串行={neg}")


asyncio.run(main())
