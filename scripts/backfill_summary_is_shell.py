#!/usr/bin/env python3
"""批 X 补标：把存量「脚本生产载体」候选行的 is_shell 置 true。

判定＝引用式（被任何脚本的 carrier_summary_id 指着）。批 X 之后镜像脚本也会指着
**真候选**，所以本脚本只该在部署批 X 后、镜像开始产生之前跑一次（幂等可重跑：
重跑时镜像指向的真候选也会被补标——那时就用 `_mirror` 侧的清理逻辑纠正，
或手工 `UPDATE asset_summaries SET is_shell=false WHERE is_shell AND ...` 点名回滚）。

运行方式（backend 容器内）：
    docker compose exec backend python scripts/backfill_summary_is_shell.py
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, update

from app.database import async_session_factory
from app.models.asset import AssetScript, AssetSummary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [shell] %(levelname)s %(message)s")
logger = logging.getLogger("backfill_is_shell")


async def main() -> None:
    async with async_session_factory() as db:
        refs = (await db.execute(select(AssetScript.carrier_summary_id))).scalars().all()
        ids = {str(x) for x in refs if x}
        if not ids:
            logger.info("没有任何脚本载体，无需补标")
            return
        n = 0
        for sid in ids:
            row = await db.get(AssetSummary, __import__("uuid").UUID(sid))
            if row is not None and not row.is_shell:
                row.is_shell = True
                n += 1
        await db.commit()
        logger.info("补标完成：%s / %s 行壳候选标了 is_shell=true", n, len(ids))


if __name__ == "__main__":
    asyncio.run(main())
