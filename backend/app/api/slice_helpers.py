"""切片共享辅助模块（Phase 1 上帝类拆分）。

从原「上帝类」api/slice.py 拆出的「Pydantic 模型 + 引擎封装 + 序列化 + Worker/Celery 分发」
辅助层，供业务路由（slice.py 的 router）与 Worker 回调路由（worker_router）复用，
把「业务路由 / Worker 回调 / Pydantic 模型 / 引擎封装」四类关注点分离。

本模块不定义任何路由，仅提供纯函数与数据模型。
"""
import json
import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import (
    Episode,
    SliceTask,
    SliceOutput,
    ClipCandidate,
    DetectedInterval,
    SystemConfig,
    AutoClipProject,
)
from app.services.autoclip_service import generate_subtitle
from app.utils.helpers import utc_iso, generate_cutlist, generate_intervals_file, format_time
from app.services.minio_service import (
    get_presigned_url,
    get_presigned_upload_url,
    ensure_bucket,
    list_files,
    delete_file,
    download_file,
    upload_file_from_path,
)
from app.services.redis_stream import (
    publish_slice_task,
    get_task_redis_status,
    store_task_callback_token,
    get_task_callback_token,
    mark_task_cancelled,
    get_redis,
)

logger = logging.getLogger(__name__)

# 允许的引擎类型
ALLOWED_ENGINES = ("celery", "worker")


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class BadgeItem(BaseModel):
    """图片角标项：在切片成品上叠加一个角标。

    - file_key：上传到 MinIO 的角标图片 key
    - position：七位位置（top-left/top-center/top-right/left/bottom-left/bottom-center/bottom-right）
    - width：角标宽度（px，可选；0/空=用默认尺寸或保持原图）
    - offset：到视频边缘的偏移量（px，可选，默认 10）
    - opacity：角标透明度（0~1，可选，默认 1 不透明）
    """
    file_key: str = ""
    position: str = "top-left"
    width: Optional[int] = None
    offset: Optional[int] = None
    opacity: Optional[float] = None


class TextOverlayItem(BaseModel):
    """固定文字角标项：在成品视频指定位置叠加一段固定文字。

    - text：文字内容（必填）
    - position：七位位置（top-left/top-center/top-right/left/bottom-left/bottom-center/bottom-right）
    - font_size：字号（px，可选，默认 36）
    - color：字体颜色（CSS #RRGGBB，可选，默认白）
    - border_color：描边颜色（CSS #RRGGBB，可选，默认黑）
    - vertical：是否竖排（最左侧常用，可选，默认 False）
    - offset：到视频边缘的偏移量（px，可选，默认 10）
    """
    text: str = ""
    position: str = "bottom-left"
    font_size: Optional[int] = None
    color: Optional[str] = None
    border_color: Optional[str] = None
    vertical: Optional[bool] = None
    offset: Optional[int] = None


