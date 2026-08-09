"""去水印功能 API（v4）。

提供：
- 两套去水印引擎选择（remove-ai-watermarks / seedance 2.0 watermark remover）
- 批量上传 + 批量启动去水印任务（异步执行）
- 任务历史保存、进度展示、下载链接
- 任务/单条视频删除（含 MinIO 资源文件），多选批量操作
"""

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import ShortdramaPrompt, WatermarkTask, WatermarkVideo
from app.services.minio_service import (
    get_presigned_url,
    delete_file,
    upload_file_from_path,
)
from app.services.upload_service import validate_file_name
from app.services.redis_stream import get_redis

logger = logging.getLogger(__name__)

router = APIRouter()

# 允许的去水印引擎
ALLOWED_ENGINES = ("remove_ai", "seedance", "seedance_wm", "remove_mask")

# 任务名称自增序列的 Redis 键（跨实例全局自增，防并发重复）
_TASK_SEQ_REDIS_KEY = "watermark:task:seq"
# 当前日期对应的 Redis 键（日期变更自动从 1 重新计数）
_TASK_SEQ_DATE_KEY = "watermark:task:seq:date"


async def gen_task_name() -> str:
    """生成任务名称：日期（YYYYMMDD）+ 4 位自增序列。

    优先使用 Redis 做跨进程全局自增（日期切换自动归 1），
    Redis 不可用时回退到进程内自增，保证不抛错。
    """
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    try:
        client = await get_redis()
        today = now.strftime("%Y%m%d")
        current_date = await client.get(_TASK_SEQ_DATE_KEY)
        if current_date is None or current_date.decode() != today:
            # 新的一天：重置序列
            await client.set(_TASK_SEQ_DATE_KEY, today)
            await client.set(_TASK_SEQ_REDIS_KEY, 0)
        seq = await client.incr(_TASK_SEQ_REDIS_KEY)
    except Exception:
        seq = _fallback_seq()
    return f"{date_part}-{seq % 10000:04d}"


_fallback_counter = 0


def _fallback_seq() -> int:
    global _fallback_counter
    _fallback_counter = (_fallback_counter % 9999) + 1
    return _fallback_counter


ENGINE_DISPLAY = {
    "remove_ai": "Remove AI Watermarks（RAiW）",
    "seedance": "Seedance 2.0 Watermark Remover",
    "seedance_wm": "Seedance 5-Stage Pipeline（seedance_wm）",
    "remove_mask": "Remove Mask（ROI 经验库）",
}


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class WatermarkRunRequest(BaseModel):
    engine: str = "remove_ai"
    # RAiW 选项
    mark: Optional[str] = "auto"        # auto/sora/veo/seedance/dola/hailuo/kling
    backend: Optional[str] = "auto"     # auto/cv2/migan/lama（auto 优先 LaMa/MI-GAN CPU 模型）
    temporal_consistency: bool = True
    region: Optional[str] = None        # x,y,w,h 手动指定水印区域（RAiW 区域擦除 / Seedance 手动区域）
    # Seedance 选项
    use_lama: bool = False              # 兼容旧前端，等价 backend=lama
    segments: Optional[int] = 4         # 分段检测段数（移动水印调大）
    detector: Optional[str] = None      # seedance_wm 主检测器（matchTemplate/yolov8_seg/paddleocr）
    inpainter: Optional[str] = None     # seedance_wm 主修复器（lama/cv2_telea/cv2_ns）
    keep_audio: bool = True             # seedance_wm 是否保留原音轨
    # remove_mask 选项
    radius: Optional[int] = 3           # 修补半径（ROI + TELEA）
    iterations: Optional[int] = 1       # 修补迭代次数
    scope: Optional[str] = "small"      # remove_mask 水印 ROI 范围：small/large
    mode: Optional[str] = "inpaint"     # remove_mask 去水印模式：inpaint（插值修复）/crop（裁切）
    name: Optional[str] = None
    # 待处理视频的 source_file_key 列表（由 /watermark/upload 返回）
    files: List[str] = []
    # 任务来源关联（短片制作）：提示词记录 id，用于「去水印 → 发布」自动代入文案
    prompt_record_id: Optional[str] = None


class WatermarkVideoItem(BaseModel):
    id: str
    file_name: str
    file_size: Optional[int] = None
    status: str
    progress: float
    error_message: Optional[str] = None
    output_url: Optional[str] = None
    source_url: Optional[str] = None
    output_file_size: Optional[int] = None
    prompt_record_id: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None  # 处理消耗时长（秒）


