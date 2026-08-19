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
    await _ensure_autoclip_runs_table()
    await _backfill_data_scope()
    # wechat_download 独立包（并入形态）：确保其独立表存在（幂等）
    await _ensure_wechat_download_tables()
    # P1 防御：空闲事务超时自动回滚（防事务泄漏占锁 autoclip_runs）
    await _enforce_idle_in_transaction_timeout()


async def _enforce_idle_in_transaction_timeout():
    """固化 idle_in_transaction_session_timeout=60s（幂等、尽力而为）。

    根因（Issue #219）：autoclip 某接口在事务内 SELECT 后未 commit/rollback 就把
    连接归还连接池，连接以 idle in transaction 悬挂并持有 autoclip_runs 表级
    RowExclusiveLock，挡死 worker-selection 的 UPDATE。把该 GUC 固化到服务端，
    悬挂事务最迟 60s 被 PG 自动回滚，作为代码修复的防御层。
    ALTER SYSTEM + pg_reload_conf 不需要重启 PG 即可生效（需超级用户权限，
    docker-compose 默认 POSTGRES_USER 即超级用户）。
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sqlalchemy.text(
                    "ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s'"
                )
            )
            await conn.execute(sqlalchemy.text("SELECT pg_reload_conf()"))
    except Exception as e:
        # 权限不足或非 PG 环境时静默降级，不阻断服务启动
        logger.warning(
            "enforce idle_in_transaction_session_timeout 失败（降级）: %s", e
        )


async def _backfill_data_scope():
    """数据隔离：为存量用户回填 data_scope（按角色默认值，幂等）。

    - admin/material/publisher → all（可见全部素材）
    - operator → own（仅自己创建的素材）
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sqlalchemy.text("""
                    UPDATE users
                    SET data_scope = CASE
                        WHEN role IN ('admin', 'material', 'publisher') THEN 'all'
                        ELSE 'own'
                    END
                    WHERE data_scope IS NULL OR data_scope = ''
                """)
            )
            # 项目中 created_by 为空时回填（旧库升级：按角色默认归属不可知，统一置空即可，
            # 运营专员可见范围依赖其创建的素材；这里不猜测归属）
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to backfill data_scope: %s", e)