class SliceRunRequest(BaseModel):
    mode: str = "fast"
    dedupe_config: Optional[dict] = None
    # 多视频号素材去重：需要生成的素材变体数（null/1=不生成，零侵入；>1=切片后自动派生 N 个去重版本）
    variant_count: Optional[int] = None
    video_path: Optional[str] = None
    engine: Optional[str] = None  # "celery" | "worker"，默认取配置 SLICE_ENGINE
    # 免审核一键切片：为 True 时自动把所有候选片段（含 pending）纳入切片，
    # 不再要求存在 status=accepted 的片段
    auto_accept_all: bool = False
    # 快速转换：为 True 时跳过 AI 选点与区间检测，直接把整段源视频作为单个
    # 片段（0 ~ 源时长），应用下方切片配置（竖屏转横屏/水印/角标/字幕/固定文字等）
    # 做一次整片转换输出，无需候选片段
    no_cut: bool = False
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
    # 水印形态/运动样式（scroll 横滚 / float 斜漂 / wave 波浪 / bounce 折返 /
    # breath 呼吸 / blink 闪现，默认 scroll）。决定水印位置+运动轨迹+特效。
    watermark_style: str = "scroll"
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
    # 动态模式：人脸舒适区边距比例（占人脸高度，默认 0.30）。人脸头像大部分
    # 仍在画面内时保持窗口不动，抑制频繁移动造成的抖动；越大越稳、越小越跟手。
    vert2horiz_face_margin: Optional[float] = None
    # ── ASR 字幕烧录 ──
    # 开启后对源视频做 ASR 语音识别生成字幕，并烧录到每个切片成品上
    subtitle_enabled: bool = False
    # 字幕字号（相对输出视频高度的比例，默认 0.20→FontSize 20，约占画面 5%；不传用引擎默认值）。
    # 用户可调大以让字幕更清晰易读，例如 0.10~0.30。
    subtitle_font_ratio: Optional[float] = None
    # 字幕字间距（ASS Spacing 像素，默认 0 更紧凑；负值/调小让字幕文字更紧凑，调大则字距变宽）。
    # 不传用引擎默认值 SUBTITLE_SPACING。
    subtitle_spacing: Optional[int] = None
    # 字幕字体粗细（ASS Bold：0=不加粗，-1 或 1=加粗，默认 0 不加粗）。加粗让字幕文字更醒目。
    subtitle_bold: Optional[int] = None
    # 字幕对齐源字幕打码区域开关（默认 True 开启）：开启源字幕打码并检测到字幕区域时，
    # 把 ASR 字幕默认位置对齐到打码区域（与被打掉的源字幕位置重合）；关闭则用默认底边距。
    subtitle_align_mask: bool = True
    # 字幕样式（default=白字黑边+半透明黑底；custom=自定义字体色/边框色且无底色）。
    # 仅在 subtitle_enabled 开启且为 custom 时生效。
    subtitle_style: Optional[str] = None
    # 上传的字幕文件（MinIO key，通过 /slice/subtitle-upload 上传）。
    # 提供后优先直接使用该字幕文件（跳过 ASR 识别 / 选点字幕复用），烧录到成品。
    subtitle_file_key: Optional[str] = None
    # 自定义字幕样式的字体颜色（CSS 十六进制 #RRGGBB）
    subtitle_color: Optional[str] = None
    # 自定义字幕样式的边框颜色（CSS 十六进制 #RRGGBB）
    subtitle_border_color: Optional[str] = None
    # ── 源视频字幕打码（去片源自带字幕，独立开关）──
    # 开启后把片源自带字幕打码（固定底部横带 + SRT 时间轴驱动）。
    # 与 ASR 字幕烧录相互独立，可单独开启。
    subtitle_mask_enabled: bool = False
    # 打码样式：delogo（去水印，推荐，默认）/ mosaic（马赛克）/ blur（模糊）/ gblur（高斯模糊）/ fill（纯色块）
    subtitle_mask_style: Optional[str] = None
    # 打码预设（三档，推荐用预设替代 temporal/spatial 两个独立开关，降低配置出错率）：
    #   auto=自动（SRT 动态窗口优先，兼顾效果与速度，推荐默认）
    #   fine=精细（帧级 + 空间子区域，最精确、更慢）
    #   quick=快速（固定区域全程打码，最快）
    # 传了 preset 时忽略下方 temporal/spatial 字段；未传则回退到显式 temporal/spatial（向后兼容）。
    subtitle_mask_preset: Optional[str] = None
    # 精细化（帧级检测）开关：开启后只在字幕/水印实际出现的时段打码，
    # 画面其余时间零改动（处理较慢，但更精细）；关闭则用 SRT 时间轴或全程打码（快）。
    subtitle_mask_temporal: bool = False
    # 仅字幕显示区域打码（空间精细化）开关：需在 subtitle_mask_temporal 开启后才能开启。
    # 开启后，在每个字幕出现时段内只对字幕文字实际占用的那部分横向区域打码，
    # 而不是把整条横带都盖住（更精细，处理更慢）。
    subtitle_mask_spatial: bool = False
    # 打码区域（相对输出视频宽高比例，可选，默认宽度 0.9 / 高度 0.12）
    subtitle_mask_width_ratio: Optional[float] = None
    subtitle_mask_height_ratio: Optional[float] = None
    # 打码区域距底边比例（可选，默认 0.02）
    subtitle_mask_bottom_ratio: Optional[float] = None
    # 打码时间轴整体偏移（秒，可选，默认 0）。用于校正 ASR 字幕时间与画面实际字幕的偏差：
    # 画面字幕比 SRT 晚出现（字幕滞后）时传正值延后打码；早出现时传负值提前打码。
    subtitle_mask_srt_offset: Optional[float] = None
    # ── 恒定水印/角标打码（打掉片源固定水印，独立开关，与字幕打码互不干扰）──
    watermark_mask_enabled: bool = False
    # 水印打码样式：delogo（去水印，推荐，默认）/ mosaic（马赛克）/ blur（模糊）/ gblur（高斯模糊）/ fill（纯色块）
    watermark_mask_style: Optional[str] = None
    # 水印打码区域（相对输出视频宽高比例，可选；自动检测失败时回退用）
    watermark_mask_width_ratio: Optional[float] = None
    watermark_mask_height_ratio: Optional[float] = None
    # 水印区域距底边比例（默认 0.02）或距顶边比例（bottom_ratio 与 top_ratio 二选一，
    # 传 top_ratio 则区域按顶部对齐，用于顶部角标/台标）
    watermark_mask_bottom_ratio: Optional[float] = None
    watermark_mask_top_ratio: Optional[float] = None
    # 手动指定水印区域绝对坐标（可选，x/y/width/height 全填时跳过自动检测，直接使用）
    watermark_mask_x: Optional[int] = None
    watermark_mask_y: Optional[int] = None
    watermark_mask_width: Optional[int] = None
    watermark_mask_height: Optional[int] = None
    # ── 固定文字角标（文字版角标，无需上传图片）──
    # 在成品视频指定位置叠加固定文字（最左侧/左下角/右上角等），全程覆盖。
    # 每个元素：text（内容）、position（left/bottom-left/top-right 等七位）、
    # font_size（字号px）、color（字体色#RRGGBB）、border_color（描边色）、
    # vertical（是否竖排，最左侧常用）、offset（边缘偏移px）。
    text_overlays: Optional[List[TextOverlayItem]] = None


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
    # ── 该任务实际应用的配置（用于历史列表悬停展示） ──
    dedupe_config: Optional[dict] = None
    watermark_config: Optional[dict] = None
    badges_config: Optional[list] = None
    badge_default_width: Optional[int] = None
    vert2horiz_config: Optional[dict] = None
    subtitle_config: Optional[dict] = None
    subtitle_align_mask: Optional[bool] = None
    subtitle_mask_config: Optional[dict] = None
    watermark_mask_config: Optional[dict] = None
    text_overlays_config: Optional[list] = None

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


