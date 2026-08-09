"""短片制作 API（v6）：Seedance 提示词生成 + 生成历史。

工作流：
1. 用户输入短剧文案（对白/旁白原文）→ 调用 autoclip 的
   POST /api/v1/prompt/generate 生成 Seedance 提示词（复用 autoclip 中配置的模型）
2. 生成的提示词落库保存历史
3. 用户可把生成结果（提示词 → Seedance 出片）与「去水印」功能串成
   「短片制作」工作流（提示词生成 → Seedance 生成 → 去水印出片）
"""

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import ShortdramaPrompt, SystemConfig
from app.services.minio_service import (
    get_presigned_url,
    delete_file,
    upload_file_from_path,
)
from app.services.upload_service import validate_file_name

logger = logging.getLogger(__name__)

router = APIRouter()

# 短片制作成片视频存储桶（Seedance 生成结果，供去水印流程读取）
SHORTDRAMA_VIDEO_BUCKET = settings.MINIO_BUCKET_WATERMARK_RAW

# ── 长 / 短提示词模板（用户可在「短片制作」页面在线编辑并持久化） ──
# 存于 system_config 表：shortdrama_prompt_templates = {"long": ..., "short": ...}
PROMPT_TEMPLATES_CONFIG_KEY = "shortdrama_prompt_templates"

# 内置默认模板（与 autoclip seedance_prompt_generator 保持一致）
DEFAULT_LONG_PROMPT_TEMPLATE = (
    "类型：按需匹配当前文案题材（家庭反转/悬疑猎奇/豪门恩怨/乡土故事/亲情冲突/搞笑反转）\n"
    "硬性视频参数：严格锁定视频时长【可填10秒 /15秒】，9:16高清竖屏；全程运镜平稳无抖动，"
    "禁止频繁切镜，单镜头最低停留1.5s，反转、人物情绪特写镜头固定停留2s以上，结尾高光片段"
    "开启慢放，绝不压缩结尾情绪、不堆砌多段剧情。\n\n"
    "时间轴固定节奏（强制执行）\n"
    "方案1‑10秒版：0‑3s强冲突黄金钩子抓人；3‑7s铺垫主线剧情；7‑10s只展示结局反转+人物情绪反应，"
    "不再新增故事情节\n"
    "方案2‑15秒版：0‑3s高能钩子；3‑9s完整铺垫故事经过；9‑15s慢节奏呈现反转爆发、夸张神态肢体\n\n"
    "剧情创作要求：根据给到的短剧文案自主完善真实合理场景、简短人物对白、适配情绪的夸张肢体动作、"
    "面部神情；只推进主线，不加多余配角、无关支线、复杂冗余桥段，贴合抖音热门短剧叙事风格。\n\n"
    "配音音频规范：配音语速舒缓、吐字清晰，人声情绪跟随剧情起伏；口型、画面、旁白音频严格同步，"
    "杜绝音画错位、语速急促、配音快过画面节奏。\n\n"
    "字幕设置：启用加粗白字+黑色粗描边同步中文字幕；单条字幕展示时长≥1.5秒，字幕随配音依次弹出；"
    "禁止字幕一闪而过、多层字幕堆叠错乱。\n\n"
    "画质风格：8K超清写实画质，画面干净，无杂乱花哨特效。\n\n"
    "本次短剧文案：[视频文案]\n\n"
    "负面避坑禁止清单\n"
    "禁止剧情节奏仓促、动作潦草急促；禁止镜头闪切、频繁转场、画面晃动；禁止配音含糊、语速过快、"
    "音画不同步；禁止字幕闪逝、字幕错乱；禁止人脸畸形、画面卡顿模糊；禁止多余花里胡哨特效；"
    "禁止末尾几秒塞入大量新剧情、结尾仓促跳转镜头；禁止添加和主线无关的人物和情节"
)

