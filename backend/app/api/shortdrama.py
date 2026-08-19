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
import secrets
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import ShortdramaPrompt, SystemConfig, User
from app.services.minio_service import (
    get_presigned_url,
    delete_file,
    upload_file_from_path,
)
from app.services.upload_service import validate_file_name
from app.utils.helpers import utc_iso

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
    "硬性视频参数：严格锁定视频时长【可填10秒 /15秒 /20秒 /25秒 /30秒】，9:16高清竖屏；全程运镜平稳无抖动，"
    "禁止频繁切镜，单镜头最低停留1.5s，反转、人物情绪特写镜头固定停留2s以上，结尾高光片段"
    "开启慢放，绝不压缩结尾情绪、不堆砌多段剧情。\n\n"
    "时间轴固定节奏（强制执行）\n"
    "方案1‑10秒版：0‑3s强冲突黄金钩子抓人；3‑7s铺垫主线剧情；7‑10s只展示结局反转+人物情绪反应，"
    "不再新增故事情节\n"
    "方案2‑15秒版：0‑3s高能钩子；3‑9s完整铺垫故事经过；9‑15s慢节奏呈现反转爆发、夸张神态肢体\n"
    "方案3‑20秒版：0‑4s高能钩子；4‑13s完整铺垫故事经过；13‑20s慢节奏呈现反转爆发、夸张神态肢体\n"
    "方案4‑25秒版：0‑5s高能钩子；5‑16s完整铺垫故事经过；16‑25s慢节奏呈现反转爆发、夸张神态肢体\n"
    "方案5‑30秒版：0‑6s高能钩子；6‑19s完整铺垫故事经过；19‑30s慢节奏呈现反转爆发、夸张神态肢体\n\n"
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
    # 时长：10 / 15 / 20 / 25 / 30 秒或自定义秒数（3~300）
    duration: int = 15
    # 是否把本次所选时长保存为当前登录用户的默认值（前端选择时长后即作为默认值）
    save_duration_as_default: bool = False
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


class ScriptOptimizeRequest(BaseModel):
    # 待优化的短剧文案（必填）
    text: str = ""
    # 可选参数：题材 / 基调 / 补充要求
    theme: Optional[str] = None
    tone: Optional[str] = None
    extra_requirements: Optional[str] = None


class ScriptOptimizeResponse(BaseModel):
    optimized_text: str
    model: Optional[str] = None
    message: str


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
    # 一键豆包生成任务状态
    doubao_status: Optional[str] = None
    doubao_account_type: Optional[str] = None
    doubao_account: Optional[str] = None
    doubao_qrcode: Optional[str] = None
    doubao_message: Optional[str] = None
    doubao_error_message: Optional[str] = None
    doubao_progress: Optional[int] = None
    doubao_approved_prompt: Optional[str] = None
    doubao_rewrite_history: Optional[list] = None
    doubao_rewrite_count: Optional[int] = None
    # Seedance 官方 API 直连任务状态（与豆包 RPA 完全独立的第二通道）
    seedance_status: Optional[str] = None
    seedance_task_id: Optional[str] = None
    seedance_message: Optional[str] = None
    seedance_error_message: Optional[str] = None
    seedance_resolution: Optional[str] = None
    # 成片来源通道：doubao_rpa / seedance_api / manual（便于追溯）
    gen_channel: Optional[str] = None


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
        "created_at": utc_iso(r.created_at) if r.created_at else "",
        "video_file_name": r.video_file_name,
        "video_file_key": r.video_file_key,
        "video_bucket": r.video_bucket,
        "video_file_size": r.video_file_size,
        "video_status": r.video_status,
        "video_error_message": r.video_error_message,
        "video_url": None,
        "video_uploaded_at": utc_iso(r.video_uploaded_at) if r.video_uploaded_at else None,
        "doubao_status": r.doubao_status,
        "doubao_account_type": r.doubao_account_type,
        "doubao_account": r.doubao_account,
        "doubao_qrcode": r.doubao_qrcode,
        "doubao_screenshot": r.doubao_screenshot,
        "doubao_message": r.doubao_message,
        "doubao_error_message": r.doubao_error_message,
        "doubao_progress": r.doubao_progress,
        "doubao_approved_prompt": r.doubao_approved_prompt,
        "doubao_rewrite_history": r.doubao_rewrite_history or [],
        "doubao_rewrite_count": len(r.doubao_rewrite_history or []),
        "seedance_status": r.seedance_status,
        "seedance_task_id": r.seedance_task_id,
        "seedance_message": r.seedance_message,
        "seedance_error_message": r.seedance_error_message,
        "seedance_resolution": r.seedance_resolution,
        "gen_channel": r.gen_channel,
    }


