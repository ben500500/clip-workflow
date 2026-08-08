"""短片制作 API（v6）：Seedance 提示词生成 + 生成历史。

工作流：
1. 用户输入短剧文案（对白/旁白原文）→ 调用 autoclip 的
   POST /api/v1/prompt/generate 生成 Seedance 提示词（复用 autoclip 中配置的模型）
2. 生成的提示词落库保存历史
3. 用户可把生成结果（提示词 → Seedance 出片）与「去水印」功能串成
   「短片制作」工作流（提示词生成 → Seedance 生成 → 去水印出片）
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import ShortdramaPrompt

logger = logging.getLogger(__name__)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class PromptGenerateRequest(BaseModel):
    # 用户输入的短剧文案（对白/旁白原文），必填
    text: str = ""
    # 时长：10 / 15 秒
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

    duration = int(data.duration)
    if duration not in (10, 15):
        duration = 15

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


@router.get("/shortdrama/prompts", response_model=List[PromptRecordItem])
async def list_shortdrama_prompts(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """提示词生成历史（按创建时间倒序）。"""
    if limit < 1 or limit > 200:
        limit = 50
    result = await db.execute(
        select(ShortdramaPrompt)
        .order_by(ShortdramaPrompt.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return [_serialize_record(r) for r in records]


@router.get("/shortdrama/prompts/{record_id}", response_model=PromptRecordItem)
async def get_shortdrama_prompt(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单条提示词生成记录详情。"""
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
    return _serialize_record(record)


@router.delete("/shortdrama/prompts/{record_id}", response_model=dict)
async def delete_shortdrama_prompt(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单条提示词生成记录。"""
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

    await db.delete(record)
    await db.commit()
    return {"message": "记录已删除", "record_id": record_id}