class WatermarkTaskItem(BaseModel):
    id: str
    engine: str
    engine_display: str
    name: Optional[str] = None
    options: dict
    prompt_record_id: Optional[str] = None
    status: str
    progress: float
    total_count: int
    completed_count: int
    failed_count: int
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
    duration_seconds: Optional[float] = None  # 处理消耗时长（秒）


class WatermarkTaskDetail(WatermarkTaskItem):
    videos: List[WatermarkVideoItem] = []


class WatermarkDeleteRequest(BaseModel):
    task_ids: List[str] = []


# ──────────────────────────────────────────────
# 序列化
# ──────────────────────────────────────────────


def _serialize_video(video: WatermarkVideo, output_url: Optional[str] = None, source_url: Optional[str] = None) -> dict:
    duration = None
    if video.started_at and video.completed_at:
        duration = round((video.completed_at - video.started_at).total_seconds(), 1)
    return {
        "id": str(video.id),
        "file_name": video.file_name,
        "file_size": video.file_size,
        "source_file_key": video.source_file_key,
        "status": video.status,
        "progress": video.progress or 0.0,
        "error_message": video.error_message,
        "output_url": output_url,
        "source_url": source_url,
        "output_file_size": video.output_file_size,
        "prompt_record_id": str(video.prompt_record_id) if video.prompt_record_id else None,
        "created_at": video.created_at.isoformat() if video.created_at else "",
        "started_at": video.started_at.isoformat() if video.started_at else None,
        "completed_at": video.completed_at.isoformat() if video.completed_at else None,
        "duration_seconds": duration,
    }


def _serialize_task(task: WatermarkTask, fallback_prompt_record_id: Optional[str] = None) -> dict:
    duration = None
    if task.started_at:
        end = task.completed_at or datetime.utcnow()
        duration = round((end - task.started_at).total_seconds(), 1)
    opts = task.options or {}
    # 任务级来源关联优先；历史任务（修复前创建）options 未持久化该字段时，
    # 回退到子视频的来源提示词记录 id，保证「去水印 → 发布」链路始终可用
    prompt_record_id = opts.get("prompt_record_id") or fallback_prompt_record_id
    return {
        "id": str(task.id),
        "engine": task.engine,
        "engine_display": ENGINE_DISPLAY.get(task.engine, task.engine),
        "name": task.name,
        "options": opts,
        "prompt_record_id": prompt_record_id,
        "status": task.status,
        "progress": task.progress or 0.0,
        "total_count": task.total_count or 0,
        "completed_count": task.completed_count or 0,
        "failed_count": task.failed_count or 0,
        "error_message": task.error_message,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "duration_seconds": duration,
    }


# ──────────────────────────────────────────────
# API
# ──────────────────────────────────────────────


