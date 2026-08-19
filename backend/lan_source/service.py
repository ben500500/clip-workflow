"""lan_source 业务编排服务（并入形态：复用主系统 DB/MinIO/剧目/剧集）。

核心职责：
1. 任务编排：创建导入任务 → 发现剧集直链 → 并发下载 → MinIO 入库 →
   落剧目(dramas) + 切片项目(projects/episodes)。
2. 任务状态/进度管理（供 API 与前端轮询展示）。

可剥离性：本服务仅依赖主系统「通用服务接口」（async_session / minio_service /
Drama / Project / Episode），并通过 db 注入的 AsyncSession 读写本包独立表；
剥离时替换 DB/MinIO 依赖即可。
"""

import json
import logging
import os
import tempfile
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.drama import Drama, gen_drama_code
from app.models.models import Episode, Project

from lan_source.client import CdnEpisode, LanSourceError, get_client
from lan_source.models import LanSourceImport

logger = logging.getLogger(__name__)

# 任务状态机
ST_PENDING = "pending"
ST_DISCOVERING = "discovering"
ST_DOWNLOADING = "downloading"
ST_IMPORTING = "importing"
ST_COMPLETED = "completed"
ST_FAILED = "failed"


class LanSourceImportError(Exception):
    """导入任务失败（不可重试：源不可达、发现失败、入库失败等）。"""


class RetryableLanSourceError(LanSourceImportError):
    """可重试的导入失败（下载中断 / 网络抖动 / 限流等瞬态错误）。

    Celery 任务捕获后调用 self.retry()（配合断点续传）。
    """


# ───────────────────────────────
# 任务创建与状态
# ───────────────────────────────

