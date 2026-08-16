"""wechat_download 业务编排服务（并入形态：复用主系统登录态/入库/MinIO）。

核心职责：
1. 任务编排：创建任务 → 多 provider 解析（兜底链）→ 拉流入库。
2. 任务状态/进度管理（供 API 与 WebSocket 查询）。

可剥离性：本服务仅依赖主系统「通用服务接口」（async_session / minio_service /
upload_service），并通过 db 注入的 AsyncSession 读写本包独立表；剥离时替换
DB/MinIO 依赖即可。
"""

import asyncio
import json
import logging
import os
import tempfile
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from wechat_download.models import (
    WechatDownloadTask,
    WechatParseRecord,
)
from wechat_download.yuanbao_client import (
    ParseResult,
)
from wechat_download.provider_registry import (
    ProviderParseError,
    build_providers,
)
from wechat_download.downloader import DownloadError, get_downloader

logger = logging.getLogger(__name__)

# 任务状态机
ST_PENDING = "pending"
ST_PARSING = "parsing"
ST_DOWNLOADING = "downloading"
ST_UPLOADING = "uploading"
ST_COMPLETED = "completed"
ST_FAILED = "failed"

class ImportError_(Exception):
    """导入任务失败。"""


# ───────────────────────────────
# 任务创建与状态
# ───────────────────────────────

