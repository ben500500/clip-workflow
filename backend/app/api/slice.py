"""切片任务 API。

支持两种引擎分发方式：
- worker：通过 Redis Stream 将切片任务分发到分布式 Worker 节点（默认）
- celery：回退到 Celery 队列（兼容旧版，迁移期可回退）

Worker 完成/失败/进度均通过回调接口上报，回调与上传 URL 申请接口使用
每次任务生成的临时 Token 鉴权，防止伪造回调。
"""

import json
import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import (
    Episode,
    SliceTask,
    SliceOutput,
    ClipCandidate,
    DetectedInterval,
    SystemConfig,
    User,
    AutoClipProject,
)
from app.services.data_scope import check_project_access_by_episode
from app.services.autoclip_service import generate_subtitle
from app.utils.helpers import utc_iso,  generate_cutlist, generate_intervals_file, format_time
from app.services.minio_service import (
    get_presigned_url,
    get_presigned_upload_url,
    ensure_bucket,
    list_files,
    delete_file,
)
from app.services.redis_stream import (
    publish_slice_task,
    get_task_redis_status,
    store_task_callback_token,
    get_task_callback_token,
    mark_task_cancelled,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 供 Go slice-worker 回调使用的开放 router（走 X-Worker-Token 鉴权，而非用户 JWT），
# 在 main.py 中单独挂载、不套用户鉴权依赖。
worker_router = APIRouter()

# 允许的引擎类型
ALLOWED_ENGINES = ("celery", "worker")


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class BadgeItem(BaseModel):
    """图片角标项：在切片成品上叠加一个角标。

    - file_key：上传到 MinIO 的角标图片 key
    - position：六角位置（top-left/top-center/top-right/bottom-left/bottom-center/bottom-right）
    - width：角标宽度（px，可选；0/空=用默认尺寸或保持原图）
    - offset：到视频边缘的偏移量（px，可选，默认 10）
    - opacity：角标透明度（0~1，可选，默认 1 不透明）
    """
    file_key: str = ""
    position: str = "top-left"
    width: Optional[int] = None
    offset: Optional[int] = None
    opacity: Optional[float] = None


class SliceRunRequest(BaseModel):
    mode: str = "fast"
    dedupe_config: Optional[dict] = None
    video_path: Optional[str] = None
    engine: Optional[str] = None  # "celery" | "worker"，默认取配置 SLICE_ENGINE
    # 免审核一键切片：为 True 时自动把所有候选片段（含 pending）纳入切片，
    # 不再要求存在 status=accepted 的片段
    auto_accept_all: bool = False
    # ── 自定义文字水印 ──
    # 水印开关：开启后会在切片成品视频上叠加动态文字水印
    watermark_enabled: bool = False
    # 水印文字内容（可自定义，默认使用剧集标题 + 日期）
    watermark_text: Optional[str] = None
    # 水印字号（px，默认 28）
    watermark_font_size: int = 28
    # 水印透明度（0~1，默认 0.5）
    watermark_opacity: float = 0.5
    # 水印位置（bottom 底部 / top 顶部，默认 bottom）
    watermark_position: str = "bottom"
    # ── 三期 GPU 加速编码 ──
    # 视频编码器：h264_nvenc / hevc_nvenc / h264_videotoolbox / hevc_videotoolbox / libx264
    # 不传时引擎自动探测（有 GPU 硬件编码器则优先使用，否则回退 libx264）
    encoder: Optional[str] = None
    # ── 成品重新剪辑 ──
    # 指定某个切片输出（成品视频）作为源，重新裁剪出一个新片段。
    # 提供 output_id 时，源视频为该成品的 file_key（sliced 桶），而非剧集原始素材。
    output_id: Optional[str] = None
    # 剪辑区间（相对成品起点，秒）。默认整段（0 ~ 成品时长）
    cut_start: Optional[float] = None
    cut_end: Optional[float] = None
    # ── 图片角标（切片后在成品上叠加角标，全程覆盖指定位置）──
    # 角标列表：每个元素含 file_key（上传的角标图片 MinIO key）、position（位置）、
    # width（可选宽度）、offset（可选边缘偏移）、opacity（可选透明度）。支持同时添加多个角标。
    badges: Optional[List[BadgeItem]] = None
    # 角标默认尺寸（px）：角标未单独设置 width 时的统一宽度；0=保持原图尺寸。可选。
    badge_default_width: int = 0
    # ── 竖屏转横屏智能裁切（切片前预处理）──
    # 开启后切片前自动检测素材方向，竖屏素材先转成横屏再切片
    vert2horiz_enabled: bool = False
    # 裁切模式：fixed 固定裁切（快速）/ dynamic 动态人脸跟踪（精准）
    vert2horiz_mode: Optional[str] = None
    # 裁切比例（宽/高，默认 9/16 = 0.5625）
    vert2horiz_ratio: Optional[float] = None
    # 输出分辨率（默认 1280x720）
    vert2horiz_output_size: Optional[str] = None
    # 动态模式：人脸检测间隔（帧，默认 2）
    vert2horiz_detect_interval: Optional[int] = None
    # 动态模式：平滑窗口（帧，默认 15）
    vert2horiz_smooth_window: Optional[int] = None
    # 动态模式：最小移动阈值（源画面像素，默认 5）。值越大画面越平稳、
    # 越小越跟手；画面抖动明显时可调大，人物走动跟不丢时可调小。
    vert2horiz_min_step: Optional[int] = None
    # ── ASR 字幕烧录 ──
    # 开启后对源视频做 ASR 语音识别生成字幕，并烧录到每个切片成品上
    subtitle_enabled: bool = False
    # 字幕字号（相对输出视频高度的比例，默认 0.20→FontSize 20，约占画面 5%；不传用引擎默认值）。
    # 用户可调大以让字幕更清晰易读，例如 0.10~0.30。
    subtitle_font_ratio: Optional[float] = None
    # 字幕样式（default=白字黑边+半透明黑底；custom=自定义字体色/边框色且无底色）。
    # 仅在 subtitle_enabled 开启且为 custom 时生效。
    subtitle_style: Optional[str] = None
    # 自定义字幕样式的字体颜色（CSS 十六进制 #RRGGBB）
    subtitle_color: Optional[str] = None
    # 自定义字幕样式的边框颜色（CSS 十六进制 #RRGGBB）
    subtitle_border_color: Optional[str] = None


class SliceRunResponse(BaseModel):
    task_id: str
    engine: str
    message: str


class SliceTaskResponse(BaseModel):
    id: str
    episode_id: str
    mode: Optional[str] = None
    status: Optional[str] = None
    progress: float
    output_count: int
    error_message: Optional[str] = None
    # 实际执行该任务的 Worker 节点 ID
    node_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class SliceOutputResponse(BaseModel):
    id: str
    task_id: str
    clip_id: Optional[str] = None
    file_key: Optional[str] = None
    file_name: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    resolution: Optional[str] = None
    created_at: str
    presigned_url: Optional[str] = None

    model_config = {"from_attributes": True}


class SliceTaskCallback(BaseModel):
    """Worker 回调请求体"""
    task_id: str
    status: str  # "completed" | "failed" | "progress"
    node_id: Optional[str] = None
    outputs: list[dict] = []
    output_count: int = 0
    error: str = ""
    progress: Optional[float] = None
    phase: str = ""
    completed_at: Optional[str] = None


# ──────────────────────────────────────────────
# 序列化函数
# ──────────────────────────────────────────────


def _serialize_task(task: SliceTask) -> dict:
    return {
        "id": str(task.id),
        "episode_id": str(task.episode_id),
        "mode": task.mode,
        "status": task.status,
        "progress": task.progress or 0.0,
        "output_count": task.output_count or 0,
        "error_message": task.error_message,
        "node_id": task.node_id,
        "started_at": utc_iso(task.started_at) if task.started_at else None,
        "completed_at": utc_iso(task.completed_at) if task.completed_at else None,
        "created_at": utc_iso(task.created_at) if task.created_at else "",
    }


def _serialize_output(output: SliceOutput, presigned_url: Optional[str] = None) -> dict:
    return {
        "id": str(output.id),
        "task_id": str(output.task_id),
        "clip_id": str(output.clip_id) if output.clip_id else None,
        "file_key": output.file_key,
        "file_name": output.file_name,
        "duration": output.duration,
        "file_size": output.file_size,
        "resolution": output.resolution,
        "created_at": utc_iso(output.created_at) if output.created_at else "",
        "presigned_url": presigned_url,
    }


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


def _resolve_engine(request_engine: Optional[str]) -> str:
    """解析最终使用的引擎类型。"""
    engine = request_engine or settings.SLICE_ENGINE
    if engine not in ALLOWED_ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"engine 参数不合法，仅支持 {'/'.join(ALLOWED_ENGINES)}",
        )
    return engine