async def create_import_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    drama_name: str,
    project_id: Optional[uuid.UUID] = None,
    total_episodes: Optional[int] = None,
) -> LanSourceImport:
    """创建局域网剧集导入任务。"""
    task = LanSourceImport(
        created_by=created_by,
        drama_name=drama_name.strip(),
        project_id=project_id,
        total_episodes=total_episodes,
        status=ST_PENDING,
        progress=0.0,
        episode_items=[],
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get_import_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[LanSourceImport]:
    result = await db.execute(select(LanSourceImport).where(LanSourceImport.id == task_id))
    return result.scalar_one_or_none()


def serialize_task(t: LanSourceImport) -> dict:
    return {
        "id": str(t.id),
        "created_by": str(t.created_by) if t.created_by else None,
        "drama_name": t.drama_name,
        "drama_id": str(t.drama_id) if t.drama_id else None,
        "project_id": str(t.project_id) if t.project_id else None,
        "status": t.status,
        "progress": t.progress,
        "message": t.message,
        "total_episodes": t.total_episodes,
        "imported_count": t.imported_count,
        "failed_count": t.failed_count,
        "episode_items": t.episode_items or [],
        "error_message": t.error_message,
        "celery_task_id": t.celery_task_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


# ───────────────────────────────
# 下载编排（供 Celery 任务调用）
# ───────────────────────────────

async def run_import_pipeline(task_id: uuid.UUID) -> dict:
    """执行完整导入流水线（发现直链 → 下载 → MinIO 入库 → 建剧目/项目/剧集）。

    由 Celery `lan_source.import_episodes` 调用；用独立 session 读写本包表，
    复用主系统 minio_service / Drama / Project / Episode 完成入库。
    """
    from app.database import async_session_factory

    async with async_session_factory() as db:
        task = await get_import_task(db, task_id)
        if task is None:
            return {"ok": False, "error": f"task {task_id} not found"}

        try:
            await _set_status(db, task, ST_DISCOVERING, 5, "正在发现局域网剧集直链...")
            episodes = await _discover_episodes(task)
            if not episodes:
                raise LanSourceImportError(f"未从局域网源获取到《{task.drama_name}》的剧集直链")

            # 受 total_episodes 限制（可选）
            if task.total_episodes and task.total_episodes > 0:
                episodes = episodes[: task.total_episodes]

            # 预置每集明细
            task.episode_items = [
                {"episode": e.episode, "title": e.title, "url": e.url, "status": "pending"}
                for e in episodes
            ]
            await _set_status(db, task, ST_DOWNLOADING, 20, f"共发现 {len(episodes)} 集，开始下载...")

            # 并发受限下载到本地临时目录
            local_dir = _temp_dir(task.id)
            url_paths = [(e.url, os.path.join(local_dir, f"{idx:03d}.mp4")) for idx, e in enumerate(episodes)]
            ok_flags = await _download_all(url_paths)

            for idx, ok in enumerate(ok_flags):
                task.episode_items[idx]["status"] = "downloaded" if ok else "failed"
                if not ok:
                    task.episode_items[idx]["error"] = "下载失败"
            await _set_status(db, task, ST_IMPORTING, 65, "下载完成，正在入库 MinIO 并建剧集...")

            # 入库：建剧目（幂等）+ 切片项目（幂等）+ 剧集（MinIO 上传 + Episode 记录）
            project_id = await _ensure_project(db, task)
            task.project_id = project_id
            drama_id = await _ensure_drama(db, task)

            imported = 0
            failed = 0
            for idx, (ep, ok) in enumerate(zip(episodes, ok_flags)):
                if not ok:
                    failed += 1
                    task.episode_items[idx]["status"] = "failed"
                    task.episode_items[idx]["error"] = task.episode_items[idx].get("error") or "下载失败"
                    continue
                local_path = url_paths[idx][1]
                try:
                    episode_id = await _import_episode(
                        db, task, project_id, drama_id, ep, local_path, idx
                    )
                    task.episode_items[idx]["status"] = "completed"
                    task.episode_items[idx]["episode_id"] = str(episode_id)
                    imported += 1
                except Exception as e:
                    failed += 1
                    task.episode_items[idx]["status"] = "failed"
                    task.episode_items[idx]["error"] = str(e)
                    logger.warning("lan_source import episode %s failed: %s", ep.episode, e)

            task.imported_count = imported
            task.failed_count = failed
            task.drama_id = drama_id
            task.project_id = project_id

            if imported == 0:
                raise LanSourceImportError(f"全部 {failed} 集导入失败，请检查局域网源与 MinIO")

            await _set_status(db, task, ST_COMPLETED, 100,
                              f"导入完成：成功 {imported} 集，失败 {failed} 集")
            await db.commit()
            return {"ok": True, "task_id": str(task.id), "imported": imported,
                    "drama_id": str(drama_id), "project_id": str(project_id)}

        except RetryableLanSourceError as e:
            logger.warning("lan_source import retryable failure for task %s: %s", task_id, e)
            await _fail(db, task, str(e))
            try:
                await db.commit()
            except Exception:
                pass
            raise
        except Exception as e:
            logger.exception("lan_source import pipeline failed for task %s", task_id)
            await _fail(db, task, str(e))
            try:
                await db.commit()
            except Exception:
                pass
            return {"ok": False, "error": str(e)}
        finally:
            _cleanup_temp(task.id)


async def _discover_episodes(task: LanSourceImport) -> list[CdnEpisode]:
    """发现剧集直链（可重试的网络瞬态由 Celery 重试处理）。"""
    try:
        return await get_client().fetch_episodes(task.drama_name)
    except LanSourceError as e:
        raise LanSourceImportError(str(e)) from e
    except Exception as e:
        raise RetryableLanSourceError(f"发现剧集直链失败(可重试): {e}") from e


async def _download_all(url_paths: list[tuple[str, str]]) -> list[bool]:
    """并发受限下载全部直链；单项失败记录，不阻塞整剧。"""
    from lan_source.downloader import run_bounded_downloads
    return await run_bounded_downloads(url_paths)


async def _ensure_project(db: AsyncSession, task: LanSourceImport) -> uuid.UUID:
    """确保切片项目存在（未指定 project_id 时按默认项目名创建/复用）。"""
    if task.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == task.project_id))
        if result.scalar_one_or_none() is not None:
            return task.project_id
    default_name = settings.LAN_SOURCE_DEFAULT_PROJECT
    result = await db.execute(select(Project).where(Project.name == default_name))
    proj = result.scalar_one_or_none()
    if proj is None:
        proj = Project(
            name=default_name,
            description="局域网获取剧集导入默认切片项目",
            status="draft",
            created_by=task.created_by,
        )
        db.add(proj)
        await db.flush()
        await db.refresh(proj)
    return proj.id


