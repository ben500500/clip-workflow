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
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
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
    """导入任务失败（不可重试：链接失效、解析失败、入库失败等）。"""


class RetryableImportError(ImportError_):
    """可重试的导入失败（下载中断 / 网络抖动 / 限流等瞬态错误）。

    Celery 任务捕获后调用 self.retry()（配合 max_retries 与断点续传），
    避免一次瞬态失败就永久置 failed 导致自动化流程中断。
    """


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


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """naive UTC datetime → 带 Z 后缀的 ISO 字符串。

    全库时间列为 timestamp without time zone，应用写入 datetime.utcnow()。
    若直接 isoformat() 输出不带时区（如 2026-09-11T04:47:51），前端 dayjs 会
    按浏览器本地时区（+8）解析 → 显示比实际少 8 小时（任务 89847c6e 实例）。

    这里显式补 UTC 标记，前端 dayjs(dateStr).format() 即自动换算为本地时间。
    不用 app.utils.helpers.utc_iso 是为了保持本包可剥离（不依赖主系统模块）。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
        "created_at": _iso_utc(t.created_at),
        "updated_at": _iso_utc(t.updated_at),
    }


# 默认分辨率取值：720p / 1080p
DOWNLOAD_RESOLUTIONS = {"720p": "1280x720", "1080p": "1920x1080"}


async def _read_default_download_resolution(db: AsyncSession) -> str:
    """读取全局默认下载分辨率（system_config.default_download_resolution，默认 720p）。"""
    from app.models.models import SystemConfig
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "default_download_resolution")
        )
        cfg = result.scalar_one_or_none()
        if cfg and cfg.value in DOWNLOAD_RESOLUTIONS:
            return cfg.value
    except Exception:
        pass
    return "720p"


async def _apply_download_resolution(db: AsyncSession, local_path: str) -> None:
    """按全局默认分辨率对本地视频做 ffmpeg 缩放。

    读取 default_download_resolution（720p/1080p，默认 720p），若源视频分辨率
    高于目标则缩放到目标；低于目标则保持原分辨率（不放大），避免画质损失。
    只在 ffmpeg 可用时执行；失败不影响原视频（由调用方降级为原分辨率入库）。
    """
    import asyncio
    resolution = await _read_default_download_resolution(db)
    target = DOWNLOAD_RESOLUTIONS.get(resolution)
    if not target:
        return
    if not os.path.isfile(local_path) or os.path.getsize(local_path) == 0:
        return
    tmp_path = local_path + ".res.mp4"
    tw, th = target.split("x")
    # 仅当源视频任一维超过目标时缩放到目标（保持宽高比，不放大原分辨率）
    scale = f"scale=min(iw\,{tw}):min(ih\,{th}):force_original_aspect_ratio=decrease"
    cmd = [
        "ffmpeg", "-y", "-i", local_path,
        "-vf", scale,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "copy", tmp_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=1800)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise ImportError_("下载视频按默认分辨率缩放超时")
    if proc.returncode != 0:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise ImportError_("下载视频按默认分辨率缩放失败")
    # 缩放成功：用缩放后的文件替换原文件
    os.replace(tmp_path, local_path)
    logger.info("已按默认分辨率 %s 缩放下载视频 -> %s", resolution, target)


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
                # 下载中断（网络抖动/超时/限流）属瞬态错误，抛可重试异常供 Celery self.retry
                # （重试时 downloader 命中断点续传，从已下载字节继续，不重复拉取）。
                raise RetryableImportError(f"拉流下载失败(可重试): {e}")

            # 按默认分辨率统一缩放：读取全局配置 default_download_resolution
            # （720p/1080p，默认 720p），入库前用 ffmpeg 转码到目标分辨率。
            try:
                await _apply_download_resolution(db, local_path)
            except ImportError_:
                raise
            except Exception as e:
                logger.warning("下载视频按默认分辨率缩放失败，按原分辨率入库: %s", e)

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

        except RetryableImportError as e:
            # 可重试失败（下载中断/限流）：标记状态后把异常重新抛出，
            # 供 Celery 任务捕获并 self.retry（配合断点续传）。
            # _fail 内部已即时 commit，此处无需再提交。
            logger.warning("download pipeline retryable failure for task %s: %s", task_id, e)
            await _fail(db, task, str(e))
            raise
        except Exception as e:
            logger.exception("download pipeline failed for task %s", task_id)
            await _fail(db, task, str(e))
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

    先查本任务 source_url 在 wechat_parse_records 中是否已有 **TTL 内**的成功解析记录
    （命中直接复用 play_url，避免重复调用易变/限流的解析接口，评审 R1/R2）。
    超期记录不复用：直链签名仅 1~3 小时有效，复用死链必然 400。

    provider 顺序由 `WECHAT_DL_PROVIDERS`（默认 yuanbao,preview）驱动；逐个尝试，
    每个 provider 的成败都写一条 WechatParseRecord（channel=provider 逻辑名），
    任一个成功即返回，全部失败聚合各 provider 错误后抛 ImportError_。
    """
    # P1 解析缓存：同 URL 已有成功解析则直接复用
    cached = await _hit_parse_cache(db, task.source_url)
    if cached is not None:
        logger.info(
            "parse cache hit for %s (channel=%s, ttl=%ss)",
            task.source_url, cached.channel, settings.WECHAT_DL_PARSE_CACHE_TTL_SECONDS,
        )
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