def _build_watermark_config(
    data: SliceRunRequest,
    episode: Episode,
) -> Optional[dict]:
    """构造水印配置（字典），未开启时返回 None。

    文字内容支持通过 {title} / {date} / {datetime} 占位符自动填充；
    留空时默认使用剧集标题 + 日期。
    """
    if not data.watermark_enabled:
        return None
    text = (data.watermark_text or "").strip()
    now = datetime.now()
    if not text:
        text = "{title} {date}"
    text = (
        text
        .replace("{title}", (episode.title or "").strip() or "Clip")
        .replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{datetime}", now.strftime("%Y-%m-%d %H:%M"))
    )
    if not text.strip():
        text = "Clip Workflow"
    # 转义 ffmpeg drawtext 特殊字符（冒号/逗号等）
    text = text.replace(":", "\\:").replace(",", "\\,").replace("'", "\\\\'")
    return {
        "text": text,
        "font_size": max(12, min(120, int(data.watermark_font_size or 28))),
        "opacity": max(0.05, min(1.0, float(data.watermark_opacity or 0.5))),
        "position": "top" if data.watermark_position == "top" else "bottom",
    }


def _build_vert2horiz_config(data: SliceRunRequest) -> Optional[dict]:
    """构造竖屏转横屏预处理配置（字典），未启用时返回 None。

    前端以 vert2horiz_* 平铺参数传入，这里转换为引擎 --vert2horiz
    期望的嵌套 JSON 结构（含 enabled 开关，引擎 parse_vert2horiz_config
    依赖该字段判断是否启用）。
    """
    if not data.vert2horiz_enabled:
        return None
    mode = (data.vert2horiz_mode or "fixed").lower()
    if mode not in ("fixed", "dynamic"):
        mode = "fixed"
    cfg = {
        "enabled": True,
        "mode": mode,
    }
    if data.vert2horiz_ratio is not None:
        ratio = float(data.vert2horiz_ratio)
        if 0 < ratio < 1:
            cfg["ratio"] = ratio
    if data.vert2horiz_output_size:
        cfg["output_size"] = data.vert2horiz_output_size.strip()
    if data.vert2horiz_detect_interval is not None:
        cfg["detect_interval"] = max(1, int(data.vert2horiz_detect_interval))
    if data.vert2horiz_smooth_window is not None:
        cfg["smooth_window"] = max(1, int(data.vert2horiz_smooth_window))
    if data.vert2horiz_min_step is not None:
        # 最小移动阈值：允许 0（完全跟手、不抑制微平移），但至少 >=0
        cfg["min_step"] = max(0, int(data.vert2horiz_min_step))
    return cfg


def _build_badges_config(data: SliceRunRequest) -> Optional[list]:
    """构造图片角标配置列表（引擎 --badges 期望的 JSON 数组）。

    仅保留合法角标；每个角标含 file_key（MinIO 对象 key）、position（位置）、
    width（可选宽度）、offset（可选边缘偏移）、opacity（可选透明度）。
    位置限定为六角：左上/中上/右上/左下/中下/右下。
    """
    if not data.badges:
        return None
    allowed = {
        "top-left", "top-center", "top-right",
        "bottom-left", "bottom-center", "bottom-right",
    }
    result = []
    for b in data.badges:
        if not b.file_key:
            continue
        position = (b.position or "top-left").lower()
        if position not in allowed:
            position = "top-left"
        item = {
            "file_key": b.file_key,
            "position": position,
        }
        if b.width is not None:
            item["width"] = max(1, int(b.width))
        if b.offset is not None:
            item["offset"] = max(0, int(b.offset))
        if b.opacity is not None:
            item["opacity"] = min(1.0, max(0.0, float(b.opacity)))
        result.append(item)
    return result if result else None