DEFAULT_SHORT_PROMPT_TEMPLATE = (
    "生成视频：类型：古言甜宠剧情；根据文案生成10秒9:16的短剧视频：[视频文案]\n"
    "；根据文案剧情，依照你的想象力，设定合理的场景，加一些夸张的肢体语言，"
    "参考抖音热播短剧给这个视频添加中文字幕和配音"
)

PLACEHOLDER_VIDEO_TEXT = "[视频文案]"


async def _load_prompt_templates(db: AsyncSession) -> dict:
    """读取用户自定义长/短提示词模板（system_config 持久化）。

    未自定义时回退到内置默认模板。
    """
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == PROMPT_TEMPLATES_CONFIG_KEY)
    )
    cfg = result.scalar_one_or_none()
    saved = (cfg.value or {}) if cfg and isinstance(cfg.value, dict) else {}
    long_tpl = (saved.get("long") or "").strip() or DEFAULT_LONG_PROMPT_TEMPLATE
    short_tpl = (saved.get("short") or "").strip() or DEFAULT_SHORT_PROMPT_TEMPLATE
    return {"long": long_tpl, "short": short_tpl}


async def _save_prompt_templates(db: AsyncSession, templates: dict) -> None:
    """持久化用户自定义长/短提示词模板（system_config）。"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == PROMPT_TEMPLATES_CONFIG_KEY)
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.value = templates
        cfg.updated_at = datetime.utcnow()
    else:
        db.add(SystemConfig(
            key=PROMPT_TEMPLATES_CONFIG_KEY,
            value=templates,
            description="短片制作长/短提示词模板（用户可编辑）",
        ))
    await db.flush()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class PromptGenerateRequest(BaseModel):
    # 用户输入的短剧文案（对白/旁白原文），必填
    text: str = ""
    # 时长：10 / 15 秒或自定义秒数（3~300）
    duration: int = 15
    # 可选参数：题材 / 基调 / 角色 / 补充要求
    theme: Optional[str] = None
    tone: Optional[str] = None
    characters: Optional[str] = None
    extra_requirements: Optional[str] = None
    # 是否保存到生成历史（默认保存）
    save: bool = True


class PromptTemplatesResponse(BaseModel):
    long: str = ""
    short: str = ""
    updated_at: str = ""


class PromptGenerateResponse(BaseModel):
    prompt: str
    versions: Optional[dict] = None  # {long/short/ai}
    duration: int
    model: Optional[str] = None
    record_id: Optional[str] = None
    message: str


class PromptRecordItem(BaseModel):
    id: str
    source_text: str
    duration: int
    theme: Optional[str] = None
    tone: Optional[str] = None
    characters: Optional[str] = None
    extra_requirements: Optional[str] = None
    model: Optional[str] = None
    prompt_text: str
    prompt_long: Optional[str] = None
    prompt_short: Optional[str] = None
    created_at: str
    # 成片视频附件（Seedance 生成结果，可一键导入去水印流程）
    video_file_name: Optional[str] = None
    video_file_key: Optional[str] = None
    video_bucket: Optional[str] = None
    video_file_size: Optional[int] = None
    video_status: Optional[str] = None
    video_error_message: Optional[str] = None
    video_url: Optional[str] = None
    video_uploaded_at: Optional[str] = None


# ──────────────────────────────────────────────
# 序列化
# ──────────────────────────────────────────────


def _serialize_record(r: ShortdramaPrompt) -> dict:
    return {
        "id": str(r.id),
        "source_text": r.source_text,
        "duration": r.duration,
        "theme": r.theme,
        "tone": r.tone,
        "characters": r.characters,
        "extra_requirements": r.extra_requirements,
        "model": r.model,
        "prompt_text": r.prompt_text,
        "prompt_long": r.prompt_long,
        "prompt_short": r.prompt_short,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "video_file_name": r.video_file_name,
        "video_file_key": r.video_file_key,
        "video_bucket": r.video_bucket,
        "video_file_size": r.video_file_size,
        "video_status": r.video_status,
        "video_error_message": r.video_error_message,
        "video_url": None,
        "video_uploaded_at": r.video_uploaded_at.isoformat() if r.video_uploaded_at else None,
    }


# ──────────────────────────────────────────────
# API
# ──────────────────────────────────────────────


@router.post("/shortdrama/prompt/generate", response_model=PromptGenerateResponse)
async def generate_shortdrama_prompt(
    data: PromptGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """根据用户输入的文案生成 Seedance 提示词。

    模型借用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME），
    通过 autoclip 的 POST /api/v1/prompt/generate 端点执行。
    """
    if not data.text or not data.text.strip():
        raise HTTPException(status_code=400, detail="请输入短剧文案")

    duration = _normalize_duration(data.duration)

    url = f"{settings.AUTOCLIP_URL}/prompt/generate"
    # 读取用户自定义长/短模板并下发给 autoclip（若用户编辑过模板）
    templates = await _load_prompt_templates(db)
    payload = {
        "text": data.text.strip(),
        "duration": duration,
        "params": {
            "theme": data.theme,
            "tone": data.tone,
            "characters": data.characters,
            "extra_requirements": data.extra_requirements,
        },
        "templates": templates,
        "max_retries": 3,
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("autoclip prompt generate failed: %s %s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=502,
            detail=f"提示词生成服务调用失败（AutoClip 返回 {e.response.status_code}）：{e.response.text[:300]}",
        )
    except httpx.RequestError as e:
        logger.error("autoclip prompt generate request error: %s", e)
        raise HTTPException(status_code=502, detail=f"无法连接 AutoClip 服务：{e}")

    prompt_text = (result or {}).get("prompt") or ""
    model = (result or {}).get("model") or ""
    if not prompt_text:
        raise HTTPException(status_code=502, detail="AutoClip 未返回提示词内容")

    # 三版本提示词：长 / 短（固定模板） + AI（Seedance 生成）
    versions = (result or {}).get("versions") or {}
    prompt_long = (versions.get("long") or "").strip()
    prompt_short = (versions.get("short") or "").strip()
    # 兼容旧数据：未返回 versions 时按 prompt 回退填充 AI 版本
    if not versions:
        prompt_long = prompt_short = ""

    record_id = None
    if data.save:
        record = ShortdramaPrompt(
            source_text=data.text.strip(),
            duration=duration,
            theme=data.theme,
            tone=data.tone,
            characters=data.characters,
            extra_requirements=data.extra_requirements,
            model=model or None,
            prompt_text=prompt_text,
            prompt_long=prompt_long or None,
            prompt_short=prompt_short or None,
        )
        db.add(record)
        await db.flush()
        record_id = str(record.id)
        await db.commit()

    return PromptGenerateResponse(
        prompt=prompt_text,
        versions=versions or None,
        duration=duration,
        model=model or None,
        record_id=record_id,
        message="提示词生成成功" if prompt_text else "提示词生成失败",
    )


def _normalize_duration(duration) -> int:
    """时长归一化：支持 10 / 15 秒及任意自定义秒数（3~300）。"""
    try:
        d = int(duration)
    except (TypeError, ValueError):
        return 15
    if d < 3 or d > 300:
        return 15
    return d


@router.get("/shortdrama/prompts", response_model=List[PromptRecordItem])
async def list_shortdrama_prompts(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """提示词生成历史（按创建时间倒序），带成片视频签名 URL。"""
    if limit < 1 or limit > 200:
        limit = 50
    result = await db.execute(
        select(ShortdramaPrompt)
        .order_by(ShortdramaPrompt.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    items = []
    for r in records:
        item = _serialize_record(r)
        if r.video_file_key and r.video_bucket:
            item["video_url"] = await get_presigned_url(
                r.video_bucket, r.video_file_key, expires_seconds=3600
            )
        items.append(item)
    return items


@router.get("/shortdrama/prompts/{record_id}", response_model=PromptRecordItem)
async def get_shortdrama_prompt(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单条提示词生成记录详情。"""
    record = await _get_record_or_404(record_id, db)
    item = _serialize_record(record)
    if record.video_file_key and record.video_bucket:
        item["video_url"] = await get_presigned_url(
            record.video_bucket, record.video_file_key, expires_seconds=3600
        )
    return item