@router.post("/watermark/upload")
async def upload_watermark_video(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传单条待去水印视频，存入 MinIO（watermark-raw 桶）。

    返回 source_file_key，随后随任务一起提交处理。支持批量：前端可多次调用。
    """
    file_name = file.filename or ""
    try:
        safe_name = validate_file_name(file_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/watermark_upload/{upload_id}_{safe_name}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    size = 0
    with open(local_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.UPLOAD_MAX_SIZE:
                out.close()
                os.unlink(local_path)
                raise HTTPException(status_code=413, detail="文件超过大小上限")
            out.write(chunk)

    if size == 0:
        os.unlink(local_path)
        raise HTTPException(status_code=400, detail="文件为空")

    file_key = f"watermark-raw/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        settings.MINIO_BUCKET_WATERMARK_RAW,
        file_key,
        local_path,
        content_type=file.content_type or "video/mp4",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="文件上传存储失败")

    return {
        "file_name": safe_name,
        "source_file_key": file_key,
        "file_size": size,
        "upload_id": upload_id,
    }


@router.post("/watermark/run", response_model=dict)
async def run_watermark_task(
    data: WatermarkRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建去水印任务并异步执行。

    请求体示例：
    {
      "engine": "remove_ai",
      "mark": "auto",
      "backend": "auto",
      "temporal_consistency": true,
      "use_lama": false,
      "name": "批量去水印",
      "files": ["watermark-raw/xxx_1.mp4", "watermark-raw/xxx_2.mp4"]
    }
    """
    engine = data.engine
    if engine not in ALLOWED_ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"engine 不合法，仅支持 {'/'.join(ALLOWED_ENGINES)}",
        )

    file_keys = data.files or []
    if not file_keys:
        raise HTTPException(status_code=400, detail="至少需要一个待处理视频（files）")

    if len(file_keys) > 200:
        raise HTTPException(status_code=400, detail="单批最多 200 条视频")

    # 构造引擎选项
    options: dict = {}
    if engine == "remove_ai":
        options = {
            "mark": data.mark or "auto",
            "backend": data.backend or "auto",
            "temporal_consistency": bool(data.temporal_consistency),
        }
        if data.region:
            # 手动指定区域时走通用区域擦除（委托 seedance 视频级引擎，
            # 其修补层复用 RAiW 的 LaMa/MI-GAN CPU 模型），兜底处理非厂商水印
            options["region"] = data.region
    elif engine == "seedance":
        options = {
            "region": data.region,
            "backend": data.backend or "auto",
            "use_lama": bool(data.use_lama),
        }
        # 分段检测段数（移动水印时增大，默认 4）
        seg = int(data.segments or 4)
        options["segments"] = max(1, min(seg, 32))
    elif engine == "seedance_wm":
        options = {
            "region": data.region,
            "backend": data.backend or "auto",
            "keep_audio": bool(data.keep_audio),
        }
        seg = int(data.segments or 4)
        options["segments"] = max(1, min(seg, 32))
        if data.detector:
            options["detector"] = data.detector
        if data.inpainter:
            options["inpainter"] = data.inpainter
    elif engine == "remove_mask":
        options = {
            "region": data.region,
            "radius": int(data.radius or 3),
            "iterations": int(data.iterations or 1),
            "scope": data.scope if data.scope in ("small", "large") else "small",
            "mode": data.mode if data.mode in ("inpaint", "crop") else "inpaint",
        }
        # 原始文件名用于匹配内置 ROI 表（如 648BC321），由 celery 任务层传入
        if data.files:
            base = os.path.basename(data.files[0])
            parts = base.split("_", 1)
            source_name = parts[1] if (len(parts) == 2 and len(parts[0]) == 36) else base
            options["source_name"] = source_name

    # 校验来源提示词记录（可选），用于「去水印 → 发布」自动代入文案
    prompt_record_id = None
    if data.prompt_record_id:
        try:
            rid = uuid.UUID(data.prompt_record_id)
            pr = await db.execute(select(ShortdramaPrompt).where(ShortdramaPrompt.id == rid))
            if pr.scalar_one_or_none():
                prompt_record_id = rid
        except Exception:
            prompt_record_id = None

    # 任务级来源关联：写入 options（必须在任务创建/flush 之前写入，
    # 因为 options 是普通 JSON 列，flush 后再原地修改 dict 不会被 SQLAlchemy 追踪持久化）
    if prompt_record_id:
        options["prompt_record_id"] = str(prompt_record_id)

    # 创建任务记录（任务名称：优先使用前端传入的完整日期+自增序列，否则后端自动生成）
    task_name = data.name or await gen_task_name()
    task = WatermarkTask(
        engine=engine,
        options=options,
        name=task_name,
        status="pending",
        progress=0.0,
        total_count=len(file_keys),
    )
    db.add(task)
    await db.flush()

    # 创建子视频记录（file_key 与文件名解耦：从 key 提取原文件名）
    for fk in file_keys:
        base = os.path.basename(fk)
        # 去除 upload_id_ 前缀，还原原始文件名
        display_name = base
        if "_" in base:
            parts = base.split("_", 1)
            if len(parts) == 2 and len(parts[0]) == 36:
                display_name = parts[1]
        video = WatermarkVideo(
            task_id=task.id,
            file_name=display_name,
            source_file_key=fk,
            source_bucket=settings.MINIO_BUCKET_WATERMARK_RAW,
            file_size=0,
            status="pending",
            progress=0.0,
            prompt_record_id=prompt_record_id,
        )
        db.add(video)

    await db.commit()
    await db.refresh(task)

    # 异步派发
    from app.celery.tasks import watermark_task as celery_watermark_task
    celery_result = celery_watermark_task.delay(
        task_id=str(task.id),
        engine=engine,
        options=options,
    )
    task.celery_task_id = celery_result.id
    await db.commit()

    return {
        "task_id": str(task.id),
        "engine": engine,
        "message": f"去水印任务已创建（{len(file_keys)} 条视频），正在异步处理",
    }