# autoclip 选点阶段生成的源视频字幕文件（whisper/aliyun ASR）所在目录
# 与 autoclip 的 MEDIA_DIR 一致（两者都挂载 media_data volume）：
#   autoclip/app/core/shared_config.py -> METADATA_DIR = MEDIA_DIR / "data/output/metadata"
#   字幕文件保存为 {project_id}/subtitle.srt
# 可通过环境变量 AUTOCLIP_METADATA_DIR 覆盖（正常情况下无需设置）。
_AUTOCLIP_METADATA_DIR = os.getenv(
    "AUTOCLIP_METADATA_DIR", "/app/media/data/output/metadata"
).rstrip("/")


async def _read_existing_subtitle(episode: Episode, db: AsyncSession) -> Optional[dict]:
    """尝试复用选点阶段（autoclip whisper/aliyun ASR）已生成的源视频字幕。

    选点流水线 Step 0 已对源视频做 ASR 并生成字幕文件
    `{METADATA_DIR}/{autoclip_project_id}/subtitle.srt`，保存在共享的 media_data volume
    中（backend 与 autoclip 都挂载该卷）。切片烧录字幕时若能找到这份已翻译好的字幕，
    直接按时间轴复用即可，完全避免二次 ASR 转写（省时间、省 API 费用/算力，且与
    选点阶段看到的台词一致）。

    返回 {"enabled": True, "srt": str}；找不到或读不到返回 None（由调用方回退到 ASR）。
    """
    # 查询该剧集关联的 autoclip 项目 id（选点生成字幕所用的 project_id）
    res = await db.execute(
        select(AutoClipProject).where(AutoClipProject.episode_id == episode.id)
    )
    proj = res.scalar_one_or_none()
    if not proj or not proj.autoclip_project_id:
        logger.info("该剧集尚未做过 AI 智能选点，无可用字幕复用，回退到 ASR 生成")
        return None
    srt_path = os.path.join(
        _AUTOCLIP_METADATA_DIR, str(proj.autoclip_project_id), "subtitle.srt"
    )
    try:
        if not os.path.isfile(srt_path) or os.path.getsize(srt_path) == 0:
            logger.info("选点阶段无字幕文件（%s），回退到 ASR 生成", srt_path)
            return None
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return None
        logger.info("复用选点阶段已生成的字幕（%s），跳过二次 ASR", srt_path)
        return {"enabled": True, "srt": content}
    except OSError as e:
        logger.warning("读取选点字幕失败: %s: %s", srt_path, e)
        return None


def _with_subtitle_options(cfg: dict, data: SliceRunRequest) -> dict:
    """把用户设置的字幕样式（字号/自定义字体色/边框色）写入字幕配置，随任务下发给引擎。"""
    if data.subtitle_font_ratio is not None and data.subtitle_font_ratio > 0:
        cfg["font_ratio"] = round(float(data.subtitle_font_ratio), 4)
    if data.subtitle_style:
        cfg["style"] = data.subtitle_style
    if data.subtitle_color:
        cfg["font_color"] = data.subtitle_color
    if data.subtitle_border_color:
        cfg["border_color"] = data.subtitle_border_color
    return cfg


async def _generate_subtitle_config(
    data: SliceRunRequest,
    source_file_key: Optional[str],
    source_bucket: str,
    episode: Optional[Episode] = None,
    db: Optional[AsyncSession] = None,
) -> Optional[dict]:
    """构造字幕烧录配置：开启时优先复用选点阶段已生成的源视频字幕，否则调用 autoclip ASR。

    返回 {"enabled": True, "srt": "..."}；未开启或生成失败返回 None。
    优先复用：该剧集做过 AI 智能选点（whisper/aliyun 已转写源视频）时，直接读取其
    subtitle.srt 复用，避免重复 ASR；未做过选点时再回退到 ASR 生成（带缓存）。
    """
    if not data.subtitle_enabled:
        return None
    if not source_file_key:
        logger.warning("字幕已开启，但缺少源视频 file_key，跳过字幕生成")
        return None
    # 1) 优先复用选点阶段 whisper/aliyun 已翻译好的字幕（仅常规切片；以切片成品为源的
    #    重新剪辑（output_id）时间轴从 0 开始、与原始字幕不同，不适用，走回退）
    if not data.output_id and episode is not None and db is not None:
        reused = await _read_existing_subtitle(episode, db)
        if reused is not None:
            return _with_subtitle_options(reused, data)
    # 2) 回退：调用 autoclip ASR 生成（复用 ASR 缓存）
    source_url = await get_presigned_url(source_bucket, source_file_key, expires_seconds=7200)
    if not source_url:
        logger.warning("字幕已开启，但生成源视频下载 URL 失败，跳过字幕生成")
        return None
    result = await generate_subtitle(source_url)
    if not result or not result.get("srt") or not result["srt"].strip():
        logger.warning("ASR 字幕生成结果为空（视频可能无语音或转写失败），跳过字幕烧录")
        return None
    return _with_subtitle_options({"enabled": True, "srt": result["srt"]}, data)


def _not_detect_task():
    """SQLAlchemy 条件：排除 detect_* 内部进度跟踪记录，同时允许 mode 为 NULL 的真实切片任务。

    注意：不能用 `~SliceTask.mode.like("detect_%")`，因为 mode 为 NULL 的历史任务
    在 SQL 三值逻辑下会被一并过滤掉，导致成品预览里没有任务可选。
    """
    return or_(
        SliceTask.mode.is_(None),
        ~SliceTask.mode.like("detect_%"),
    )


async def _get_max_concurrent_tasks(db: AsyncSession) -> int:
    """读取系统配置中的全局最大并发切片任务数（多人同时切片的全局闸门）。

    默认 4；配置不存在或非法时使用默认值。
    """
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "max_concurrent_tasks")
        )
        cfg = result.scalar_one_or_none()
        if cfg and cfg.value is not None:
            val = int(cfg.value)
            if val > 0:
                return val
    except (TypeError, ValueError):
        pass
    return 4