@router.delete("/shortdrama/prompts/{record_id}", response_model=dict)
async def delete_shortdrama_prompt(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单条提示词生成记录（连同关联的成片视频）。"""
    record = await _get_record_or_404(record_id, db)
    # 先删除关联的成片视频文件
    if record.video_file_key and record.video_bucket:
        try:
            await delete_file(record.video_bucket, record.video_file_key)
        except Exception as e:
            logger.warning("删除成片视频失败（忽略）: %s", e)

    await db.delete(record)
    await db.commit()
    return {"message": "记录已删除", "record_id": record_id}


async def _get_record_or_404(record_id: str, db: AsyncSession) -> ShortdramaPrompt:
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record ID")
    result = await db.execute(
        select(ShortdramaPrompt).where(ShortdramaPrompt.id == rid)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


# ──────────────────────────────────────────────
# 成片视频上传 / 详情 / 删除 / 一键导入去水印
# ──────────────────────────────────────────────


@router.post("/shortdrama/prompts/{record_id}/video", response_model=PromptRecordItem)
async def upload_shortdrama_video(
    record_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """为一条提示词生成记录上传成片视频（Seedance 生成结果）。

    视频存入 watermark-raw 桶，与去水印流程共用同一存储，
    之后可一键导入到去水印任务中。
    """
    record = await _get_record_or_404(record_id, db)

    file_name = file.filename or ""
    try:
        safe_name = validate_file_name(file_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/shortdrama_video/{upload_id}_{safe_name}"
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

    file_key = f"shortdrama/{str(record.id)}/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(
        SHORTDRAMA_VIDEO_BUCKET,
        file_key,
        local_path,
        content_type=file.content_type or "video/mp4",
    )
    os.unlink(local_path)
    if not ok:
        raise HTTPException(status_code=500, detail="文件上传存储失败")

    # 若此前已有关联视频，先清理旧文件
    if record.video_file_key and record.video_bucket:
        try:
            await delete_file(record.video_bucket, record.video_file_key)
        except Exception as e:
            logger.warning("清理旧成片视频失败（忽略）: %s", e)

    record.video_file_name = safe_name
    record.video_file_key = file_key
    record.video_bucket = SHORTDRAMA_VIDEO_BUCKET
    record.video_file_size = size
    record.video_status = "uploaded"
    record.video_error_message = None
    record.video_uploaded_at = datetime.utcnow()
    await db.commit()

    # 返回带可播放的签名 URL，便于前端上传后立即预览
    item = _serialize_record(record)
    if record.video_file_key and record.video_bucket:
        item["video_url"] = await get_presigned_url(
            record.video_bucket, record.video_file_key, expires_seconds=3600
        )
    return item


@router.get("/shortdrama/prompts/{record_id}/video", response_model=dict)
async def get_shortdrama_video(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取记录关联成片视频的签名播放地址。"""
    record = await _get_record_or_404(record_id, db)
    if not record.video_file_key or not record.video_bucket:
        raise HTTPException(status_code=404, detail="该记录尚未上传成片视频")
    url = await get_presigned_url(record.video_bucket, record.video_file_key, expires_seconds=3600)
    if not url:
        raise HTTPException(status_code=500, detail="获取视频地址失败")
    return {
        "record_id": record_id,
        "file_name": record.video_file_name,
        "url": url,
        "file_size": record.video_file_size,
        "status": record.video_status,
    }


@router.delete("/shortdrama/prompts/{record_id}/video", response_model=dict)
async def delete_shortdrama_video(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除记录关联的成片视频（保留提示词记录）。"""
    record = await _get_record_or_404(record_id, db)
    if record.video_file_key and record.video_bucket:
        try:
            await delete_file(record.video_bucket, record.video_file_key)
        except Exception as e:
            logger.warning("删除成片视频失败: %s", e)
    record.video_file_name = None
    record.video_file_key = None
    record.video_bucket = None
    record.video_file_size = None
    record.video_status = None
    record.video_error_message = None
    record.video_uploaded_at = None
    await db.commit()
    return {"message": "视频已删除", "record_id": record_id}


@router.post("/shortdrama/prompts/{record_id}/import-to-watermark", response_model=dict)
async def import_shortdrama_video_to_watermark(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """一键把生成历史中的成片视频导入去水印流程。

    返回去水印任务所需的上传凭证（source_file_key），
    前端随即把视频挂载到「去水印」页签并可直接提交去水印任务。
    """
    record = await _get_record_or_404(record_id, db)
    if not record.video_file_key or not record.video_bucket:
        raise HTTPException(status_code=404, detail="该记录尚未上传成片视频，无法导入")
    # 附带签名播放地址，便于去水印页待处理列表展示缩略图 / 悬停预览
    preview_url = await get_presigned_url(
        record.video_bucket, record.video_file_key, expires_seconds=3600
    )
    return {
        "record_id": record_id,
        "file_name": record.video_file_name,
        "source_file_key": record.video_file_key,
        "bucket": record.video_bucket,
        "file_size": record.video_file_size,
        "url": preview_url,
        "message": "已导入去水印流程，可直接提交处理",
    }


# ──────────────────────────────────────────────
# 长 / 短提示词模板管理（用户可在线编辑并持久化）
# ──────────────────────────────────────────────


@router.get("/shortdrama/prompt/templates", response_model=PromptTemplatesResponse)
async def get_shortdrama_prompt_templates(
    db: AsyncSession = Depends(get_db),
):
    """获取长/短提示词模板（用户自定义值，未编辑时返回内置默认）。"""
    templates = await _load_prompt_templates(db)
    updated_at = ""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == PROMPT_TEMPLATES_CONFIG_KEY)
    )
    cfg = result.scalar_one_or_none()
    if cfg and cfg.updated_at:
        updated_at = cfg.updated_at.isoformat()
    return PromptTemplatesResponse(long=templates["long"], short=templates["short"], updated_at=updated_at)


class PromptTemplatesUpdateRequest(BaseModel):
    long: Optional[str] = None
    short: Optional[str] = None


@router.put("/shortdrama/prompt/templates", response_model=PromptTemplatesResponse)
async def update_shortdrama_prompt_templates(
    data: PromptTemplatesUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """保存用户自定义的长/短提示词模板（至少传一个字段，[视频文案] 占位符保留）。

    模板内需包含 [视频文案] 占位符（保存时自动补齐），
    生成时会把占位符替换为用户输入的文案。
    """
    current = await _load_prompt_templates(db)
    long_tpl = data.long if data.long is not None else current["long"]
    short_tpl = data.short if data.short is not None else current["short"]

    # 校验 / 补齐占位符，避免模板保存后文案丢失
    if PLACEHOLDER_VIDEO_TEXT not in (long_tpl or ""):
        long_tpl = f"{long_tpl}\n{PLACEHOLDER_VIDEO_TEXT}"
    if PLACEHOLDER_VIDEO_TEXT not in (short_tpl or ""):
        short_tpl = f"{short_tpl}\n{PLACEHOLDER_VIDEO_TEXT}"

    templates = {"long": long_tpl.strip(), "short": short_tpl.strip()}
    await _save_prompt_templates(db, templates)
    await db.commit()

    updated_at = datetime.utcnow().isoformat()
    return PromptTemplatesResponse(long=templates["long"], short=templates["short"], updated_at=updated_at)
