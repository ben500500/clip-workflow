import logging

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_timeout=30,
    pool_recycle=3600,
    connect_args={
        "server_settings": {
            "statement_timeout": "30000",  # 30s
        }
    },
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency that provides an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 对已存在的老表补充新增列（create_all 不会为已存在的表加列）
    await _apply_compat_migrations()


async def _apply_compat_migrations():
    """为已存在的表补充本次迭代新增的列，兼容老库升级。

    - slice_tasks.node_id: 记录实际执行任务的 Worker 节点
    - worker_nodes.enabled: 节点启停标记
    - video_metrics.tags: 视频标签（二期）
    """
    migrations = [
        ("slice_tasks", "node_id", "VARCHAR(100)"),
        ("slice_tasks", "watermark_config", "JSON"),
        ("worker_nodes", "enabled", "BOOLEAN DEFAULT TRUE"),
        ("worker_nodes", "cpu_percent", "INTEGER DEFAULT 50"),
        ("system_config", "description", "VARCHAR(500)"),
        ("platform_profiles", "description", "VARCHAR(500)"),
        ("autoclip_projects", "error_message", "TEXT"),
        # 二期：视频标签系统（JSON 数组）
        ("video_metrics", "tags", "JSON"),
    ]
    async with engine.begin() as conn:
        for table, column, ddl in migrations:
            try:
                exists = await conn.run_sync(
                    lambda sync_conn, _t=table, _c=column: sqlalchemy.inspect(sync_conn).has_column(_t, _c)
                )
            except Exception:
                exists = False
            if not exists:
                try:
                    await conn.execute(
                        sqlalchemy.text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {ddl}')
                    )
                    logger.info("Added column %s.%s", table, column)
                except Exception as e:
                    logger.warning("Failed to add column %s.%s: %s", table, column, e)


async def close_db():
    """Dispose the database engine."""
    await engine.dispose()