@router.get("/watermark/tasks", response_model=List[WatermarkTaskItem])
async def list_watermark_tasks(
    db: AsyncSession = Depends(get_db),
):
    """任务历史列表（按创建时间倒序）。"""
    result = await db.execute(
        select(WatermarkTask).order_by(WatermarkTask.created_at.desc()).limit(200)
    )
    tasks = result.scalars().all()
    items = []
    # 历史任务（修复前）任务级 options 未持久化 prompt_record_id，
    # 从子视频的来源提示词记录回退（批量查询一次完成，避免 N+1），
    # 保证「去水印 → 发布」链路一致
    task_ids = [t.id for t in tasks]
    fallback_map: dict = {}
    if task_ids:
        vres = await db.execute(
            select(WatermarkVideo.task_id, WatermarkVideo.prompt_record_id)
            .where(
                WatermarkVideo.task_id.in_(task_ids),
                WatermarkVideo.prompt_record_id.isnot(None),
            )
            .distinct()
        )
        for tid, prid in vres.all():
            if tid not in fallback_map:
                fallback_map[tid] = str(prid)
    for t in tasks:
        items.append(_serialize_task(t, fallback_map.get(t.id)))
    return items


@router.get("/watermark/tasks/{task_id}", response_model=WatermarkTaskDetail)
async def get_watermark_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """任务详情：包含任务下的多条视频及其输出/源视频直链。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    result = await db.execute(select(WatermarkTask).where(WatermarkTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    videos_res = await db.execute(
        select(WatermarkVideo).where(WatermarkVideo.task_id == tid).order_by(WatermarkVideo.created_at.asc())
    )
    videos = videos_res.scalars().all()

    video_items = []
    for v in videos:
        output_url = None
        source_url = None
        if v.output_file_key:
            output_url = await get_presigned_url(
                v.output_bucket or settings.MINIO_BUCKET_WATERMARK,
                v.output_file_key,
                expires_seconds=3600,
            )
        if v.source_file_key:
            source_url = await get_presigned_url(
                v.source_bucket or settings.MINIO_BUCKET_WATERMARK_RAW,
                v.source_file_key,
                expires_seconds=3600,
            )
        video_items.append(_serialize_video(v, output_url, source_url))

    data = _serialize_task(task)
    data["videos"] = video_items
    # 历史任务（修复前）任务级 options 未持久化 prompt_record_id，
    # 从子视频来源回退，保证「去水印 → 发布」任务级关联始终可用
    if not data.get("prompt_record_id"):
        for v in videos:
            if v.prompt_record_id:
                data["prompt_record_id"] = str(v.prompt_record_id)
                break
    return data


@router.delete("/watermark/tasks/{task_id}", response_model=dict)
async def delete_watermark_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单个任务（含其全部视频的源文件与输出文件）。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    result = await db.execute(select(WatermarkTask).where(WatermarkTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    videos_res = await db.execute(
        select(WatermarkVideo).where(WatermarkVideo.task_id == tid)
    )
    videos = videos_res.scalars().all()

    # 任务正在运行中：先标记取消，让 Celery 任务在下一条视频处理前感知并中断
    if task.status in ("pending", "running"):
        task.status = "cancelled"
        await db.flush()

    # 删除 MinIO 源/输出文件
    # 来源提示词任务的源视频归属提示词记录，删除任务时保留（便于再次导入去水印）
    for v in videos:
        try:
            if v.source_file_key and not v.prompt_record_id:
                await delete_file(v.source_bucket or settings.MINIO_BUCKET_WATERMARK_RAW, v.source_file_key)
        except Exception as e:
            logger.warning("Delete source %s failed: %s", v.source_file_key, e)
        try:
            if v.output_file_key:
                await delete_file(v.output_bucket or settings.MINIO_BUCKET_WATERMARK, v.output_file_key)
        except Exception as e:
            logger.warning("Delete output %s failed: %s", v.output_file_key, e)

    await db.delete(task)
    await db.commit()
    return {"message": "任务及其资源文件已删除", "task_id": task_id}


@router.post("/watermark/tasks/batch-delete", response_model=dict)
async def batch_delete_watermark_tasks(
    data: WatermarkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除任务（多选）。"""
    ids = data.task_ids or []
    if not ids:
        raise HTTPException(status_code=400, detail="未选择任何任务")
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="单次最多批量删除 100 个任务")

    deleted = 0
    for tid_str in ids:
        try:
            tid = uuid.UUID(tid_str)
        except ValueError:
            continue
        result = await db.execute(select(WatermarkTask).where(WatermarkTask.id == tid))
        task = result.scalar_one_or_none()
        if not task:
            continue

        # 运行中任务先标记取消，避免 Worker 继续处理已删除任务的资源
        if task.status in ("pending", "running"):
            task.status = "cancelled"
            await db.flush()

        videos_res = await db.execute(
            select(WatermarkVideo).where(WatermarkVideo.task_id == tid)
        )
        videos = videos_res.scalars().all()
        for v in videos:
            # 来源提示词任务的源视频归属提示词记录，批量删除时同样保留
            try:
                if v.source_file_key and not v.prompt_record_id:
                    await delete_file(v.source_bucket or settings.MINIO_BUCKET_WATERMARK_RAW, v.source_file_key)
            except Exception as e:
                logger.warning("Delete source %s failed: %s", v.source_file_key, e)
            try:
                if v.output_file_key:
                    await delete_file(v.output_bucket or settings.MINIO_BUCKET_WATERMARK, v.output_file_key)
            except Exception as e:
                logger.warning("Delete output %s failed: %s", v.output_file_key, e)

        await db.delete(task)
        deleted += 1

    await db.commit()
    return {"message": f"已删除 {deleted} 个任务及其资源文件", "deleted": deleted}


