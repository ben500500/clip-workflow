#!/usr/bin/env python3
"""批 W 数据搬迁：asset_items 里的图片行（media_kind='image'）→ asset_cards 角色卡库。

11-25 用户口径「这个图片不要入库」——角色卡不再当素材行摆着。本脚本把存量图片行
原 id 迁进 asset_cards（**id 不变**，已挂卡的生产单 `card_asset_ids` 不用重挑），
迁完在**同一个事务**里核完引用再删旧行。

运行方式（backend 容器内，复用其 DB 配置）：
    docker compose exec backend python scripts/migrate_cards_from_items.py            # 默认 dry-run
    docker compose exec backend python scripts/migrate_cards_from_items.py --execute  # 真迁（先备份 DB！）

先备份再跑：
    docker compose exec -T postgres sh -c 'pg_dump -U $POSTGRES_USER $POSTGRES_DB' | gzip > ~/clip-db-pre-cards.sql.gz

搬迁口径：
  - 复制列映射：id/code 不变；owner_id ← created_by；name ← file_name 去扩展名（空则「角色卡」）；
    file_name/file_key/bucket/file_size/resolution 原样；note 记「11-25 批 W 自素材库迁入」。
  - 同 id 已在 asset_cards → 跳过（幂等，可重跑）。
  - 删除前的硬校验（任一不为 0 就中止，不删行）：
      · asset_summaries.asset_id 引用图片行（图片本不该有候选，有＝数据被手工改过）；
      · asset_frames.asset_id 引用图片行（图片本不该抽帧）；
      · asset_productions.asset_id 引用图片行；
      · asset_productions.concat_asset_id 引用图片行。
    card_asset_ids 不校验——它的 id 随迁进卡表，删完旧行照样解析得出。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from sqlalchemy import delete, func, select

from app.database import async_session_factory
from app.models.asset import AssetCard, AssetFrame, AssetItem, AssetProduction, AssetSummary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [cards] %(levelname)s %(message)s")
logger = logging.getLogger("migrate_cards")


def _card_name(file_name: str | None) -> str:
    stem = (file_name or "").strip()
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem[:255] or "角色卡"


async def _counts(db) -> dict:
    n_items = (await db.execute(
        select(func.count()).select_from(AssetItem).where(AssetItem.media_kind == "image")
    )).scalar_one()
    n_cards = (await db.execute(select(func.count()).select_from(AssetCard))).scalar_one()
    return {"image_items": n_items, "cards_now": n_cards}


async def _refs(db, ids: list[uuid.UUID]) -> dict:
    if not ids:
        return {}
    out = {}
    out["summaries"] = (await db.execute(
        select(func.count()).select_from(AssetSummary).where(AssetSummary.asset_id.in_(ids))
    )).scalar_one()
    out["frames"] = (await db.execute(
        select(func.count()).select_from(AssetFrame).where(AssetFrame.asset_id.in_(ids))
    )).scalar_one()
    out["productions.asset_id"] = (await db.execute(
        select(func.count()).select_from(AssetProduction).where(AssetProduction.asset_id.in_(ids))
    )).scalar_one()
    out["productions.concat_asset_id"] = (await db.execute(
        select(func.count()).select_from(AssetProduction).where(AssetProduction.concat_asset_id.in_(ids))
    )).scalar_one()
    return out


async def main(execute: bool) -> int:
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(AssetItem).where(AssetItem.media_kind == "image").order_by(AssetItem.created_at)
        )).scalars().all()
        counts = await _counts(db)
        logger.info("图片素材行 %s 张，现有卡表 %s 行", counts["image_items"], counts["cards_now"])
        if not rows:
            logger.info("没有要迁的图片行，结束")
            return 0
        existing = {
            str(x) for x in (await db.execute(select(AssetCard.id))).scalars()
        }
        to_move = [r for r in rows if str(r.id) not in existing]
        skipped = len(rows) - len(to_move)
        if skipped:
            logger.info("%s 张已在卡表（上次迁过？），跳过", skipped)
        ids = [r.id for r in to_move]
        refs = await _refs(db, ids)
        bad = {k: v for k, v in refs.items() if v}
        for r in to_move:
            logger.info(
                "  迁 %s code=%s name=%s key=%s res=%s",
                r.id, r.code, (r.file_name or "")[:40], (r.file_key or "")[:48], r.resolution,
            )
        if bad:
            logger.error("图片行被这些表引用着（不该发生，先人工核再动，本脚本不删）：%s", bad)
            return 1
        no_key = [str(r.id) for r in to_move if not (r.file_key or "").strip()]
        if no_key:
            logger.error("%s 张图片行没落桶（file_key 空），迁过去也是取不到的卡，先处理它们：%s", len(no_key), no_key)
            return 1

        if not execute:
            logger.info("DRY-RUN：将迁 %s 张、删 %s 行。确认无误后加 --execute（先备份 DB）", len(to_move), len(to_move))
            return 0

        for r in to_move:
            db.add(AssetCard(
                id=r.id,
                code=r.code,
                owner_id=r.created_by,
                name=_card_name(r.file_name),
                file_name=r.file_name,
                file_key=r.file_key,
                bucket=r.bucket,
                file_size=r.file_size,
                resolution=r.resolution,
                note="11-25 批 W 自素材库迁入",
                created_at=r.created_at,
            ))
        await db.flush()
        after = (await db.execute(
            select(func.count()).select_from(AssetCard).where(AssetCard.id.in_(ids))
        )).scalar_one()
        if after != len(ids):
            await db.rollback()
            logger.error("写卡表后回读 %s/%s 不齐，已回滚（一行都没删）", after, len(ids))
            return 1
        n = (await db.execute(
            delete(AssetItem).where(AssetItem.id.in_(ids))
        )).rowcount
        await db.commit()
        # 挂卡生产单按真实口径数一遍（card_asset_ids JSON 数组 Python 侧比对，同删卡闸门）
        arrs = (await db.execute(select(AssetProduction.card_asset_ids))).scalars().all()
        held = sum(1 for arr in arrs if arr and any(str(x) in {str(i) for i in ids} for x in arr))
        logger.info("完成：迁 %s 张卡，删 %s 行图片素材；%s 张生产单挂着这些卡，id 没变照常解析",
                    len(ids), n, held)
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="图片素材行 → 角色卡库（dry-run 默认）")
    ap.add_argument("--execute", action="store_true", help="真迁（复制＋校验＋删旧行，同一事务）")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.execute)))
