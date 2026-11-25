"""批X-补 前置只读核查 v2（163，只读；每条独立连接，一处表名错不拖垮全篇）。"""
import asyncio

from sqlalchemy import text

from app.database import engine

CHECKS = [
    ("tables", "select table_name from information_schema.tables where table_schema='public' and table_name like 'asset%' order by 1"),
    ("need_mirror", """
        select count(*) from asset_summaries s
        where coalesce(s.is_shell, false) = false
          and s.text is not null and length(trim(s.text)) > 0
          and not exists (select 1 from asset_scripts sc where sc.carrier_summary_id = s.id)
    """),
    ("by_owner", """
        select a.created_by, count(*) from asset_summaries s
        join asset_items a on a.id = s.asset_id
        where coalesce(s.is_shell, false) = false
          and s.text is not null and length(trim(s.text)) > 0
          and not exists (select 1 from asset_scripts sc where sc.carrier_summary_id = s.id)
        group by a.created_by order by count(*) desc
    """),
]


async def run(label, sql):
    try:
        async with engine.connect() as c:
            rows = (await c.execute(text(sql))).fetchall()
        print(f"{label} :: " + ("; ".join(",".join(str(x) for x in r) for r in rows) or "(空)"))
    except Exception as e:  # noqa: BLE001
        print(f"{label} :: ERROR {type(e).__name__}: {str(e)[:160]}")


async def main():
    for label, sql in CHECKS:
        await run(label, sql)


asyncio.run(main())
print("PROBE2_DONE")