def _parse_cache_cutoff(now: Optional[datetime] = None,
                        ttl_seconds: Optional[int] = None) -> datetime:
    """解析缓存的截止时间（naive UTC）：早于它的记录视为过期，不可复用。

    ⚠️ 必须在 Python 侧用 `datetime.utcnow()` 计算，**禁止在 SQL 里用 now()**：
    `wechat_parse_records.created_at` 是 timestamp without time zone，写入的是
    naive UTC（模型 default=datetime.utcnow）。若改用 SQL now()，PG 会按会话时区
    解释，在 Asia/Shanghai（+8）实例上 now() 比 UTC 快 8 小时，导致已过期的记录
    仍被判为「新鲜」，死链 bug 原样保留。用 Python 侧同源（utcnow）比较才与写入值同尺度。
    """
    ttl = ttl_seconds if ttl_seconds is not None else settings.WECHAT_DL_PARSE_CACHE_TTL_SECONDS
    return (now or datetime.utcnow()) - timedelta(seconds=ttl)


async def _hit_parse_cache(db: AsyncSession, source_url: str,
                           now: Optional[datetime] = None,
                           ttl_seconds: Optional[int] = None) -> Optional[ParseResult]:
    """命中解析缓存：返回同 URL 在 TTL 内最近一次成功解析结果，否则 None。

    仅取 status=success 且 play_url 非空的记录，按时间倒序取最新一条。
    避免对易变/限流的元宝接口重复调用（评审 R1/R2）。

    时效性（本缺陷修复点）：腾讯签名直链 play_url 只活 1~3 小时，过期后直接交给
    下载器必然 `direct download http 400`，且重试无效（解析缓存永远命中同一条死链）。
    因此只复用 `created_at >= utcnow() - WECHAT_DL_PARSE_CACHE_TTL_SECONDS` 的记录；
    超期记录一律不命中 → 走实时解析拿新直链。原 docstring 中「TTL 短时可由下载器
    兜底」的假设是错的：下载器的断点续传/重试无法修复已失效的签名。
    """
    cutoff = _parse_cache_cutoff(now, ttl_seconds)
    result = await db.execute(
        select(WechatParseRecord)
        .where(
            WechatParseRecord.source_url == source_url,
            WechatParseRecord.status == "success",
            WechatParseRecord.play_url.isnot(None),
            # 时效窗口：naive UTC 与 Python 侧 cutoff 同尺度比较（勿用 SQL now()）
            WechatParseRecord.created_at >= cutoff,
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


async def _commit_status(db, task):
    """提交状态变更（写库优先，失败不抛出）。

    状态/进度必须即时落库：外部（GET /api/wechat-dl/tasks、运维排查）只读库，
    仅 flush 不 commit 会让中间态在事务结束前对外不可见——worker 崩溃即回滚，
    任务永久停在 pending（生产实例 1b2eb0ae 卡两周的根因）。

    提交失败时回滚并降级为 flush（保留 WS 实时进度），绝不让「状态写库」
    这一观测动作影响下载主流程。
    """
    try:
        await db.commit()
    except Exception as e:  # pragma: no cover - 依赖异常路径
        logger.warning("commit wechat_dl task %s status failed: %s", task.id, e)
        try:
            await db.rollback()
            await db.flush()
        except Exception:
            logger.exception("rollback/flush wechat_dl task %s status failed", task.id)


async def _set_status(db, task, status, progress, message):
    """更新任务状态/进度 → 即时 commit → 发布 WebSocket 进度。

    commit 先于 publish：前端收到 WS 推送后若立刻回查 REST，库里已是新状态。
    """
    task.status = status
    task.progress = progress
    task.message = message
    await _commit_status(db, task)
    await _publish_progress(task)


async def _fail(db, task, error):
    """标记任务失败（终态）→ 即时 commit → 发布 WebSocket 进度。"""
    task.status = ST_FAILED
    task.error_message = error
    await _commit_status(db, task)
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


def _is_stale_pending(task: WechatDownloadTask, now: Optional[datetime] = None,
                      timeout_seconds: Optional[int] = None) -> bool:
    """任务是否属于「超时未收敛」的可重试孤儿。

    判定条件（须同时满足）：
    1. 非终态（pending/parsing/downloading/uploading）——已完成任务不可重投；
    2. 距最后一次更新（updated_at，退化为 created_at）已超过阈值——
       worker 崩溃/节点重启/消息丢失后，任务永远停在投递时的 pending。

    阈值默认取 WECHAT_DL_STALE_TIMEOUT_SECONDS（3600s），远大于
    WECHAT_DL_DOWNLOAD_TIMEOUT，避免把正在跑的任务误判为孤儿。
    """
    if task.status in (ST_COMPLETED, ST_FAILED):
        return False
    timeout = timeout_seconds or settings.WECHAT_DL_STALE_TIMEOUT_SECONDS
    ref = task.updated_at or task.created_at
    if ref is None:
        return False
    now = now or datetime.utcnow()
    if ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    return (now - ref).total_seconds() > timeout


async def retry_task(db: AsyncSession, task_id: uuid.UUID) -> dict:
    """重投一个失败/超时卡死的任务到下载队列（Web 端「重试」按钮）。

    允许重试的状态（评审放宽）：
    - failed：明确失败，直接重投；
    - 非终态但已超时（见 _is_stale_pending）：worker 崩溃遗留的 pending/中间态孤儿
      （如生产实例 1b2eb0ae 卡两周）。此前这类任务既不落 failed 也无法重试，
      只能人工改库；本次放宽后可由页面「重试」或 beat 守护任务回收。

    重置进度/错误信息后重新投递 wechat_dl 队列，复用既有 celery task
    （wechat_dl.download），无需前端重新提交分享链接。
    """
    task = await get_task(db, task_id)
    if task is None:
        return {"ok": False, "message": "任务不存在"}
    if task.status == ST_COMPLETED:
        return {"ok": False, "message": "任务已完成，无需重试"}
    if task.status != ST_FAILED and not _is_stale_pending(task):
        return {
            "ok": False,
            "message": f"任务正在执行中，暂不可重试（当前状态: {task.status}；"
                       f"超过 {settings.WECHAT_DL_STALE_TIMEOUT_SECONDS}s 未更新后可重试）",
        }

    task.status = ST_PENDING
    task.progress = 0.0
    task.message = "已重新投递到下载队列"
    task.error_message = None
    # 即时提交再投递：worker 另开 session 读库，未提交则查不到该行（同 /import 竞态）
    await db.commit()

    # 延迟导入：celery tasks 反向 import 本模块，模块级导入会形成循环依赖
    from app.celery.tasks import celery_app

    celery_task = celery_app.send_task(
        "wechat_dl.download",
        args=[str(task.id)],
        queue=settings.WECHAT_DL_QUEUE,
    )
    task.celery_task_id = celery_task.id if celery_task else None
    await db.commit()

    logger.info("wechat dl task %s re-queued for retry", task.id)
    return {
        "ok": True,
        "task_id": str(task.id),
        "message": "任务已重新投递到下载队列",
    }


# ───────────────────────────────
# 超时卡死任务回收（beat 守护）
# ───────────────────────────────

async def recover_stale_tasks(timeout_seconds: Optional[int] = None) -> list[dict]:
    """把超时未收敛的非终态任务回写 failed，返回被回收的任务摘要。

    兜底场景（方案 B）：worker 崩溃 / 节点重启 / 消息丢失，任务永远停在
    pending 或中间态且无任何外部可见变化。仅靠 RT 侧的「允许超时 pending 重试」
    仍需人工点击，本守护把孤儿任务收敛为 failed，使既有重试按钮与告警链路生效。

    注意：Celery 的 task_reject_on_worker_lost 只能处理「已被消费」的任务；
    消息在 broker 中丢失/被 purge 时无人消费，因此必须有库侧巡检兜底。
    """
    from app.database import async_session_factory

    timeout = timeout_seconds or settings.WECHAT_DL_STALE_TIMEOUT_SECONDS
    cutoff = datetime.utcnow() - timedelta(seconds=timeout)
    active = (ST_PENDING, ST_PARSING, ST_DOWNLOADING, ST_UPLOADING)
    recovered: list[dict] = []

    async with async_session_factory() as db:
        # 以 updated_at（退化为 created_at）判定：非终态且超过阈值未更新即为孤儿
        result = await db.execute(
            select(WechatDownloadTask).where(
                WechatDownloadTask.status.in_(active),
                func.coalesce(
                    WechatDownloadTask.updated_at, WechatDownloadTask.created_at
                ) < cutoff,
            )
        )
        for task in result.scalars().all():
            prev_status = task.status
            task.status = ST_FAILED
            task.error_message = (
                f"任务超时未完成（超过 {timeout}s 无状态更新），"
                f"判定为 worker 崩溃/节点重启遗留，可由「重试」重新投递"
            )
            recovered.append({"task_id": str(task.id), "prev_status": prev_status})

        if recovered:
            try:
                await db.commit()
            except Exception:
                logger.exception("recover stale wechat_dl tasks commit failed")
                return []
            for item in recovered:
                logger.warning("wechat_dl stale task recovered: %s", item["task_id"])
    return recovered