class UserSliceConfigRequest(BaseModel):
    slice_config: dict = {}


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
        # 该任务实际应用的配置（用于历史列表悬停展示）
        "dedupe_config": task.dedupe_config,
        "watermark_config": task.watermark_config,
        "badges_config": task.badges_config,
        "badge_default_width": task.badge_default_width,
        "vert2horiz_config": task.vert2horiz_config,
        "subtitle_config": task.subtitle_config,
        "subtitle_align_mask": task.subtitle_align_mask,
        "subtitle_mask_config": task.subtitle_mask_config,
        "watermark_mask_config": task.watermark_mask_config,
        "text_overlays_config": task.text_overlays_config,
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


def _ffprobe_duration(path: str) -> float:
    """用 ffprobe 探测本地视频时长（秒），失败返回 0.0。"""
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


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
        # 形态/运动样式：透传给引擎 build_watermark_filter（未指定保持默认 scroll）
        "style": (data.watermark_style or "scroll").lower(),
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
    if data.vert2horiz_face_margin is not None:
        # 人脸舒适区边距比例：0=关闭该层抗抖（完全跟手），否则限制在合理范围
        cfg["face_margin"] = max(0.0, min(0.8, float(data.vert2horiz_face_margin)))
    return cfg


def _build_badges_config(data: SliceRunRequest) -> Optional[list]:
    """构造图片角标配置列表（引擎 --badges 期望的 JSON 数组）。

    仅保留合法角标；每个角标含 file_key（MinIO 对象 key）、position（位置）、
    width（可选宽度）、offset（可选边缘偏移）、opacity（可选透明度）。
    位置限定为七位：左上/中上/右上/最左侧/左下/中下/右下。
    """
    if not data.badges:
        return None
    # 位置限定：左上/中上/右上/最左侧/左下/中下/右下。
    allowed = {
        "top-left", "top-center", "top-right", "left",
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


def _build_text_overlays_config(data: SliceRunRequest) -> Optional[list]:
    """构造固定文字角标配置列表（引擎 --text-overlays 期望的 JSON 数组）。

    仅保留含文字内容的条目；位置限定为七位（最左侧/左上/中上/右上/左下/中下/右下）。
    """
    if not data.text_overlays:
        return None
    allowed = {
        "top-left", "top-center", "top-right", "left",
        "bottom-left", "bottom-center", "bottom-right",
    }
    result = []
    for t in data.text_overlays:
        if not t.text or not t.text.strip():
            continue
        position = (t.position or "bottom-left").lower()
        if position not in allowed:
            position = "bottom-left"
        item = {
            "text": t.text.strip(),
            "position": position,
        }
        if t.font_size is not None:
            item["font_size"] = max(12, min(200, int(t.font_size)))
        if t.color:
            item["color"] = t.color
        if t.border_color:
            item["border_color"] = t.border_color
        if t.vertical is not None:
            item["vertical"] = bool(t.vertical)
        if t.offset is not None:
            item["offset"] = max(0, int(t.offset))
        result.append(item)
    return result if result else None


def _build_subtitle_mask_config(data: SliceRunRequest, source_srt: Optional[str] = None) -> Optional[dict]:
    """构造源视频字幕打码配置（引擎 --subtitle-mask 期望的 JSON）。

    仅当 subtitle_mask_enabled 开启时返回非空 dict；区域参数未填则用引擎默认值。
    source_srt 为打码时间轴（源视频字幕/ASR 台词）内容，与 ASR 字幕烧录开关相互独立：
    即使未开启字幕烧录，只要开启打码也会解析源 SRT 用于对齐打码时间段。
    """
    if not data.subtitle_mask_enabled:
        return None
    cfg: dict = {"enabled": True}
    style = (data.subtitle_mask_style or "delogo").lower()
    if style not in ("delogo", "mosaic", "blur", "gblur", "fill"):
        style = "delogo"
    cfg["style"] = style
    # 打码预设（三档）优先：auto/fine/quick 收敛 temporal/spatial 两个开关，降低配置出错率。
    preset = (getattr(data, "subtitle_mask_preset", None) or "").strip().lower()
    if preset in ("auto", "fine", "quick", "自动", "精细", "快速"):
        cfg["preset"] = preset
    else:
        # 未传预设时回退到显式 temporal/spatial（向后兼容）。
        # 精细化（帧级检测）：只在字幕/水印实际出现的时段打码。
        cfg["temporal"] = bool(getattr(data, "subtitle_mask_temporal", False))
        # 仅字幕显示区域打码（空间精细化）：只在字幕文字实际占用的横向子区域打码。
        # 需 temporal 开启才生效（引擎侧仅在 temporal 模式下启用该能力）。
        cfg["spatial"] = bool(getattr(data, "subtitle_mask_spatial", False))
    if data.subtitle_mask_width_ratio is not None:
        cfg["width_ratio"] = max(0.1, min(1.0, float(data.subtitle_mask_width_ratio)))
    if data.subtitle_mask_height_ratio is not None:
        cfg["height_ratio"] = max(0.02, min(0.5, float(data.subtitle_mask_height_ratio)))
    if data.subtitle_mask_bottom_ratio is not None:
        cfg["bottom_ratio"] = max(0.0, min(0.5, float(data.subtitle_mask_bottom_ratio)))
    # 打码时间轴整体偏移（秒）：校正 ASR 字幕时间与画面字幕偏差（正值延后、负值提前）
    if getattr(data, "subtitle_mask_srt_offset", None) is not None:
        cfg["srt_offset"] = float(data.subtitle_mask_srt_offset)
    # 独立携带打码时间轴 SRT（与字幕烧录无关），供 Worker/Celery 写入本地文件后透传引擎
    if source_srt and source_srt.strip():
        cfg["srt"] = source_srt
    return cfg


def _build_watermark_mask_config(data: SliceRunRequest) -> Optional[dict]:
    """构造恒定水印/角标打码配置（引擎 --watermark-mask 期望的 JSON）。

    仅当 watermark_mask_enabled 开启时返回非空 dict。区域参数未填则引擎自动检测，
    检测失败回退底部水印带（或 top_ratio 指定的顶部区域）。
    """
    if not getattr(data, "watermark_mask_enabled", False):
        return None
    cfg: dict = {"enabled": True}
    style = (data.watermark_mask_style or "delogo").lower()
    if style not in ("delogo", "mosaic", "blur", "gblur", "fill"):
        style = "delogo"
    cfg["style"] = style
    if data.watermark_mask_width_ratio is not None:
        cfg["width_ratio"] = max(0.1, min(1.0, float(data.watermark_mask_width_ratio)))
    if data.watermark_mask_height_ratio is not None:
        cfg["height_ratio"] = max(0.02, min(0.5, float(data.watermark_mask_height_ratio)))
    if data.watermark_mask_bottom_ratio is not None:
        cfg["bottom_ratio"] = max(0.0, min(0.5, float(data.watermark_mask_bottom_ratio)))
    if data.watermark_mask_top_ratio is not None:
        cfg["top_ratio"] = max(0.0, min(0.5, float(data.watermark_mask_top_ratio)))
    # 手动绝对坐标：x/y/width/height 全填时引擎跳过自动检测直接使用
    if (data.watermark_mask_x is not None and data.watermark_mask_y is not None
            and data.watermark_mask_width is not None and data.watermark_mask_height is not None):
        cfg["x"] = int(data.watermark_mask_x)
        cfg["y"] = int(data.watermark_mask_y)
        cfg["width"] = int(data.watermark_mask_width)
        cfg["height"] = int(data.watermark_mask_height)
    return cfg


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
    """把用户设置的字幕样式（字号/字间距/自定义字体色/边框色）写入字幕配置，随任务下发给引擎。"""
    if data.subtitle_font_ratio is not None and data.subtitle_font_ratio > 0:
        cfg["font_ratio"] = round(float(data.subtitle_font_ratio), 4)
    if data.subtitle_spacing is not None:
        cfg["spacing"] = int(data.subtitle_spacing)
    if data.subtitle_bold is not None:
        cfg["bold"] = int(data.subtitle_bold)
    if data.subtitle_style:
        cfg["style"] = data.subtitle_style
    if data.subtitle_color:
        cfg["font_color"] = data.subtitle_color
    if data.subtitle_border_color:
        cfg["border_color"] = data.subtitle_border_color
    return cfg


async def _read_uploaded_subtitle(file_key: str) -> Optional[dict]:
    """读取用户上传的字幕文件内容（MinIO raw-footage 桶）。

    上传字幕通过 /slice/subtitle-upload 接口得到 file_key，这里下载其内容作为
    烧录时间轴，优先于 ASR 识别与选点字幕复用。返回 {"enabled": True, "srt": str}；
    读不到返回 None。
    """
    if not file_key:
        return None
    data = await download_file(settings.MINIO_BUCKET_RAW, file_key)
    if not data:
        logger.warning("读取上传字幕失败: %s", file_key)
        return None
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = data.decode("utf-8", errors="replace")
    if not content.strip():
        logger.warning("上传字幕内容为空: %s", file_key)
        return None
    # VTT 兼容：去掉 WEBVTT 头与内联时间戳，转成 SRT 时间轴格式
    ext = os.path.splitext(file_key)[1].lower()
    if ext == ".vtt":
        content = _vtt_to_srt(content)
    if not content.strip():
        logger.warning("上传字幕解析后为空: %s", file_key)
        return None
    logger.info("使用用户上传的字幕文件（%s），跳过 ASR 识别", file_key)
    return {"enabled": True, "srt": content}


def _vtt_to_srt(content: str) -> str:
    """把 WebVTT 文本转成 SRT 文本（时间戳分隔符与序号）。

    仅做最小转换：去 WEBVTT 头、时间戳 '.' -> ','、补序号。
    无法解析的时间块跳过。
    """
    lines = content.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    index = 0
    i = 0
    # 跳过 WEBVTT 头及 NOTE/STYLE 元数据块
    while i < len(lines):
        line = lines[i].strip()
        if line.upper().startswith("WEBVTT"):
            i += 1
            continue
        if line.upper().startswith(("NOTE", "STYLE", "REGION")):
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                i += 1
            i += 1
            continue
        break
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # 时间行可能带 cue settings（如 align:start）
        if "-->" in line:
            time_line = line
        else:
            # 非时间行：可能是 cue id，也可能是正文。先看下一行是否时间行
            if i + 1 < len(lines) and "-->" in lines[i + 1]:
                i += 1
                time_line = lines[i].strip()
            else:
                i += 1
                continue
        start_end = time_line.split("-->", 1)
        if len(start_end) != 2:
            i += 1
            continue
        start = start_end[0].strip()
        end = start_end[1].strip().split(" ")[0]  # 去掉 align 等 cue settings
        # 时间戳 '.' -> ','
        start = start.replace(".", ",")
        end = end.replace(".", ",")
        # 收集正文（直到空行）
        texts: List[str] = []
        i += 1
        while i < len(lines) and lines[i].strip() != "":
            texts.append(lines[i].strip())
            i += 1
        index += 1
        out.append(f"{index}")
        out.append(f"{start} --> {end}")
        out.append("\n".join(texts))
        out.append("")
    return "\n".join(out).strip()


async def _resolve_source_subtitle_srt(
    data: SliceRunRequest,
    source_file_key: Optional[str],
    source_bucket: str,
    episode: Optional[Episode] = None,
    db: Optional[AsyncSession] = None,
) -> Optional[str]:
    """解析源视频的字幕 SRT 内容（时间轴），供 ASR 字幕烧录与源字幕打码共用。

    优先复用选点阶段已生成的源视频字幕（whisper/aliyun），否则调用 autoclip ASR 生成
    （带缓存）。返回 SRT 文本；拿不到返回 None。
    """
    if not source_file_key:
        return None
    # 1) 优先复用选点阶段 whisper/aliyun 已翻译好的字幕（仅常规切片；以切片成品为源的
    #    重新剪辑（output_id）时间轴从 0 开始、与原始字幕不同，不适用，走回退）
    if not data.output_id and episode is not None and db is not None:
        reused = await _read_existing_subtitle(episode, db)
        if reused is not None and reused.get("srt"):
            return reused["srt"]
    # 2) 回退：调用 autoclip ASR 生成（复用 ASR 缓存）
    source_url = await get_presigned_url(source_bucket, source_file_key, expires_seconds=7200)
    if not source_url:
        logger.warning("生成源视频下载 URL 失败，无法解析源字幕时间轴")
        return None
    asr_method = None
    if db is not None:
        try:
            cfg_row = (await db.execute(select(SystemConfig).where(SystemConfig.key == "asr_method"))).scalar_one_or_none()
            if cfg_row is not None and cfg_row.value:
                asr_method = str(cfg_row.value)
        except Exception:
            asr_method = None
    result = await generate_subtitle(source_url, asr_method=asr_method)
    if not result or not result.get("srt") or not result["srt"].strip():
        logger.warning("ASR 字幕生成结果为空（视频可能无语音或转写失败）")
        return None
    return result["srt"]


def _generate_subtitle_config(
    data: SliceRunRequest,
    source_srt: Optional[str],
) -> Optional[dict]:
    """构造字幕烧录配置（引擎 --subtitle 期望的 SRT）。

    返回 {"enabled": True, "srt": "..."}；未开启或 SRT 为空返回 None。
    上传了字幕文件（subtitle_file_key）时视为已开启字幕，直接应用上传的字幕。
    """
    if not data.subtitle_enabled and not data.subtitle_file_key:
        return None
    if not source_srt or not source_srt.strip():
        logger.warning("字幕已开启，但源字幕时间轴为空，跳过字幕烧录")
        return None
    return _with_subtitle_options({"enabled": True, "srt": source_srt}, data)


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
    text_overlays_config: Optional[list] = None,
    subtitle_mask_config: Optional[dict] = None,
    watermark_mask_config: Optional[dict] = None,
    subtitle_align_mask: bool = True,
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

    # 判断本任务是否需要字幕烧录能力（ASR 字幕烧录 或 源字幕打码）。
    # 需要字幕能力的任务路由到独立的 slice:tasks:subtitle 流，仅 163 Linux worker
    # （ffmpeg 带 libass）消费；Mac worker 只读 high/normal/low，永不领取，
    # 避免其 ffmpeg 缺 libass 导致字幕烧录失败（退出码 1）。
    def _subtitle_enabled(cfg) -> bool:
        return bool(cfg) and bool(getattr(cfg, "get", lambda k: None)("enabled"))

    needs_subtitle = _subtitle_enabled(subtitle_config) or _subtitle_enabled(subtitle_mask_config)
    queue = "subtitle" if needs_subtitle else "normal"

    # 回调地址使用可配置的基础地址（支持远程 Worker 通过公网/内网访问）
    callback_base = settings.WORKER_CALLBACK_BASE_URL.rstrip("/")
    callback_url = f"{callback_base}/api/slice-tasks/{slice_task.id}/callback"

    # 构造 Worker 任务 payload（匹配 Go Worker 的 SliceTask 结构体）
    task_payload = {
        "task_id": str(slice_task.id),
        "episode_id": str(slice_task.episode_id),
        "priority": queue,
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
        # 固定文字角标（可选，Go Worker 直接透传给引擎 --text-overlays）
        "text_overlays": text_overlays_config,
        # 源视频字幕打码（可选，Go Worker 透传给引擎 --subtitle-mask）
        "subtitle_mask": subtitle_mask_config,
        # 字幕对齐源字幕打码区域（默认开启，Go Worker 透传给引擎 --subtitle-align-mask）
        "subtitle_align_mask": subtitle_align_mask,
        # 恒定水印/角标打码（可选，Go Worker 透传给引擎 --watermark-mask）
        "watermark_mask": watermark_mask_config,
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

    # 发布到 Redis Stream（字幕任务走独立 subtitle 流，仅 163 Linux worker 消费）
    msg_id = await publish_slice_task(task_payload, queue)
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
    text_overlays_config: Optional[list] = None,
    subtitle_mask_config: Optional[dict] = None,
    watermark_mask_config: Optional[dict] = None,
    subtitle_align_mask: bool = True,
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
        text_overlays_config=text_overlays_config,
        subtitle_mask_config=subtitle_mask_config,
        watermark_mask_config=watermark_mask_config,
        subtitle_align_mask=subtitle_align_mask,
    )
    slice_task.celery_task_id = task.id
    logger.info("Dispatched slice task %s via Celery (celery_task_id=%s)", slice_task.id, task.id)
    return True


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