async def _ensure_drama(db: AsyncSession, task: LanSourceImport) -> uuid.UUID:
    """确保剧目存在（按 name 幂等：存在即复用，否则创建）。"""
    result = await db.execute(select(Drama).where(Drama.name == task.drama_name))
    drama = result.scalar_one_or_none()
    if drama is not None:
        return drama.id
    # 唯一性冲突（并发同剧名导入）兜底重抽 code
    for _attempt in range(3):
        code = gen_drama_code()
        exists = await db.execute(select(Drama).where(Drama.code == code))
        if exists.scalar_one_or_none() is not None:
            continue
        drama = Drama(
            code=code,
            name=task.drama_name,
            listing_status="待上架",
            created_by=task.created_by,
        )
        db.add(drama)
        await db.flush()
        await db.refresh(drama)
        return drama.id
    raise LanSourceImportError("生成剧目唯一 ID 失败，请重试")


async def _import_episode(
    db: AsyncSession,
    task: LanSourceImport,
    project_id: uuid.UUID,
    drama_id: uuid.UUID,
    ep: CdnEpisode,
    local_path: str,
    idx: int,
) -> uuid.UUID:
    """单集入库：MinIO 上传 → 创建 Episode（含 source_url + drama_id 粘合）。"""
    from app.services.minio_service import upload_file_from_path

    file_key = f"{settings.MINIO_BUCKET_RAW}/{project_id}/{task.id}/{idx:03d}.mp4"
    ok = await upload_file_from_path(settings.MINIO_BUCKET_RAW, file_key, local_path, "video/mp4")
    if not ok:
        raise LanSourceImportError("MinIO 入库失败")

    size = os.path.getsize(local_path) if os.path.isfile(local_path) else None
    title = f"{task.drama_name} 第{ep.episode or idx + 1}集"
    episode = Episode(
        project_id=project_id,
        title=title,
        episode_no=ep.episode or (idx + 1),
        source_file_key=file_key,
        source_url=ep.url,
        drama_id=drama_id,
        file_size=size,
        status="uploaded",
    )
    db.add(episode)
    await db.flush()
    await db.refresh(episode)
    return episode.id


async def _set_status(db, task: LanSourceImport, status, progress, message):
    task.status = status
    task.progress = progress
    task.message = message
    await db.flush()
    await _publish_progress(task)


async def _fail(db, task: LanSourceImport, error):
    task.status = ST_FAILED
    task.error_message = error
    await db.flush()
    await _publish_progress(task)


# 进度发布（跨进程 Redis pub/sub，供前端 WebSocket 订阅）
_PROGRESS_CHANNEL = "lan_source:progress"


def _progress_payload(task: LanSourceImport) -> dict:
    return {
        "task_id": str(task.id),
        "status": task.status,
        "progress": task.progress,
        "message": task.message or "",
        "error_message": task.error_message or "",
        "imported_count": task.imported_count,
        "failed_count": task.failed_count,
    }


async def _publish_progress(task: LanSourceImport) -> None:
    """把任务进度发布到 Redis 频道（供主系统 WebSocket 订阅转发）。"""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.publish(_PROGRESS_CHANNEL, json.dumps(_progress_payload(task)))
        await r.aclose()
    except Exception as e:  # 进度发布失败不影响主流程
        logger.warning("publish lan_source progress failed: %s", e)


def _temp_dir(task_id) -> str:
    d = os.path.join(tempfile.gettempdir(), "lan_source")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, str(task_id))


def _cleanup_temp(task_id) -> None:
    d = os.path.join(tempfile.gettempdir(), "lan_source", str(task_id))
    if os.path.isdir(d):
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