async def _acquire_concurrency_slot(db: AsyncSession) -> None:
    """全局并发闸门：超过 max_concurrent_tasks 个运行中/排队中的切片任务时拒绝新任务。

    适用于多用户/多剧集同时发起切片，保证重任务不会无限堆积抢占资源。
    """
    max_concurrent = await _get_max_concurrent_tasks(db)
    running_count = (
        await db.execute(
            select(func.count(SliceTask.id)).where(
                SliceTask.status.in_(["running", "pending"]),
                _not_detect_task(),
            )
        )
    ).scalar() or 0
    # 注意：调用时新任务尚未写入 DB，因此 running_count 为当前在飞任务数；
    # 允许在 running_count < max 时放行新任务，等于最多同时处理 max 个。
    if running_count >= max_concurrent:
        raise HTTPException(
            status_code=429,
            detail=(
                f"当前已有 {running_count} 个切片任务在运行/排队，"
                f"已达到全局并发上限 {max_concurrent}。"
                "请稍后再试，或到「系统设置」调大 max_concurrent_tasks。"
            ),
        )


def _output_prefix(slice_task: SliceTask) -> str:
    """输出文件在 MinIO 中的 key 前缀。"""
    return f"slices/{str(slice_task.episode_id)}/{str(slice_task.id)}/"


async def _refresh_episode_status(db: AsyncSession, episode_id) -> None:
    """根据该剧集下所有切片任务的实际状态刷新剧集状态。

    规则：
    - 若存在 running/pending 任务 → 保持/置为 slicing
    - 否则若存在已完成任务且无失败 → completed
    - 否则若全部为失败/取消 → failed（有失败任务时保持 slicing 会导致用户永远看不到
      "已切完还是切片中"的问题，因此这里统一推进到 failed，由前端引导重试）
    - 若没有任何任务 → 不改变（避免误覆盖新上传/选点状态）
    """
    try:
        eid = uuid.UUID(str(episode_id))
    except ValueError:
        return

    ep_res = await db.execute(select(Episode).where(Episode.id == eid))
    episode = ep_res.scalar_one_or_none()
    if not episode:
        return

    tasks_res = await db.execute(
        select(SliceTask).where(
            SliceTask.episode_id == eid,
            _not_detect_task(),
        )
    )
    all_tasks = tasks_res.scalars().all()
    if not all_tasks:
        return

    has_running = any(t.status in ("running", "pending") for t in all_tasks)
    has_completed = any(t.status == "completed" for t in all_tasks)
    has_failed = any(t.status in ("failed", "cancelled") for t in all_tasks)

    if has_running:
        if episode.status != "completed":
            episode.status = "slicing"
    elif has_completed and not has_failed:
        episode.status = "completed"
    elif has_completed and has_failed:
        # 部分成功、部分失败：保留 completed 更符合用户预期（有成品可看）
        episode.status = "completed"
    else:
        # 全部失败/取消：置为 failed，避免长期停留在 slicing
        episode.status = "failed"


async def _publish_to_worker(
    slice_task: SliceTask,
    episode: Episode,
    cutlist: str,
    intervals_content: str,
    source_file_key: Optional[str],
    dedupe_config: Optional[dict],
    watermark_config: Optional[dict] = None,
    encoder: Optional[str] = None,
    vert2horiz_config: Optional[dict] = None,
    badges_config: Optional[list] = None,
    badge_default_width: int = 0,
    source_bucket: str = "",
    subtitle_config: Optional[dict] = None,
) -> bool:
    """构造 Worker 任务 payload 并发布到 Redis Stream。

    Returns:
        是否成功发布
    """
    # 生成源视频的 presigned GET URL（有效期 2 小时）
    # 普通切片源为剧集原始素材（raw-footage 桶）；
    # 成品重新剪辑（output_id）时源为该成品视频（sliced 桶）。
    source_url = None
    if source_file_key:
        source_url = await get_presigned_url(
            source_bucket or settings.MINIO_BUCKET_RAW,
            source_file_key,
            expires_seconds=7200,
        )

    # 角标图片：为每个角标生成 presigned GET URL，Worker 下载后供引擎叠加
    badge_items = None
    if badges_config:
        badge_items = []
        for b in badges_config:
            url = await get_presigned_url(
                settings.MINIO_BUCKET_RAW,
                b["file_key"],
                expires_seconds=7200,
            )
            if url:
                badge_items.append({
                    "url": url,
                    "position": b.get("position", "top-left"),
                    "width": b.get("width"),
                    "offset": b.get("offset"),
                    "opacity": b.get("opacity"),
                })

    # 每次任务生成独立的回调/上传鉴权 Token
    callback_token = secrets.token_hex(16)

    # 回调地址使用可配置的基础地址（支持远程 Worker 通过公网/内网访问）
    callback_base = settings.WORKER_CALLBACK_BASE_URL.rstrip("/")
    callback_url = f"{callback_base}/api/slice-tasks/{slice_task.id}/callback"

    # 构造 Worker 任务 payload（匹配 Go Worker 的 SliceTask 结构体）
    task_payload = {
        "task_id": str(slice_task.id),
        "episode_id": str(slice_task.episode_id),
        "priority": "normal",
        "mode": slice_task.mode or "fast",
        "required_tags": [],
        "source": {
            "url": source_url or "",
        },
        "cutlist": cutlist,
        "intervals": intervals_content,
        "dedupe_config": dedupe_config or {},
        # 自定义文字水印配置（可选，Go Worker 透传给引擎）
        "watermark": watermark_config,
        # 三期 GPU 加速编码（可选，Go Worker 透传给引擎 --encoder）
        "encoder": encoder,
        # 竖屏转横屏预处理配置（可选，Go Worker 透传给引擎 --vert2horiz）
        "vert2horiz": vert2horiz_config,
        # 图片角标（可选，Go Worker 下载图片后透传给引擎 --badges）
        "badges": badge_items,
        # 角标默认尺寸（px，可选，Go Worker 透传给引擎 --badge-default-width）
        "badge_default_width": badge_default_width or 0,
        # ASR 字幕烧录（可选，Go Worker 把 SRT 写到本地后透传给引擎 --subtitle）
        "subtitle": subtitle_config,
        "output": {
            "upload_url": f"{callback_base}/api/slice-tasks/{slice_task.id}/upload-url",
            "callback_url": callback_url,
            "output_prefix": _output_prefix(slice_task),
            "callback_token": callback_token,
        },
        "timeout_seconds": settings.SLICE_TASK_TIMEOUT_SECONDS,
        "created_at": utc_iso(datetime.utcnow()),
    }

    # 保存回调 Token 到 Redis（供回调/上传接口鉴权校验）
    await store_task_callback_token(str(slice_task.id), callback_token)

    # 发布到 Redis Stream
    msg_id = await publish_slice_task(task_payload)
    if not msg_id:
        logger.error("Failed to publish slice task %s to Redis Stream", slice_task.id)
        return False

    logger.info(
        "Published slice task %s to Redis Stream (msg_id=%s)",
        slice_task.id,
        msg_id,
    )
    return True


