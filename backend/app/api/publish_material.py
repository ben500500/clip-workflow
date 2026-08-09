"""短片制作 API（v7）：短剧发布素材生成 + 生成历史。

工作流（完整「短片制作」链路）：
1. 用户输入短剧文案 → 生成 Seedance 提示词（v6，POST /shortdrama/prompt/generate）
2. 提示词 → Seedance 出片 → 上传成片视频（v6.1）
3. 依据剧情梗概/提示词/标题 → 生成短剧发布素材（v7，本模块）
   - 短标题 → 三款视频配文 → 成套话题标签 → 三条置顶互动神评
4. 成片视频 → 去水印出片（v5）

模型统一复用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME）。
"""

import json
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
from app.models.models import PublishMaterial

logger = logging.getLogger(__name__)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class PublishMaterialGenerateRequest(BaseModel):
    # 用户输入的短剧剧情梗概 / 已生成的 Seedance 提示词 / 短剧标题（必填）
    story: str = ""
    # 可选参数：标题 / 题材 / 基调 / 平台 / 补充要求
    title: Optional[str] = None
    theme: Optional[str] = None
    tone: Optional[str] = None
    platform: Optional[str] = None
    extra_requirements: Optional[str] = None
    # 来源提示词记录 id（短片分析链路：发布素材 → 提示词）
    prompt_record_id: Optional[str] = None
    # 是否保存到生成历史（默认保存）
    save: bool = True


class PublishMaterialGenerateResponse(BaseModel):
    material: dict
    model: Optional[str] = None
    record_id: Optional[str] = None
    message: str


class PublishMaterialRecordItem(BaseModel):
    id: str
    story: str
    title: Optional[str] = None
    theme: Optional[str] = None
    tone: Optional[str] = None
    platform: Optional[str] = None
    extra_requirements: Optional[str] = None
    model: Optional[str] = None
    material: dict
    created_at: str


# ──────────────────────────────────────────────
# 序列化
# ──────────────────────────────────────────────


def _serialize_record(r: PublishMaterial) -> dict:
    material = r.material_json
    if isinstance(material, str):
        try:
            material = json.loads(material)
        except (json.JSONDecodeError, ValueError):
            material = {}
    return {
        "id": str(r.id),
        "story": r.story,
        "title": r.title,
        "theme": r.theme,
        "tone": r.tone,
        "platform": r.platform,
        "extra_requirements": r.extra_requirements,
        "model": r.model,
        "material": material or {},
        "prompt_record_id": str(r.prompt_record_id) if r.prompt_record_id else None,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ──────────────────────────────────────────────
# API
# ──────────────────────────────────────────────


@router.post(
    "/shortdrama/publish-material/generate",
    response_model=PublishMaterialGenerateResponse,
)
async def generate_publish_material(
    data: PublishMaterialGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """根据短剧剧情梗概生成一套可发布的短剧发布素材。

    输出结构严格顺序：短标题 → 三款视频配文 → 成套话题标签 → 三条置顶互动神评。
    模型借用 autoclip 中配置的大模型，通过 autoclip 的
    POST /api/v1/publish-material/generate 端点执行。
    """
    if not data.story or not data.story.strip():
        raise HTTPException(status_code=400, detail="请输入短剧剧情梗概")

    url = f"{settings.AUTOCLIP_URL}/publish-material/generate"
    payload = {
        "story": data.story.strip(),
        "params": {
            "title": data.title,
            "theme": data.theme,
            "tone": data.tone,
            "platform": data.platform,
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
        logger.error(
            "autoclip publish material generate failed: %s %s",
            e.response.status_code,
            e.response.text,
        )
        raise HTTPException(
            status_code=502,
            detail=f"发布素材生成服务调用失败（AutoClip 返回 {e.response.status_code}）：{e.response.text[:300]}",
        )
    except httpx.RequestError as e:
        logger.error("autoclip publish material request error: %s", e)
        raise HTTPException(status_code=502, detail=f"无法连接 AutoClip 服务：{e}")

    material = (result or {}).get("material") or {}
    model = (result or {}).get("model") or ""
    if not material:
        raise HTTPException(status_code=502, detail="AutoClip 未返回发布素材内容")

    record_id = None
    if data.save:
        # 校验来源提示词记录 id（可选），用于短片分析链路
        prompt_uuid = None
        if data.prompt_record_id:
            try:
                prompt_uuid = uuid.UUID(data.prompt_record_id)
            except ValueError:
                prompt_uuid = None
        record = PublishMaterial(
            story=data.story.strip(),
            title=data.title,
            theme=data.theme,
            tone=data.tone,
            platform=data.platform,
            extra_requirements=data.extra_requirements,
            model=model or None,
            material_json=material,
            prompt_record_id=prompt_uuid,
        )
        db.add(record)
        await db.flush()
        record_id = str(record.id)
        await db.commit()

    return PublishMaterialGenerateResponse(
        material=material,
        model=model or None,
        record_id=record_id,
        message="发布素材生成成功",
    )


@router.get("/shortdrama/publish-materials", response_model=List[PublishMaterialRecordItem])
async def list_publish_materials(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """发布素材生成历史（按创建时间倒序）。"""
    if limit < 1 or limit > 200:
        limit = 50
    result = await db.execute(
        select(PublishMaterial)
        .order_by(PublishMaterial.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return [_serialize_record(r) for r in records]


@router.get(
    "/shortdrama/publish-materials/{record_id}",
    response_model=PublishMaterialRecordItem,
)
async def get_publish_material(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单条发布素材生成记录详情。"""
    record = await _get_record_or_404(record_id, db)
    return _serialize_record(record)


@router.delete("/shortdrama/publish-materials/{record_id}", response_model=dict)
async def delete_publish_material(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除单条发布素材生成记录。"""
    record = await _get_record_or_404(record_id, db)
    await db.delete(record)
    await db.commit()
    return {"message": "记录已删除", "record_id": record_id}


async def _get_record_or_404(record_id: str, db: AsyncSession) -> PublishMaterial:
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record ID")
    result = await db.execute(
        select(PublishMaterial).where(PublishMaterial.id == rid)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record