async def _ensure_autoclip_runs_table():
    """确保 autoclip_runs 表存在（旧库升级时 create_all 不会新建该表，需要显式建）。"""
    from sqlalchemy import inspect as sa_inspect

    try:
        async with engine.begin() as conn:
            exists = await conn.run_sync(
                lambda sync_conn: sa_inspect(sync_conn).has_table("autoclip_runs")
            )
        if exists:
            return
        # 表不存在时手动创建（与 ORM 模型字段一致）
        async with engine.begin() as conn:
            await conn.execute(
                sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS autoclip_runs (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                        autoclip_project_id VARCHAR(100),
                        celery_task_id VARCHAR(100),
                        status VARCHAR(50) DEFAULT 'pending',
                        progress DOUBLE PRECISION DEFAULT 0,
                        message TEXT,
                        error_message TEXT,
                        config JSON,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                """)
            )
            try:
                await conn.execute(
                    sqlalchemy.text(
                        "CREATE INDEX IF NOT EXISTS ix_autoclip_runs_episode_id ON autoclip_runs(episode_id)"
                    )
                )
            except Exception:
                pass
            logger.info("Created autoclip_runs table")
    except Exception as e:
        logger.warning("Failed to ensure autoclip_runs table: %s", e)


async def _apply_compat_migrations():
    """为已存在的表补充本次迭代新增的列，兼容老库升级。

    - slice_tasks.node_id: 记录实际执行任务的 Worker 节点
    - worker_nodes.enabled: 节点启停标记
    - video_metrics.tags: 视频标签（二期）
    """
    migrations = [
        ("slice_tasks", "node_id", "VARCHAR(100)"),
        ("slice_tasks", "source_bucket", "VARCHAR(50)"),
        ("slice_tasks", "source_file_key", "VARCHAR(500)"),
        ("slice_tasks", "watermark_config", "JSON"),
        ("slice_tasks", "vert2horiz_config", "JSON"),
        ("worker_nodes", "enabled", "BOOLEAN DEFAULT TRUE"),
        ("worker_nodes", "cpu_percent", "INTEGER DEFAULT 50"),
        ("system_config", "description", "VARCHAR(500)"),
        ("platform_profiles", "description", "VARCHAR(500)"),
        ("autoclip_projects", "error_message", "TEXT"),
        # 二期：视频标签系统（JSON 数组）
        ("video_metrics", "tags", "JSON"),
        # 二期：JWT 双 Token（会话表新增 refresh_token_hash / access_token_jti）
        ("user_sessions", "refresh_token_hash", "VARCHAR(255)"),
        ("user_sessions", "access_token_jti", "VARCHAR(64)"),
        # 二期方案：数据隔离
        # - users.data_scope：用户数据可见范围（all=全部素材，own=仅自己创建）
        # - projects.created_by：项目创建人（运营专员默认仅可见自己创建的素材）
        ("users", "data_scope", "VARCHAR(20) DEFAULT 'own'"),
        ("projects", "created_by", "UUID"),
        # 短片制作：去水印任务关联来源提示词记录（提示词 → 去水印 → 发布）
        ("watermark_videos", "prompt_record_id", "UUID"),
        # 短片制作：一键豆包生成
        # - users.doubao_account_type：用户默认豆包账户类型（free=免费 / pro=包月会员）
        # - shortdrama_prompts.doubao_*：豆包生成任务状态 / 登录二维码 / 改写闭环等
        ("users", "doubao_account_type", "VARCHAR(20) DEFAULT 'free'"),
        ("shortdrama_prompts", "doubao_status", "VARCHAR(50)"),
        ("shortdrama_prompts", "doubao_account_type", "VARCHAR(20)"),
        ("shortdrama_prompts", "doubao_qrcode", "TEXT"),
        ("shortdrama_prompts", "doubao_screenshot", "TEXT"),
        ("shortdrama_prompts", "doubao_task_id", "VARCHAR(100)"),
        ("shortdrama_prompts", "doubao_message", "TEXT"),
        ("shortdrama_prompts", "doubao_progress", "INTEGER DEFAULT 0"),
        ("shortdrama_prompts", "doubao_error_message", "TEXT"),
        ("shortdrama_prompts", "doubao_approved_prompt", "TEXT"),
        ("shortdrama_prompts", "doubao_rewrite_history", "JSON"),
        ("shortdrama_prompts", "doubao_confirm_token", "VARCHAR(64)"),
        # 短片制作：Seedance 官方 API 直连出片（与豆包 RPA 并行、独立通道）
        # - seedance_*：官方 API 任务状态 / 方舟 task_id / 进度消息 / 失败原因 / 分辨率
        # - gen_channel：成片来源通道（doubao_rpa / seedance_api），便于追溯
        ("shortdrama_prompts", "seedance_status", "VARCHAR(50)"),
        ("shortdrama_prompts", "seedance_task_id", "VARCHAR(100)"),
        ("shortdrama_prompts", "seedance_message", "TEXT"),
        ("shortdrama_prompts", "seedance_error_message", "TEXT"),
        ("shortdrama_prompts", "seedance_resolution", "VARCHAR(20)"),
        ("shortdrama_prompts", "gen_channel", "VARCHAR(20)"),
        # 短片制作：提示词生成默认时长（用户选择时长后即作为当前登录用户的默认值）
        ("users", "prompt_default_duration", "INTEGER"),
        # 一期：视频号账号矩阵 + 短片分析
        # - publish_tasks：账号矩阵 / 小程序库 / 短片来源关联
        # - video_metrics.platform：平台显式标记（视频号/抖音/快手）
        # - publish_materials.prompt_record_id：发布素材来源提示词记录
        ("publish_tasks", "video_account_id", "UUID"),
        ("publish_tasks", "mini_program_id", "UUID"),
        ("publish_tasks", "prompt_record_id", "UUID"),
        ("publish_tasks", "material_id", "UUID"),
        ("video_metrics", "platform", "VARCHAR(50)"),
        ("publish_materials", "prompt_record_id", "UUID"),
        # 视频号素材导入（wechat_download）：episodes 最小粘合字段 source_url
        ("episodes", "source_url", "VARCHAR(2000)"),
        # 多视频号素材去重（圆桌定稿）：SliceOutput 变体组 + Publication 变体回写
        ("slice_outputs", "variant_group_id", "UUID"),
        ("publications", "variant_id", "UUID"),
        ("slice_tasks", "variant_count", "INTEGER"),
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

async def _ensure_wechat_download_tables():
    """确保 wechat_download 独立包的表存在（并入形态，幂等）。

    wechat_download 使用独立 Base（wechat_download.base.WechatDownloadBase），
    不在主系统 Base.metadata 中，create_all 不会自动建表；此处显式建表，
    兼容未跑 alembic 迁移的环境。生产建议以 alembic 迁移（0029）为准。
    """
    from wechat_download.base import WechatDownloadBase
    try:
        async with engine.begin() as conn:
            await conn.run_sync(WechatDownloadBase.metadata.create_all)
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to ensure wechat_download tables: %s", e)