async def _dispatch_celery(
    slice_task: SliceTask,
    episode: Episode,
    cutlist: str,
    intervals_content: str,
    source_file_key: Optional[str],
    dedupe_config: Optional[dict],
    video_path: Optional[str],
    watermark_config: Optional[dict] = None,
    encoder: Optional[str] = None,
    vert2horiz_config: Optional[dict] = None,
    badges_config: Optional[list] = None,
    badge_default_width: int = 0,
    source_bucket: str = "",
    subtitle_config: Optional[dict] = None,
) -> bool:
    """通过 Celery 队列分发切片任务（回退路径）。"""
    from app.celery.tasks import slice_task as celery_slice_task

    # 与旧版 Celery 路径一致：优先使用本地视频路径
    if video_path:
        source_path = video_path
    elif source_file_key:
        source_path = f"/data/videos/{source_file_key}"
    else:
        source_path = None

    task = celery_slice_task.delay(
        episode_id=str(slice_task.episode_id),
        source_path=source_path,
        cutlist=cutlist,
        intervals=intervals_content,
        mode=slice_task.mode or "fast",
        dedupe_config=dedupe_config,
        task_id=str(slice_task.id),
        source_file_key=source_file_key,
        source_bucket=source_bucket or None,
        watermark_config=watermark_config,
        encoder=encoder,
        vert2horiz_config=vert2horiz_config,
        badges_config=badges_config,
        badge_default_width=badge_default_width,
        subtitle_config=subtitle_config,
    )
    slice_task.celery_task_id = task.id
    logger.info("Dispatched slice task %s via Celery (celery_task_id=%s)", slice_task.id, task.id)
    return True


# ──────────────────────────────────────────────
# API 端点
# ──────────────────────────────────────────────


@router.post("/slice/badge-upload")
async def upload_badge_image(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """上传角标图片（png/jpg/jpeg/webp/gif/bmp），存入 MinIO（raw-footage 桶 badge/ 前缀）。

    返回 file_key，前端将其纳入切片请求的 badges 列表。
    """
    # 注意：角标是图片，不能复用 validate_file_name（它按 ALLOWED_VIDEO_EXTENSIONS
    # 视频白名单校验，png/jpg 会被拒为 unsupported file type）。这里只做安全清洗
    # （取 basename、去路径穿越），扩展名白名单单独校验。
    import posixpath

    raw_name = file.filename or ""
    safe_name = posixpath.basename(raw_name.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="empty file name")

    # 仅允许图片类型
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        raise HTTPException(status_code=400, detail="角标仅支持图片文件（png/jpg/jpeg/webp/gif/bmp）")

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/badge_upload/{upload_id}_{safe_name}"
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

    # 角标图片存入 raw-footage 桶 badge/ 前缀
    file_key = f"badge/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW,
        file_key,
        local_path,
        content_type=file.content_type or "image/png",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="角标图片上传存储失败")

    return {
        "file_name": safe_name,
        "file_key": file_key,
        "file_size": size,
        "upload_id": upload_id,
    }