async def create_import_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    source_url: str,
    source_type: str = "self_owned",
    project_id: Optional[uuid.UUID] = None,
    authorize_note: Optional[str] = None,
) -> WechatDownloadTask:
    """创建下载任务（授权校验已移除：任意视频号链接均可导入）。"""
    task = WechatDownloadTask(
        created_by=created_by,
        source_url=source_url,
        status=ST_PENDING,
        progress=0.0,
        source_type=source_type,
        source_authorize=authorize_note or "",
        project_id=project_id,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[WechatDownloadTask]:
    result = await db.execute(select(WechatDownloadTask).where(WechatDownloadTask.id == task_id))
    return result.scalar_one_or_none()


async def create_import_tasks_batch(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    source_urls: list[str],
    source_type: str = "self_owned",
    project_id: Optional[uuid.UUID] = None,
    authorize_note: Optional[str] = None,
) -> tuple[list[WechatDownloadTask], list[str]]:
    """批量创建下载任务（P1：批量链接）。

    授权校验已移除：任意视频号链接均可批量导入。
    返回 (创建成功的任务列表, 失败项消息列表)。失败项（如重复/非法 URL）单独收集，
    不阻塞整批导入。
    """
    if not source_urls:
        raise ImportError_("批量导入至少需要一个分享链接")

    tasks: list[WechatDownloadTask] = []
    errors: list[str] = []
    seen: set[str] = set()
    for url in source_urls:
        url = (url or "").strip()
        if not url:
            errors.append("存在空链接，已跳过")
            continue
        if url in seen:
            errors.append(f"重复链接已跳过: {url[:40]}")
            continue
        seen.add(url)
        task = WechatDownloadTask(
            created_by=created_by,
            source_url=url,
            status=ST_PENDING,
            progress=0.0,
            source_type=source_type,
            source_authorize=authorize_note or "",
            project_id=project_id,
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        tasks.append(task)

    if not tasks:
        raise ImportError_("批量导入没有可用的有效链接")
    return tasks, errors


def _serialize_task(t: WechatDownloadTask) -> dict:
    return {
        "id": str(t.id),
        "created_by": str(t.created_by) if t.created_by else None,
        "source_url": t.source_url,
        "status": t.status,
        "progress": t.progress,
        "message": t.message,
        "video_meta": t.video_meta,
        "source_type": t.source_type,
        "source_authorize": t.source_authorize,
        "auth_id": str(t.auth_id) if t.auth_id else None,
        "file_key": t.file_key,
        "episode_id": str(t.episode_id) if t.episode_id else None,
        "project_id": str(t.project_id) if t.project_id else None,
        "error_message": t.error_message,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


# ───────────────────────────────
# 下载编排（供 Celery 任务调用）
# ───────────────────────────────

async def run_download_pipeline(task_id: uuid.UUID) -> dict:
    """执行完整下载流水线（解析 → 拉流 → 入库）。

    由 Celery `task_wechat_dl_download` 调用；用独立 session 读写本包表，
    复用主系统 minio_service / Project / Episode 完成入库。
    """
    from app.database import async_session_factory
    from app.services.minio_service import upload_file_from_path

    async with async_session_factory() as db:
        task = await get_task(db, task_id)
        if task is None:
            return {"ok": False, "error": f"task {task_id} not found"}

        try:
            await _set_status(db, task, ST_PARSING, 5, "正在解析视频链接...")
            parsed = await _parse_with_fallback(db, task)
            if not parsed.success:
                raise ImportError_(parsed.error or "解析失败")

            await _set_status(db, task, ST_DOWNLOADING, 35, "正在拉流下载视频...")
            local_path = _temp_path(task.id)
            try:
                total = await get_downloader().download_to_file(parsed.play_url, local_path)
            except DownloadError as e:
                raise ImportError_(f"拉流下载失败: {e}")

            await _set_status(db, task, ST_UPLOADING, 80, "正在入库 MinIO...")
            project_id = await _ensure_project(db, task)
            file_key = f"{settings.MINIO_BUCKET_RAW}/{project_id}/{task.id}.mp4"
            ok = await upload_file_from_path(
                settings.MINIO_BUCKET_RAW, file_key, local_path, "video/mp4"
            )
            if not ok:
                raise ImportError_("MinIO 入库失败")

            episode_id = await _create_episode(
                db, task, project_id, file_key, total, parsed
            )
            task.file_key = file_key
            task.episode_id = episode_id
            task.project_id = project_id
            task.video_meta = parsed.meta
            await _set_status(db, task, ST_COMPLETED, 100, "下载并入库完成")
            await db.commit()
            return {"ok": True, "task_id": str(task.id), "episode_id": str(episode_id)}

        except Exception as e:
            logger.exception("download pipeline failed for task %s", task_id)
            await _fail(db, task, str(e))
            try:
                await db.commit()
            except Exception:
                pass
            return {"ok": False, "error": str(e)}
        finally:
            # 断点续传（P1）：仅成功/彻底失败后清理临时文件；
            # 若因可重试的下载中断失败，保留残留文件供 Celery 重试续传。
            keep_for_resume = task.status in (ST_FAILED,)
            if keep_for_resume and _temp_path(task.id) and os.path.exists(_temp_path(task.id)):
                # 标记为续传残留：不删除，下次任务命中 Range 续传
                logger.info("保留临时文件供断点续传: %s", _temp_path(task.id))
            elif os.path.exists(_temp_path(task.id)):
                try:
                    os.remove(_temp_path(task.id))
                except OSError:
                    pass


async def _parse_with_fallback(db, task: WechatDownloadTask):
    """多 provider 兜底链解析（P1 增加解析结果缓存）。

    先查本任务 source_url 在 wechat_parse_records 中是否已有成功解析记录
    （命中直接复用 play_url，避免重复调用易变/限流的解析接口，评审 R1/R2）。

    provider 顺序由 `WECHAT_DL_PROVIDERS`（默认 yuanbao,preview）驱动；逐个尝试，
    每个 provider 的成败都写一条 WechatParseRecord（channel=provider 逻辑名），
    任一个成功即返回，全部失败聚合各 provider 错误后抛 ImportError_。
    """
    # P1 解析缓存：同 URL 已有成功解析则直接复用
    cached = await _hit_parse_cache(db, task.source_url)
    if cached is not None:
        logger.info("parse cache hit for %s (channel=%s)", task.source_url, cached.channel)
        return cached

    errors: list[str] = []
    providers = build_providers()
    if not providers:
        raise ImportError_("解析失败：未配置任何可用的解析服务（WECHAT_DL_PROVIDERS 为空）")
    for idx, client in enumerate(providers):
        try:
            await _set_status(
                db, task, ST_PARSING, min(30, 10 + idx * 5),
                f"正在尝试解析服务: {client.channel}",
            )
            result = await client.parse(task.source_url, db=db)
            rec = WechatParseRecord(
                task_id=task.id, channel=client.channel, source_url=task.source_url,
                status="success" if result.success else "failed",
                play_url=result.play_url, result_meta=result.meta,
                raw=result.raw[:4000] if result.raw else None,
                error_message=result.error,
            )
            db.add(rec)
            await db.flush()
            if result.success:
                logger.info("parse success via provider %s for task %s", client.channel, task.id)
                return result
        except ProviderParseError as e:
            errors.append(str(e))
            logger.warning("provider %s parse failed for %s: %s", client.channel, task.id, e)
            rec = WechatParseRecord(
                task_id=task.id, channel=client.channel, source_url=task.source_url,
                status="failed", error_message=str(e),
            )
            db.add(rec)
            await db.flush()
        finally:
            try:
                await client.close()
            except Exception:
                pass

    raise ImportError_(f"解析失败（全部解析服务均不可用）: {' | '.join(errors)}")


async def _hit_parse_cache(db: AsyncSession, source_url: str) -> Optional[ParseResult]:
    """命中解析缓存：返回同 URL 最近一次成功解析结果（play_url 有效），否则 None。

    仅取 status=success 且 play_url 非空的记录，按时间倒序取最新一条。
    避免对易变/限流的元宝接口重复调用；拉流地址 TTL 短时可由下载器
    兜底（断点续传/重试），此处缓存只优化重复 URL 场景。
    """
    result = await db.execute(
        select(WechatParseRecord)
        .where(
            WechatParseRecord.source_url == source_url,
            WechatParseRecord.status == "success",
            WechatParseRecord.play_url.isnot(None),
        )
        .order_by(WechatParseRecord.created_at.desc())
        .limit(1)
    )
    rec = result.scalar_one_or_none()
    if rec is None or not rec.play_url:
        return None
    return ParseResult(
        success=True,
        channel="cache",
        play_url=rec.play_url,
        title=(rec.result_meta or {}).get("title") if rec.result_meta else None,
        cover_url=(rec.result_meta or {}).get("cover") if rec.result_meta else None,
        duration=(rec.result_meta or {}).get("duration") if rec.result_meta else None,
        meta=rec.result_meta or {},
        error=None,
    )


async def _set_status(db, task, status, progress, message):
    task.status = status
    task.progress = progress
    task.message = message
    await db.flush()
    await _publish_progress(task)


async def _fail(db, task, error):
    task.status = ST_FAILED
    task.error_message = error
    await db.flush()
    await _publish_progress(task)


# 进度发布（WebSocket 实时回传，跨进程 Redis pub/sub）
_PROGRESS_CHANNEL = "wechat_dl:progress"


def _progress_payload(task) -> dict:
    return {
        "task_id": str(task.id),
        "status": task.status,
        "progress": task.progress,
        "message": task.message or "",
        "error_message": task.error_message or "",
    }


async def _publish_progress(task) -> None:
    """把任务进度发布到 Redis 频道（供主系统 WebSocket 订阅转发）。"""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.publish(_PROGRESS_CHANNEL, json.dumps(_progress_payload(task)))
        await r.aclose()
    except Exception as e:  # 进度发布失败不影响主流程
        logger.warning("publish wechat_dl progress failed: %s", e)


def _temp_path(task_id) -> str:
    d = os.path.join(tempfile.gettempdir(), "wechat_dl")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{task_id}.mp4")


async def _ensure_project(db, task) -> uuid.UUID:
    """确保任务归属项目存在（未指定 project_id 时复用默认项目，按需创建）。"""
    from app.models.models import Project
    if task.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == task.project_id))
        if result.scalar_one_or_none() is not None:
            return task.project_id
    # 查找/创建默认项目（按创建人隔离）
    default_name = settings.WECHAT_DL_DEFAULT_PROJECT
    result = await db.execute(
        select(Project).where(Project.name == default_name)
    )
    proj = result.scalar_one_or_none()
    if proj is None:
        proj = Project(name=default_name, description="视频号素材导入默认项目", status="draft")
        db.add(proj)
        await db.flush()
        await db.refresh(proj)
    return proj.id


async def _create_episode(db, task, project_id, file_key, size, parsed) -> uuid.UUID:
    """入库：创建 Episode 记录（含 source_url 粘合字段），返回 episode_id。"""
    from app.models.models import Episode
    ep = Episode(
        project_id=project_id,
        title=parsed.title or "视频号导入素材",
        source_file_key=file_key,
        source_url=task.source_url,
        file_size=size,
        duration=parsed.duration,
        status="uploaded",
    )
    db.add(ep)
    await db.flush()
    await db.refresh(ep)
    return ep.id
