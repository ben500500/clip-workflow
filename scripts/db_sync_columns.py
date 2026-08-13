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

用法：
  docker compose cp scripts/db_sync_columns.py backend:/app/db_sync_columns.py
  docker compose exec backend python /app/db_sync_columns.py
"""
import asyncio
import os
import asyncpg

from app.models.models import Base
from sqlalchemy.dialects import postgresql


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 未设置")
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    added = []
    skipped_tables = []
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
    finally:
        await conn.close()

    print(f"ADDED_COUNT={len(added)}")
    for a in added:
        print(f"  + {a}")
    if skipped_tables:
        print(f"SKIP_NEW_TABLE_COUNT={len(skipped_tables)}")
        for t in skipped_tables:
            print(f"  - {t} (由 alembic 建表)")


if __name__ == "__main__":
    asyncio.run(main())
