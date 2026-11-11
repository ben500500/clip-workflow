#!/usr/bin/env python3
"""
db_sync_columns.py — 部署后补齐 ORM 模型与数据库实际表的列差异

背景（踩坑）：
  cnb 更新给 SQLAlchemy 模型加了新列（如 slice_tasks.subtitle_mask_config），
  但 alembic 迁移链因旧迁移创建 user_sessions 表时 DuplicateTableError 优雅跳过，
  导致后续新增列的迁移也没执行 → 数据库缺列 → 相关接口 500。

本脚本在 backend 容器内运行（复用其 app 包与 DATABASE_URL 环境变量）：
  - 遍历 Base.metadata 所有表，对比 information_schema 实际列
  - 对缺失列按 SQLAlchemy 方言编译出的类型 ALTER TABLE ADD COLUMN（IF NOT EXISTS，幂等）
  - 新列统一不加 NOT NULL 约束，避免历史空数据导致 ALTER 失败
  - 整表缺失时跳过并打印 SKIP_NEW_TABLE（由 alembic 负责建新表）
  - （2026-11-11 七席评审）对缺失的**唯一索引**幂等回填：部署链路只 stamp 不跑
    upgrade，迁移里的索引现网执行不到，靠这里补（建不上打 INDEX_FAIL 点名）

用法：
  docker compose cp scripts/db_sync_columns.py backend:/app/db_sync_columns.py
  docker compose exec backend python /app/db_sync_columns.py
"""
import asyncio
import os
import asyncpg

from app.database import Base
import app.models.models  # noqa: F401  触发全部 ORM 模型注册到 Base.metadata
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 未设置")
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    added = []
    skipped_tables = []
    indexes_filled = []
    index_errors = []
    try:
        for tname, table in sorted(Base.metadata.tables.items()):
            exists = await conn.fetchval("SELECT to_regclass($1)", tname)
            if not exists:
                skipped_tables.append(tname)
                continue
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name=$1",
                tname,
            )
            cols = {r["column_name"] for r in rows}
            for col in table.columns:
                if col.name in cols:
                    continue
                ctype = col.type.compile(dialect=postgresql.dialect())
                ddl = (
                    f'ALTER TABLE {tname} '
                    f'ADD COLUMN IF NOT EXISTS {col.name} {ctype}'
                )
                await conn.execute(ddl)
                added.append(f"{tname}.{col.name} ({ctype})")

        # ── 唯一索引回填（2026-11-11 七席评审，业务 P0）──────────────────────────
        # 部署链路只 `alembic stamp head`、不跑 upgrade（见 compose alembic-migrate
        # 命令注释与 database.py:321），迁移里建的索引在现网**永远执行不到**。本脚本
        # 却是每次部署都跑的——所以「一钩一号」的 DB 底线（hook_code 部分唯一索引）
        # 从 Base.metadata 在这里幂等回填：fresh 库 create_all 已带，存量表靠这里补。
        # 只补 unique 索引：普通索引漏了只慢不错，唯一索引漏了是闸门失效。
        # 建不上（存量重复数据撞约束）→ 打 INDEX_FAIL 点名且放在最后几行（deploy 只
        # tail -8），不回滚已补的列——迁移失败留给人工，别让列补齐陪着一起挂。
        for tname, table in sorted(Base.metadata.tables.items()):
            if not await conn.fetchval("SELECT to_regclass($1)", tname):
                continue
            for idx in sorted(table.indexes, key=lambda i: i.name or ""):
                if not idx.unique or not idx.name:
                    continue
                try:
                    if await conn.fetchval(
                        "SELECT 1 FROM pg_indexes WHERE indexname=$1", idx.name
                    ):
                        continue  # 已存在（名称即模型声明名）
                    ddl = str(CreateIndex(idx).compile(dialect=postgresql.dialect()))
                    await conn.execute(ddl)
                    indexes_filled.append(f"{idx.name} ({tname})")
                except Exception as exc:  # noqa: BLE001 —— 撞重复数据/权限，点名不中断
                    index_errors.append(f"{idx.name} ({tname}): {type(exc).__name__}: {exc}")
    finally:
        await conn.close()

    print(f"ADDED_COUNT={len(added)}")
    for a in added:
        print(f"  + {a}")
    if skipped_tables:
        print(f"SKIP_NEW_TABLE_COUNT={len(skipped_tables)}")
        for t in skipped_tables:
            print(f"  - {t} (由 alembic 建表)")
    print(f"INDEX_BACKFILL_COUNT={len(indexes_filled)}")
    for i in indexes_filled:
        print(f"  + index {i}")
    # INDEX_FAIL 必须是最后几行：deploy 只展示 tail -8，闸门失败不能被截掉
    for e in index_errors:
        print(f"INDEX_FAIL={e}")
    if index_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
