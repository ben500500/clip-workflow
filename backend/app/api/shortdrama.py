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
from app.models.models import ShortdramaPrompt
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


class PromptGenerateResponse(BaseModel):
    prompt: str
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
    payload = {
        "text": data.text.strip(),
        "duration": duration,
        "params": {
            "theme": data.theme,
            "tone": data.tone,
            "characters": data.characters,
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
        )
        db.add(record)
        await db.flush()
        record_id = str(record.id)
        await db.commit()

    return PromptGenerateResponse(
        prompt=prompt_text,
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

    return _serialize_record(record)


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
    return {
        "record_id": record_id,
        "file_name": record.video_file_name,
        "source_file_key": record.video_file_key,
        "bucket": record.video_bucket,
        "file_size": record.video_file_size,
        "message": "已导入去水印流程，可直接提交处理",
    }