# ──────────────────────────────────────────────
# API
# ──────────────────────────────────────────────


@router.post("/shortdrama/prompt/generate", response_model=PromptGenerateResponse)
async def generate_shortdrama_prompt(
    data: PromptGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """根据用户输入的文案生成 Seedance 提示词。

    模型借用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME），
    通过 autoclip 的 POST /api/v1/prompt/generate 端点执行。
    """
    if not data.text or not data.text.strip():
        raise HTTPException(status_code=400, detail="请输入短剧文案")

    # 时长选择后即作为当前登录用户的默认值
    if current_user and data.save_duration_as_default:
        current_user.prompt_default_duration = _normalize_duration(data.duration)

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
    elif current_user and data.save_duration_as_default:
        # 不落库历史时仍需保存用户默认时长
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
    """时长归一化：支持 10 / 15 / 20 / 25 / 30 秒及任意自定义秒数（3~300）。"""
    try:
        d = int(duration)
    except (TypeError, ValueError):
        return 15
    if d < 3 or d > 300:
        return 15
    return d


@router.post("/shortdrama/prompt/optimize", response_model=ScriptOptimizeResponse)
async def optimize_shortdrama_script(
    data: ScriptOptimizeRequest,
):
    """短剧文案 AI 优化：调用 autoclip 配置的大模型改写文案。

    模型借用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME），
    通过 autoclip 的 POST /api/v1/script/optimize 端点执行。
    """
    if not data.text or not data.text.strip():
        raise HTTPException(status_code=400, detail="请输入短剧文案")

    url = f"{settings.AUTOCLIP_URL}/script/optimize"
    payload = {
        "text": data.text.strip(),
        "params": {
            "theme": data.theme,
            "tone": data.tone,
            "extra_requirements": data.extra_requirements,
        },
        "max_retries": 3,
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("autoclip script optimize failed: %s %s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=502,
            detail=f"文案优化服务调用失败（AutoClip 返回 {e.response.status_code}）：{e.response.text[:300]}",
        )
    except httpx.RequestError as e:
        logger.error("autoclip script optimize request error: %s", e)
        raise HTTPException(status_code=502, detail=f"无法连接 AutoClip 服务：{e}")

    optimized_text = ((result or {}).get("optimized_text") or "").strip()
    if not optimized_text:
        raise HTTPException(status_code=502, detail="AutoClip 未返回优化后的文案")

    model = (result or {}).get("model") or ""
    return ScriptOptimizeResponse(
        optimized_text=optimized_text,
        model=model or None,
        message="文案优化成功",
    )


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
    record.gen_channel = "manual"
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
        updated_at = utc_iso(cfg.updated_at)
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

    updated_at = utc_iso(datetime.utcnow())
    return PromptTemplatesResponse(long=templates["long"], short=templates["short"], updated_at=updated_at)


# ──────────────────────────────────────────────
# 一键豆包生成（RPA 自动出片）
# ──────────────────────────────────────────────

DOUBAO_STATUS_LABELS = {
    "none": "未生成",
    "pending": "排队中",
    "need_login": "等待扫码",
    "running": "生成中",
    "awaiting_rewrite": "待确认改写",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


class DoubaoGenerateRequest(BaseModel):
    # 账户类型：free=免费（时长上限 10s）；pro=包月会员（时长上限 30s）
    account_type: str = "free"
    # 生成时长（秒）；超过账户类型上限自动校正
    duration: Optional[int] = None


class DoubaoGenerateResponse(BaseModel):
    record_id: str
    doubao_status: str
    message: str


class DoubaoRewriteConfirmRequest(BaseModel):
    # approved=确认使用改写稿并重试；rejected=再让豆包改一版；cancelled=放弃
    decision: str = "approved"


@router.post("/shortdrama/prompts/{record_id}/doubao/generate", response_model=DoubaoGenerateResponse)
async def start_doubao_generate(
    record_id: str,
    data: DoubaoGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """一键豆包生成：为提示词记录启动 RPA 豆包出片任务。

    - account_type 选择后即作为当前登录用户的默认值（users.doubao_account_type）
    - 已存在运行中的豆包任务时返回 409
    """
    if data.account_type not in ("free", "pro"):
        raise HTTPException(status_code=400, detail="账户类型仅支持 free（免费）或 pro（包月会员）")

    record = await _get_record_or_404(record_id, db)
    if record.doubao_status in ("pending", "running", "need_login", "awaiting_rewrite"):
        raise HTTPException(status_code=409, detail="该记录已有豆包任务在进行中，请先等待完成或取消")

    # 账户类型选择后作为当前登录用户的默认值
    if current_user and current_user.doubao_account_type != data.account_type:
        current_user.doubao_account_type = data.account_type

    record.doubao_status = "pending"
    record.doubao_account_type = data.account_type
    record.doubao_message = "任务已创建，等待执行…"
    record.doubao_progress = 0
    record.doubao_error_message = None
    record.doubao_qrcode = None
    record.doubao_confirm_token = None
    await db.flush()

    # 异步派发到 publish 队列（rpa_worker 上的 Celery worker 消费，连接 Chromium）
    from app.celery.tasks import doubao_generate_task
    celery_result = doubao_generate_task.delay(
        str(record.id),
        account_type=data.account_type,
        duration=data.duration,
    )
    record.doubao_task_id = celery_result.id
    await db.commit()

    return DoubaoGenerateResponse(
        record_id=str(record.id),
        doubao_status="pending",
        message="豆包生成任务已创建，正在后台执行",
    )


@router.post("/shortdrama/prompts/{record_id}/doubao/confirm-rewrite", response_model=DoubaoGenerateResponse)
async def confirm_doubao_rewrite(
    record_id: str,
    data: DoubaoRewriteConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """改写确认回调：用户在「等待改写确认」弹窗中做出决策。

    - approved：确认使用豆包改写稿，任务继续（用改写稿重新发送）
    - rejected：让豆包再改一版
    - cancelled：放弃本次生成
    需要一次性 confirm_token 防跨用户误操作。
    """
    if data.decision not in ("approved", "rejected", "cancelled"):
        raise HTTPException(status_code=400, detail="decision 仅支持 approved / rejected / cancelled")

    record = await _get_record_or_404(record_id, db)
    if record.doubao_status != "awaiting_rewrite":
        raise HTTPException(status_code=400, detail="当前记录不处于等待改写确认状态")

    if not record.doubao_confirm_token:
        raise HTTPException(status_code=400, detail="改写确认凭证已失效，请重新发起生成")

    token = record.doubao_confirm_token
    # 清除一次性凭证（Celery 任务看到 token 被清除即继续）
    record.doubao_confirm_token = None

    if data.decision == "cancelled":
        record.doubao_status = "cancelled"
        record.doubao_message = "用户已放弃本次豆包生成"
        record.doubao_error_message = "用户已放弃"
        await db.commit()
        return DoubaoGenerateResponse(record_id=record_id, doubao_status="cancelled", message="已放弃本次豆包生成")

    if data.decision == "rejected":
        # 让豆包再改一版：保持 awaiting_rewrite 状态（仅清除凭证），
        # Celery 轮询到 token 清除 + 非 running 状态即识别为 rejected 并继续改写
        record.doubao_message = "用户要求豆包继续改写，请稍候…"
        await db.commit()
        return DoubaoGenerateResponse(record_id=record_id, doubao_status="awaiting_rewrite", message="已通知豆包继续改写")

    # approved：确认使用改写稿，回到 running（Celery 轮询到 token 清除 + running 即继续）
    record.doubao_status = "running"
    record.doubao_message = "已确认改写稿，继续生成视频…"
    # 把最后一条改写稿作为 approved_prompt 落库留档
    if record.doubao_rewrite_history:
        record.doubao_approved_prompt = record.doubao_rewrite_history[-1].get("rewritten")
    await db.commit()
    return DoubaoGenerateResponse(record_id=record_id, doubao_status="running", message="已确认改写稿，继续生成")


@router.post("/shortdrama/prompts/{record_id}/doubao/cancel", response_model=DoubaoGenerateResponse)
async def cancel_doubao_generate(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """取消豆包生成任务（含等待扫码 / 生成中 / 等待改写确认）。"""
    record = await _get_record_or_404(record_id, db)
    if record.doubao_status in ("completed", "failed", "cancelled", "none", None):
        raise HTTPException(status_code=400, detail="当前无进行中的豆包任务可取消")

    record.doubao_status = "cancelled"
    record.doubao_message = "任务已取消"
    record.doubao_error_message = "用户取消"
    record.doubao_confirm_token = None
    await db.commit()

    # 尝试取消 Celery 任务（尽力而为）
    if record.doubao_task_id:
        try:
            from app.celery.tasks import celery_app as celery
            celery.control.revoke(record.doubao_task_id, terminate=False)
        except Exception:
            pass

    return DoubaoGenerateResponse(record_id=record_id, doubao_status="cancelled", message="豆包生成任务已取消")


@router.get("/shortdrama/prompts/{record_id}/doubao/status", response_model=PromptRecordItem)
async def get_doubao_status(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """查询豆包生成任务状态（前端轮询用，返回完整记录含二维码/改写稿）。"""
    record = await _get_record_or_404(record_id, db)
    item = _serialize_record(record)
    if record.video_file_key and record.video_bucket:
        item["video_url"] = await get_presigned_url(
            record.video_bucket, record.video_file_key, expires_seconds=3600
        )
    return item


# ──────────────────────────────────────────────
# 提示词生成默认时长（当前登录用户）
# ──────────────────────────────────────────────


@router.get("/shortdrama/prompt/default-duration", response_model=dict)
async def get_prompt_default_duration(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """获取当前登录用户的提示词生成默认时长（用户选择时长后即作为默认值）。

    未设置过时返回默认 15s。
    """
    duration = getattr(current_user, "prompt_default_duration", None) if current_user else None
    try:
        d = int(duration)
    except (TypeError, ValueError):
        d = 15
    if d < 3 or d > 300:
        d = 15
    return {"duration": d, "message": "获取默认时长成功"}


class PromptDefaultDurationRequest(BaseModel):
    # 提示词生成默认时长（秒）：10/15/20/25/30 或自定义（3~300）
    duration: int = 15


@router.put("/shortdrama/prompt/default-duration", response_model=dict)
async def update_prompt_default_duration(
    data: PromptDefaultDurationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """保存当前登录用户的提示词生成默认时长。"""
    d = _normalize_duration(data.duration)
    if current_user:
        current_user.prompt_default_duration = d
        await db.commit()
    return {"duration": d, "message": "已保存为当前用户的默认时长"}


@router.get("/shortdrama/doubao/account-type", response_model=dict)
async def get_doubao_account_type(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """获取当前登录用户的默认豆包账户类型（用户选择后即作为默认值）。"""
    account_type = current_user.doubao_account_type if current_user else "free"
    limits = await _load_doubao_limits(db)
    return {
        "account_type": account_type if account_type in ("free", "pro") else "free",
        "limits": limits,
    }


@router.put("/shortdrama/doubao/account-type", response_model=dict)
async def update_doubao_account_type(
    data: DoubaoGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """保存当前登录用户的默认豆包账户类型。"""
    if data.account_type not in ("free", "pro"):
        raise HTTPException(status_code=400, detail="账户类型仅支持 free 或 pro")
    if current_user:
        current_user.doubao_account_type = data.account_type
        await db.commit()
    return {
        "account_type": data.account_type,
        "message": "已保存为当前用户的默认账户类型",
    }


@router.post("/shortdrama/doubao/switch-account", response_model=dict)
async def switch_doubao_account(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """更换豆包账户：清除 RPA 持久化的豆包登录态，下次生成时重新扫码登录。"""
    from app.services.doubao_service import DoubaoGenerator

    gen = DoubaoGenerator(
        chrome_port=settings.CHROME_DEBUG_PORT,
        chrome_host=settings.CHROME_DEBUG_HOST,
    )
    ok = await gen.clear_login()
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="清除豆包登录态失败：请确认 RPA（rpa_worker）已启动且 CDP 端口可访问",
        )
    return {
        "message": "已清除豆包登录态，下次「一键豆包生成」时将弹出扫码登录，可切换到另一个豆包账号",
    }


async def _load_doubao_limits(db: AsyncSession) -> dict:
    """读取豆包账户时长上限配置（默认 free=10s / pro=30s），支持 system_config 覆盖。"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "shortdrama_doubao_config")
    )
    cfg = result.scalar_one_or_none()
    custom = (cfg.value or {}) if cfg and isinstance(cfg.value, dict) else {}
    return {
        "free_max_seconds": int(custom.get("free_max_seconds", 10)),
        "pro_max_seconds": int(custom.get("pro_max_seconds", 30)),
    }


# ──────────────────────────────────────────────
# Seedance 官方 API 直连出片（火山方舟）—— 与豆包 RPA 完全独立的第二通道
# ──────────────────────────────────────────────

SEEDANCE_STATUS_LABELS = {
    "none": "未生成",
    "pending": "排队中",
    "running": "生成中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

# Seedance 直连配置的 system_config key（可在系统设置中修改 JSON）
SEEDANCE_CONFIG_KEY = "shortdrama_seedance_config"


class SeedanceGenerateRequest(BaseModel):
    # 生成时长（秒）；Seedance 1.0 仅支持 5s/10s，>10s 按配置策略截断或拒绝
    duration: Optional[int] = None
    # 分辨率：480p / 720p / 1080p（默认取配置）
    resolution: Optional[str] = None


class SeedanceGenerateResponse(BaseModel):
    record_id: str
    seedance_status: str
    message: str


async def _load_seedance_config(db: AsyncSession):
    """读取 Seedance 直连配置（环境变量 + system_config 合并）。"""
    from app.services.ark_client import load_seedance_config

    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == SEEDANCE_CONFIG_KEY)
    )
    cfg = result.scalar_one_or_none()
    db_config = (cfg.value or {}) if cfg and isinstance(cfg.value, dict) else {}
    return load_seedance_config(db_config=db_config)


async def _require_seedance_enabled(db: AsyncSession):
    """开关校验：Seedance 直连未启用时统一抛 403（默认关闭）。"""
    cfg = await _load_seedance_config(db)
    if not cfg.enabled:
        raise HTTPException(
            status_code=403,
            detail="Seedance 官方 API 直连未启用（开关默认关闭）。请在系统设置或 .env 中配置并开启。",
        )
    return cfg


@router.get("/shortdrama/seedance/config", response_model=dict)
async def get_seedance_config(
    db: AsyncSession = Depends(get_db),
):
    """读取 Seedance 直连配置（只读，绝不返回 api_key）。

    前端据此展示「是否已开启 / 是否已配 Key / 支持的时长 / 超长策略」。
    """
    cfg = await _load_seedance_config(db)
    public = cfg.to_public_dict()
    # 未配置 Key 时补充友好提示
    if not public["has_api_key"]:
        public["missing"] = "未配置 SEEDANCE_API_KEY（火山方舟 API Key）"
    return public


@router.post("/shortdrama/prompts/{record_id}/seedance/generate", response_model=SeedanceGenerateResponse)
async def start_seedance_generate(
    record_id: str,
    data: SeedanceGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Seedance 官方 API 直连出片：为提示词记录启动方舟直连任务。

    - 开关未开启（默认）时返回 403，前端不展示该按钮
    - 与豆包 RPA 并行独立：seedance_* 字段与 doubao_* 字段互不干扰
    - 已存在运行中的 Seedance 任务时返回 409
    """
    await _require_seedance_enabled(db)

    record = await _get_record_or_404(record_id, db)
    if record.seedance_status in ("pending", "running"):
        raise HTTPException(status_code=409, detail="该记录已有 Seedance 直连任务在进行中，请先等待完成或取消")

    # 校验时长：Seedance 1.0 仅支持 5s/10s；>10s 由任务内按策略截断/拒绝
    want_duration = _normalize_duration(data.duration) if data.duration is not None else (record.duration or 10)

    record.seedance_status = "pending"
    record.seedance_task_id = None
    record.seedance_message = "任务已创建，等待执行…"
    record.seedance_error_message = None
    record.seedance_resolution = data.resolution or None
    await db.flush()

    # 异步派发到 publish 队列（普通 worker 即可消费，不依赖 rpa_worker）
    from app.celery.tasks import seedance_generate_task
    celery_result = seedance_generate_task.delay(
        str(record.id),
        duration=want_duration,
        resolution=data.resolution,
    )
    record.seedance_task_id = celery_result.id
    await db.commit()

    return SeedanceGenerateResponse(
        record_id=str(record.id),
        seedance_status="pending",
        message="Seedance 直连生成任务已创建，正在后台执行",
    )


@router.post("/shortdrama/prompts/{record_id}/seedance/cancel", response_model=SeedanceGenerateResponse)
async def cancel_seedance_generate(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """取消 Seedance 直连生成任务（尽力取消方舟侧任务 + 置 cancelled）。"""
    await _require_seedance_enabled(db)

    record = await _get_record_or_404(record_id, db)
    if record.seedance_status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="当前无进行中的 Seedance 直连任务可取消")

    # 尝试取消方舟侧任务（尽力而为）
    if record.seedance_task_id and record.seedance_status == "running":
        try:
            from app.services.ark_client import SeedanceClient, load_seedance_config

            cfg = await _load_seedance_config(db)
            if cfg.enabled and cfg.api_key:
                client = SeedanceClient(cfg)
                await client.cancel_task(record.seedance_task_id)
        except Exception as e:
            logger.warning("取消方舟侧任务失败（忽略）: %s", e)

    record.seedance_status = "cancelled"
    record.seedance_message = "任务已取消"
    record.seedance_error_message = "用户取消"
    await db.commit()

    # 尝试取消 Celery 任务（尽力而为）
    if record.seedance_task_id:
        try:
            from app.celery.tasks import celery_app as celery
            celery.control.revoke(record.seedance_task_id, terminate=False)
        except Exception:
            pass

    return SeedanceGenerateResponse(record_id=record_id, seedance_status="cancelled", message="Seedance 直连任务已取消")


@router.get("/shortdrama/prompts/{record_id}/seedance/status", response_model=PromptRecordItem)
async def get_seedance_status(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """查询 Seedance 直连任务状态（前端轮询用，返回完整记录）。"""
    record = await _get_record_or_404(record_id, db)
    item = _serialize_record(record)
    if record.video_file_key and record.video_bucket:
        item["video_url"] = await get_presigned_url(
            record.video_bucket, record.video_file_key, expires_seconds=3600
        )
    return item