@router.delete("/watermark/videos/{video_id}", response_model=dict)
async def delete_watermark_video(
    video_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除任务下的单条视频（含源文件与输出文件）。"""
    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video ID")

    result = await db.execute(select(WatermarkVideo).where(WatermarkVideo.id == vid))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 来源提示词任务的源视频归属提示词记录，删除任务视频时保留源文件（便于再次导入去水印）
    try:
        if video.source_file_key and not video.prompt_record_id:
            await delete_file(video.source_bucket or settings.MINIO_BUCKET_WATERMARK_RAW, video.source_file_key)
    except Exception as e:
        logger.warning("Delete source %s failed: %s", video.source_file_key, e)
    try:
        if video.output_file_key:
            await delete_file(video.output_bucket or settings.MINIO_BUCKET_WATERMARK, video.output_file_key)
    except Exception as e:
        logger.warning("Delete output %s failed: %s", video.output_file_key, e)

    await db.delete(video)
    await db.commit()
    return {"message": "视频及其资源文件已删除", "video_id": video_id}


@router.get("/watermark/videos/{video_id}/download")
async def download_watermark_video(
    video_id: str,
    db: AsyncSession = Depends(get_db),
):
    """单条处理后视频下载（重定向到 presigned URL）。"""
    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video ID")

    result = await db.execute(select(WatermarkVideo).where(WatermarkVideo.id == vid))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")

    if not video.output_file_key:
        raise HTTPException(status_code=400, detail="该视频尚未处理完成，无输出文件")

    url = await get_presigned_url(
        video.output_bucket or settings.MINIO_BUCKET_WATERMARK,
        video.output_file_key,
        expires_seconds=7200,
    )
    if not url:
        raise HTTPException(status_code=500, detail="生成下载链接失败")

    return {"url": url, "file_name": video.file_name}


@router.post("/watermark/videos/batch-download", response_model=dict)
async def batch_download_watermark_videos(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """批量下载：返回多条视频的 presigned 直链，前端逐个触发下载。"""
    ids = data.get("video_ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="未选择任何视频")
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="单次最多批量下载 100 条视频")

    files = []
    for vid_str in ids:
        try:
            vid = uuid.UUID(vid_str)
        except ValueError:
            continue
        result = await db.execute(select(WatermarkVideo).where(WatermarkVideo.id == vid))
        video = result.scalar_one_or_none()
        if not video or not video.output_file_key:
            continue
        url = await get_presigned_url(
            video.output_bucket or settings.MINIO_BUCKET_WATERMARK,
            video.output_file_key,
            expires_seconds=7200,
        )
        if url:
            files.append({
                "video_id": str(video.id),
                "file_name": video.file_name,
                "url": url,
            })

    if not files:
        raise HTTPException(status_code=404, detail="没有可下载的处理结果")

    return {"files": files}
