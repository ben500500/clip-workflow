"""运维/性能优化服务（三期）。

- 数据归档：将超过 METRICS_ARCHIVE_DAYS 天的看板数据归档（video_metrics 等），保持主表轻量
- MinIO 生命周期：设置对象生命周期策略，未访问对象转低频存储/清理
- 临时文件清理：任务完成后清理本地临时目录
"""

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from app.config import settings
from app.database import async_session_factory
from app.models.models import AdMetric, DramaMetric, FunnelSnapshot, MiniProgramMetric, VideoMetric

logger = logging.getLogger(__name__)

# 需要按日期归档的表：表名 → ORM 模型 + 日期字段
ARCHIVE_TABLES = [
    (VideoMetric, "publish_date"),
    (MiniProgramMetric, "date"),
    (AdMetric, "date"),
    (DramaMetric, "date"),
    (FunnelSnapshot, "date"),
]


async def archive_old_metrics(days: int | None = None) -> dict:
    """归档超过 N 天的看板数据（默认 METRICS_ARCHIVE_DAYS=90 天）.

    说明：归档采用物理删除并记录统计信息。生产环境如需完整历史追溯，
    可扩展为将数据导出到归档表/冷存储后再删除。
    """
    days = days or settings.METRICS_ARCHIVE_DAYS
    cutoff = datetime.utcnow().date() - timedelta(days=days)

    result: dict = {"cutoff": str(cutoff), "deleted": {}, "errors": []}

    async with async_session_factory() as session:
        for model, date_col in ARCHIVE_TABLES:
            try:
                col = getattr(model, date_col)
                # 统计待删除数量
                count = (
                    await session.execute(
                        select(func.count(model.id)).where(
                            col.is_not(None), col < cutoff
                        )
                    )
                ).scalar() or 0
                if count:
                    await session.execute(
                        delete(model).where(col.is_not(None), col < cutoff)
                    )
                result["deleted"][model.__tablename__] = int(count)
            except Exception as e:
                result["errors"].append(f"{model.__tablename__}: {e}")
                logger.warning("Failed to archive %s: %s", model.__tablename__, e)
        await session.commit()
    return result


async def cleanup_temp_files(max_age_hours: int = 24) -> dict:
    """清理任务完成后遗留的本地临时文件（>24h）.

    覆盖目录：
    - /tmp/slice_outputs   （切片任务输出目录）
    - /tmp/source_videos   （下载的源视频）
    - /tmp/uploads         （分片上传临时目录，保留进行中文件）
    """
    result = {"cleaned": 0, "freed_mb": 0.0, "errors": []}
    dirs = [
        settings.UPLOAD_TEMP_DIR,
        "/tmp/slice_outputs",
        "/tmp/source_videos",
    ]
    cutoff = datetime.now().timestamp() - max_age_hours * 3600

    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for name in files:
                path = os.path.join(root, name)
                try:
                    st = os.stat(path)
                    if st.st_mtime < cutoff:
                        size = st.st_size
                        os.unlink(path)
                        result["cleaned"] += 1
                        result["freed_mb"] += size / (1024 * 1024)
                except FileNotFoundError:
                    pass
                except Exception as e:
                    result["errors"].append(str(e))
    result["freed_mb"] = round(result["freed_mb"], 2)
    return result


async def apply_minio_lifecycle() -> dict:
    """为 MinIO 设置生命周期策略（>90 天未访问对象转低频存储）.

    使用 MinIO 客户端的 set_bucket_lifecycle 设置规则。
    """
    result = {"buckets": [], "errors": []}
    days = settings.MINIO_LIFECYCLE_DAYS
    buckets = [
        settings.MINIO_BUCKET_RAW,
        settings.MINIO_BUCKET_SLICED,
        settings.MINIO_BUCKET_PREVIEWS,
        settings.MINIO_BUCKET_EXPORTS,
    ]
    try:
        from minio.commonconfig import Transition
        from minio.lifecycleconfig import LifecycleConfig, Rule, Filter, Expiration

        from app.services.minio_service import get_minio_client

        client = get_minio_client()

        for bucket in buckets:
            if not bucket:
                continue
            try:
                loop = asyncio.get_event_loop()
                # 检查 bucket 是否存在
                exists = await loop.run_in_executor(None, client.bucket_exists, bucket)
                if not exists:
                    continue
                # 生命周期规则：非当前版本对象在 days 天后转低频（GLACIER 需特定存储类，
                # 这里用 STANDARD_IA 低频存储降低存储成本）
                transition = Transition(
                    days=days,
                    storage_class="STANDARD_IA",
                )
                rule = Rule(
                    rule_id=f"lifecycle-{bucket}-{days}d",
                    status="Enabled",
                    filter=Filter(prefix=""),
                    transitions=[transition],
                )
                config = LifecycleConfig([rule])
                await loop.run_in_executor(
                    None,
                    lambda: client.set_bucket_lifecycle(bucket, config),
                )
                result["buckets"].append(bucket)
            except Exception as e:
                result["errors"].append(f"{bucket}: {e}")
                logger.warning("Failed to set lifecycle on %s: %s", bucket, e)
    except Exception as e:
        result["errors"].append(str(e))
    return result