@router.post("/episodes/{episode_id}/slice/run", response_model=SliceRunResponse)
async def run_slice(
    episode_id: str,
    data: SliceRunRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger video slicing for an episode via Worker node or Celery（数据隔离）. """
    engine = _resolve_engine(data.engine)

    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # Get episode
    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 数据隔离
    await check_project_access_by_episode(db, episode, current_user)

    if data.video_path and not os.path.isfile(data.video_path):
        raise HTTPException(
            status_code=400,
            detail=f"video_path 指向的文件不存在: {data.video_path}",
        )
    source_file_key = episode.source_file_key
    source_bucket = settings.MINIO_BUCKET_RAW
    if not data.video_path and not source_file_key:
        raise HTTPException(
            status_code=400,
            detail="Episode has no source file. Upload a video first or provide video_path.",
        )

    # ── 成品重新剪辑：以某个切片输出（成品）为源，重新裁剪出一个新片段 ──
    if data.output_id:
        if data.video_path:
            raise HTTPException(
                status_code=400,
                detail="指定 output_id 重新剪辑时不能同时传 video_path",
            )
        try:
            out_id = uuid.UUID(data.output_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="output_id 格式不合法")

        out_res = await db.execute(select(SliceOutput).where(SliceOutput.id == out_id))
        output = out_res.scalar_one_or_none()
        if not output:
            raise HTTPException(status_code=404, detail="输出文件不存在")

        # 校验输出属于当前剧集
        out_task_res = await db.execute(select(SliceTask).where(SliceTask.id == output.task_id))
        out_task = out_task_res.scalar_one_or_none()
        if not out_task or str(out_task.episode_id) != str(eid):
            raise HTTPException(status_code=400, detail="输出文件不属于当前剧集")
        if not output.file_key:
            raise HTTPException(status_code=400, detail="输出文件缺少存储对象，无法重新剪辑")

        src_duration = output.duration or episode.duration or 0.0
        start = data.cut_start if data.cut_start is not None else 0.0
        end = data.cut_end if data.cut_end is not None else src_duration
        if start < 0 or end <= start:
            raise HTTPException(
                status_code=400,
                detail="剪辑区间不合法：需要 0 <= 开始时间 < 结束时间",
            )

        source_file_key = output.file_key
        source_bucket = settings.MINIO_BUCKET_SLICED
        cutlist = f"{format_time(start)} {format_time(end)} clip_01"
        intervals_content = ""
    else:
        # Generate cutlist from accepted clips
        clips_result = await db.execute(
            select(ClipCandidate).where(
                ClipCandidate.episode_id == eid,
                ClipCandidate.status == "accepted",
            )
        )
        accepted_clips = clips_result.scalars().all()

        if data.auto_accept_all:
            # 免审核一键切片：不要求审核通过，直接把所有候选片段纳入切片
            all_clips_result = await db.execute(
                select(ClipCandidate)
                .where(ClipCandidate.episode_id == eid)
                .order_by(ClipCandidate.clip_index.asc().nullslast())
            )
            all_clips = all_clips_result.scalars().all()
            if not all_clips:
                raise HTTPException(
                    status_code=400,
                    detail="当前没有候选片段，无法一键切片。请先运行 AI 智能选点。",
                )
            # 自动通过所有待审核片段，方便后续在切片任务/成品预览中看到关联关系
            for clip in all_clips:
                if clip.status == "pending":
                    clip.status = "accepted"
            await db.flush()
            accepted_clips = all_clips

        if not accepted_clips:
            raise HTTPException(
                status_code=400,
                detail="没有已通过的候选片段，无法生成切片。请先在片段审核中通过至少一个片段，或重新触发选点。",
            )
        cutlist = generate_cutlist(accepted_clips)

        # Generate intervals from enabled intervals
        intervals_result = await db.execute(
            select(DetectedInterval).where(
                DetectedInterval.episode_id == eid,
                DetectedInterval.enabled == True,
            )
        )
        enabled_intervals = intervals_result.scalars().all()
        intervals_content = generate_intervals_file(enabled_intervals)

    # 多人同时切片的全局并发闸门：超过 max_concurrent_tasks 上限直接拒绝。
    # 在创建任务记录前检查，running_count 为当前在飞任务数（不含本任务），
    # 保证“同时处理的切片任务数不超过 max_concurrent_tasks”。
    await _acquire_concurrency_slot(db)

    # Create slice task record
    slice_task = SliceTask(
        episode_id=eid,
        mode=data.mode,
        cutlist=cutlist,
        intervals=intervals_content,
        dedupe_config=data.dedupe_config,
        source_bucket=source_bucket,
        source_file_key=source_file_key,
        status="pending",
        progress=0.0,
    )
    db.add(slice_task)
    await db.flush()
    await db.refresh(slice_task)

    # 构造水印配置（开启后随任务下发给引擎）
    watermark_config = _build_watermark_config(data, episode)
    # 构造竖屏转横屏预处理配置（开启后随任务下发给引擎）
    vert2horiz_config = _build_vert2horiz_config(data)
    # 构造图片角标配置（开启后随任务下发给引擎）
    badges_config = _build_badges_config(data)
    # 构造字幕烧录配置：开启时优先复用选点阶段已生成的源视频字幕，否则回退到 ASR 生成
    subtitle_config = await _generate_subtitle_config(data, source_file_key, source_bucket, episode, db)
    # 持久化竖屏转横屏/角标/字幕配置，重试时保留
    slice_task.vert2horiz_config = vert2horiz_config
    slice_task.watermark_config = watermark_config
    slice_task.badges_config = badges_config
    slice_task.badge_default_width = data.badge_default_width or 0
    slice_task.subtitle_config = subtitle_config

    if engine == "worker":
        # 确保输出桶存在（全新部署时 sliced 桶可能未初始化）
        await ensure_bucket(settings.MINIO_BUCKET_SLICED)

        published = await _publish_to_worker(
            slice_task,
            episode,
            cutlist,
            intervals_content,
            source_file_key,
            data.dedupe_config,
            watermark_config,
            data.encoder,
            vert2horiz_config,
            badges_config,
            data.badge_default_width,
            source_bucket,
            subtitle_config,
        )

        if not published:
            # 如果发布失败，标记任务为失败
            slice_task.status = "failed"
            slice_task.error_message = "发布到 Worker 队列失败，请检查 Redis 连接"
            await db.flush()
            raise HTTPException(
                status_code=500,
                detail="发布切片任务到 Worker 队列失败，请检查 Redis 连接",
            )
    else:
        try:
            dispatched = await _dispatch_celery(
                slice_task,
                episode,
                cutlist,
                intervals_content,
                source_file_key,
                data.dedupe_config,
                data.video_path,
                watermark_config,
                data.encoder,
                vert2horiz_config,
                badges_config,
                data.badge_default_width,
                source_bucket,
                subtitle_config,
            )
        except Exception as e:
            logger.error("Celery 分发切片任务失败: %s", e)
            slice_task.status = "failed"
            slice_task.error_message = f"Celery 分发失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"Celery 分发切片任务失败: {e}")
        if not dispatched:
            slice_task.status = "failed"
            slice_task.error_message = "Celery 分发失败"
            await db.flush()
            raise HTTPException(status_code=500, detail="Celery 分发切片任务失败")

    # 切片启动时推进剧集状态，使工作流步骤条正确展示到“切片执行”
    if episode.status not in ("slicing", "completed"):
        episode.status = "slicing"
    await db.flush()

    slice_task.status = "running"
    slice_task.started_at = datetime.utcnow()
    await db.flush()

    return SliceRunResponse(
        task_id=str(slice_task.id),
        engine=engine,
        message=f"切片任务已发布到 {engine} 队列（模式: {data.mode}），正在处理中…",
    )


@router.get("/episodes/{episode_id}/slice/tasks", response_model=List[SliceTaskResponse])
async def list_slice_tasks(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all slice tasks for an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == eid))
    ).scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    await check_project_access_by_episode(db, episode, current_user)

    # 排除 detect_* 内部进度跟踪记录（区间检测复用了 slice_tasks 表）。
    result = await db.execute(
        select(SliceTask)
        .where(SliceTask.episode_id == eid)
        .where(_not_detect_task())
        .order_by(SliceTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_serialize_task(t) for t in tasks]


@router.get("/slice-tasks/{task_id}", response_model=SliceTaskResponse)
async def get_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a slice task's details and progress（数据隔离）. 

    同时从 Redis 获取 Worker 上报的实时进度，同步到数据库。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    # 从 Redis 获取 Worker 上报的实时状态
    try:
        redis_status = await get_task_redis_status(task_id)
        if redis_status:
            rs = redis_status
            if rs.get("status") == "completed" and task.status != "completed":
                task.status = "completed"
                task.progress = 100.0
                task.completed_at = datetime.utcnow()
            elif rs.get("status") == "failed" and task.status != "failed":
                task.status = "failed"
                task.error_message = rs.get("error", "Worker 报告错误")
                task.completed_at = datetime.utcnow()
            elif rs.get("status") == "cancelled" and task.status != "cancelled":
                task.status = "cancelled"
                task.error_message = rs.get("error", "任务已取消")
                task.completed_at = datetime.utcnow()
            elif rs.get("progress") is not None:
                task.progress = max(task.progress or 0, rs["progress"])
    except Exception as e:
        logger.warning("Failed to get Redis status for task %s: %s", task_id, e)

    await db.flush()
    return _serialize_task(task)


@router.get("/slice-tasks/{task_id}/outputs", response_model=List[SliceOutputResponse])
async def get_slice_outputs(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all outputs for a slice task（数据隔离）. """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # Verify task exists
    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    # Get outputs
    outputs_result = await db.execute(
        select(SliceOutput)
        .where(SliceOutput.task_id == tid)
        .order_by(SliceOutput.created_at.asc())
    )
    outputs = outputs_result.scalars().all()

    # Generate presigned URLs for each output
    result_list = []
    for output in outputs:
        url = None
        if output.file_key:
            url = await get_presigned_url("sliced", output.file_key, expires_seconds=3600)
        result_list.append(_serialize_output(output, url))

    return result_list


async def _verify_worker_token(
    task_id: str,
    x_worker_token: Optional[str],
) -> bool:
    """校验 Worker 回调/上传接口的 Token。"""
    if not x_worker_token:
        return False
    expected = await get_task_callback_token(task_id)
    if not expected:
        return False
    return secrets.compare_digest(expected, x_worker_token)


@worker_router.get("/slice-tasks/{task_id}/upload-url")
async def get_slice_upload_url(
    task_id: str,
    file_name: str,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 上传每个输出文件前，逐一申请精确绑定 object key 的 presigned PUT URL。

    修复"单 URL 拼文件名导致 MinIO 签名失效（403 SignatureDoesNotMatch）"问题。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    if not file_name or file_name != os.path.basename(file_name):
        raise HTTPException(status_code=400, detail="file_name 不合法")

    # 精确生成该文件的上传 URL（避免路径拼接导致签名失效）
    file_key = f"{_output_prefix(task)}{file_name}"
    upload_url = await get_presigned_upload_url(
        "sliced",
        file_key,
        expires_seconds=7200,
    )
    if not upload_url:
        raise HTTPException(status_code=500, detail="生成上传 URL 失败")

    return {"upload_url": upload_url, "file_key": file_key}


@worker_router.post("/slice-tasks/{task_id}/callback")
async def slice_task_callback(
    task_id: str,
    data: SliceTaskCallback,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 完成任务后的回调。

    Worker 在处理完切片任务后，调用此接口通知后端结果。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权：防止伪造任务完成/失败回调
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    now = datetime.utcnow()

    if data.status == "completed":
        # ── 幂等保护 ──
        # 任务可能因 PEL 重新认领 / 回调重发被重复上报 completed。
        # 若任务已处于终态且输出已落库，直接返回，避免切片输出重复添加。
        if task.status == "completed":
            return {"ok": True, "duplicate": True}
        if task.status in ("failed", "cancelled") and task.output_count and task.output_count > 0:
            return {"ok": True, "duplicate": True}

        # 记录执行该任务的节点（用于切片任务列表展示"由哪个节点完成"）
        if data.node_id:
            task.node_id = data.node_id

        # 按接受的候选片段顺序映射 clip_id（文件名 clip_XX.mp4 对应片段顺序）
        clip_result = await db.execute(
            select(ClipCandidate)
            .where(
                ClipCandidate.episode_id == task.episode_id,
                ClipCandidate.status == "accepted",
            )
            .order_by(ClipCandidate.clip_index.asc())
        )
        accepted_clips = clip_result.scalars().all()

        # 按文件名中的序号或输出顺序关联 clip_id
        clip_index = 0
        for out in data.outputs:
            fname = out.get("file_name", "")
            file_key = out.get("file_key", "")
            clip_id = None
            matched = False
            # 尝试从文件名 clip_{index}.mp4 解析
            base = os.path.splitext(os.path.basename(fname))[0]
            if base.startswith("clip_"):
                try:
                    idx = int(base.split("_")[1])
                    if 1 <= idx <= len(accepted_clips):
                        clip_id = accepted_clips[idx - 1].id
                        matched = True
                except (ValueError, IndexError):
                    pass
            if not matched:
                # 兜底：按输出顺序关联
                if clip_index < len(accepted_clips):
                    clip_id = accepted_clips[clip_index].id
                clip_index += 1

            # 同一 file_key 已存在则跳过，避免重复回调/重跑时输出记录叠加
            if file_key:
                existing_out = await db.execute(
                    select(SliceOutput).where(
                        SliceOutput.task_id == tid,
                        SliceOutput.file_key == file_key,
                    )
                )
                if existing_out.scalar_one_or_none():
                    continue

            db_output = SliceOutput(
                task_id=tid,
                clip_id=clip_id,
                file_key=file_key,
                file_name=fname,
                duration=out.get("duration"),
                file_size=out.get("file_size"),
                created_at=now,
            )
            db.add(db_output)

        task.status = "completed"
        task.progress = 100.0
        task.output_count = data.output_count or len(data.outputs)
        task.completed_at = now
        task.error_message = None
        logger.info("Slice task %s completed with %d outputs", task_id, task.output_count)

        # 推进剧集状态：所有切片任务完成后置为 completed（而非仅依赖最近一条）
        await _refresh_episode_status(db, task.episode_id)

    elif data.status == "progress":
        # 进度更新（真实 ffmpeg 进度）
        if data.progress is not None:
            task.progress = max(task.progress or 0, data.progress)

    else:  # failed
        task.status = "failed"
        if data.node_id:
            task.node_id = data.node_id
        task.error_message = (data.error or "Worker 报告错误")[:2000]
        task.completed_at = now
        logger.warning("Slice task %s failed: %s", task_id, task.error_message)

        # 任务失败也刷新剧集状态（保证不是"最近一条未完成就永远切片中"）
        await _refresh_episode_status(db, task.episode_id)

    await db.flush()
    return {"ok": True}


@worker_router.post("/slice-tasks/{task_id}/progress")
async def update_slice_progress(
    task_id: str,
    data: dict,
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Worker 实时进度上报端点。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    # 鉴权
    if not await _verify_worker_token(task_id, x_worker_token):
        raise HTTPException(status_code=401, detail="无效的 Worker Token")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    progress = data.get("progress")
    if progress is not None:
        task.progress = max(task.progress or 0, float(progress))

    await db.flush()
    return {"ok": True}


@router.post("/slice-tasks/{task_id}/retry", response_model=SliceRunResponse)
async def retry_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed or cancelled slice task by re-dispatching it to Worker（数据隔离）. """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    if task.status not in ("failed", "cancelled", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry task with status '{task.status}'",
        )

    episode = await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ep = episode.scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")

    source_file_key = task.source_file_key or ep.source_file_key
    source_bucket = task.source_bucket or settings.MINIO_BUCKET_RAW
    if not source_file_key:
        raise HTTPException(status_code=400, detail="Episode has no source file")

    engine = _resolve_engine(None)  # 沿用默认引擎

    new_task = SliceTask(
        episode_id=task.episode_id,
        mode=task.mode,
        cutlist=task.cutlist,
        intervals=task.intervals,
        dedupe_config=task.dedupe_config,
        # 重试时保留原任务的源与水印/角标配置
        source_bucket=source_bucket,
        source_file_key=source_file_key,
        watermark_config=task.watermark_config,
        badges_config=task.badges_config,
        vert2horiz_config=task.vert2horiz_config,
        subtitle_config=task.subtitle_config,
        status="pending",
        progress=0.0,
    )

    # 全局并发闸门：重试同样受 max_concurrent_tasks 限制，避免堆积
    await _acquire_concurrency_slot(db)

    db.add(new_task)
    await db.flush()
    await db.refresh(new_task)

    if engine == "worker":
        await ensure_bucket(settings.MINIO_BUCKET_SLICED)
        published = await _publish_to_worker(
            new_task,
            ep,
            task.cutlist or "",
            task.intervals or "",
            source_file_key,
            task.dedupe_config,
            task.watermark_config,
            None,
            task.vert2horiz_config,
            task.badges_config,
            task.badge_default_width or 0,
            source_bucket,
            task.subtitle_config,
        )

        if not published:
            new_task.status = "failed"
            new_task.error_message = "发布到 Worker 队列失败"
            await db.flush()
            raise HTTPException(
                status_code=500,
                detail="发布切片任务到 Worker 队列失败",
            )
    else:
        try:
            await _dispatch_celery(
                new_task,
                ep,
                task.cutlist or "",
                task.intervals or "",
                source_file_key,
                task.dedupe_config,
                None,
                task.watermark_config,
                None,
                task.vert2horiz_config,
                task.badges_config,
                task.badge_default_width or 0,
                source_bucket,
                task.subtitle_config,
            )
        except Exception as e:
            new_task.status = "failed"
            new_task.error_message = f"Celery 分发失败: {e}"
            await db.flush()
            raise HTTPException(status_code=500, detail=f"Celery 分发切片任务失败: {e}")

    new_task.status = "running"
    new_task.started_at = datetime.utcnow()
    if ep.status not in ("slicing", "completed"):
        ep.status = "slicing"
    await db.flush()

    return SliceRunResponse(
        task_id=str(new_task.id),
        engine=engine,
        message="切片任务已重新发布到 Worker 队列",
    )


@router.post("/slice-tasks/{task_id}/cancel", response_model=dict)
async def cancel_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running slice task（数据隔离）. 

    Worker 模式下，取消操作会同时更新数据库状态并写入 Redis 任务 Hash，
    Worker 端通过轮询任务 Hash 感知取消并强杀 ffmpeg 进程。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status '{task.status}'",
        )

    task.status = "cancelled"
    await db.flush()

    # 写入 Redis，通知 Worker 端强杀任务
    await mark_task_cancelled(task_id)

    return {"message": "任务已取消（Worker 端将收到取消信号并终止 ffmpeg）", "task_id": task_id}


@router.delete("/slice-tasks/{task_id}", status_code=200)
async def delete_slice_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """删除切片任务，同时删除其输出文件（MinIO 临时资源，数据隔离）。

    - 若任务正在运行/排队，先取消（写入 Redis 取消标记，Worker 端会强杀 ffmpeg）
    - 删除该任务在 MinIO sliced 桶中的全部输出对象
    - 级联删除数据库中的 SliceOutput / Publication 等关联记录
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(SliceTask).where(SliceTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Slice task not found")

    # 数据隔离
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)

    # 正在运行/排队中的任务先取消，避免 Worker 还在写入
    if task.status in ("pending", "running"):
        task.status = "cancelled"
        await mark_task_cancelled(task_id)
        await db.flush()

    # 删除该任务在 MinIO 中的输出文件（slices/{episode}/{task}/ 前缀）
    prefix = _output_prefix(task)
    try:
        objs = await list_files(settings.MINIO_BUCKET_SLICED, prefix=prefix)
        for obj in objs:
            await delete_file(settings.MINIO_BUCKET_SLICED, obj["key"])
        if objs:
            logger.info("Deleted %d output files for slice task %s from MinIO", len(objs), task_id)
    except Exception as e:
        logger.warning("Failed to delete MinIO outputs for task %s: %s", task_id, e)

    # 删除数据库记录（级联删除 SliceOutput / Publication / PublishTask）
    episode_id_for_refresh = task.episode_id
    await db.delete(task)
    await db.flush()

    # 删除后刷新剧集状态（避免删除了任务仍停留在 slicing）
    await _refresh_episode_status(db, episode_id_for_refresh)
    await db.flush()

    return {"message": "任务已删除，相关输出文件已清理", "task_id": task_id}
