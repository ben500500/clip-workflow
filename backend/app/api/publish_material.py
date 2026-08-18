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
from typing import Annotated, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import PublishMaterial, User, SliceOutput, ClipCandidate, Episode, Project, SliceTask
from app.models.user import user_can_access_all_materials
from app.utils.helpers import utc_iso

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


class PublishMaterialGenerateFromOutputRequest(BaseModel):
    # 切片成品 output_id（从 SliceOutput 自动组装剧情梗概 story）
    output_id: str
    # 可选参数：题材 / 基调 / 平台 / 补充要求（覆盖默认组装）
    theme: Optional[str] = None
    tone: Optional[str] = None
    platform: Optional[str] = None
    extra_requirements: Optional[str] = None
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
        "created_at": utc_iso(r.created_at) if r.created_at else "",
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


async def _build_story_from_output(
    db: AsyncSession, output_id: str, current_user: User
) -> dict:
    """从切片成品 SliceOutput 向上游组装一段剧情梗概 story（供发布素材生成）。

    组装来源（与短片制作要的 story 同构）：
      - Project.name / description（剧名 / 项目描述）
      - Episode.title / episode_no（剧集标题 / 集数）
      - ClipCandidate.content / outline / recommend_reason（切片标题 / 内容摘要 / 大纲 / 推荐理由）

    同时做数据隔离校验：当前用户无权访问该项目时抛 403。
    """
    try:
        out_uuid = uuid.UUID(str(output_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output_id")

    result = await db.execute(
        select(SliceOutput).where(SliceOutput.id == out_uuid)
    )
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="切片成品不存在")

    task = None
    if output.task_id:
        task_res = await db.execute(
            select(SliceTask).where(SliceTask.id == output.task_id)
        )
        task = task_res.scalar_one_or_none()

    episode = None
    project = None
    if task and task.episode_id:
        ep_res = await db.execute(
            select(Episode).where(Episode.id == task.episode_id)
        )
        episode = ep_res.scalar_one_or_none()
        if episode:
            proj_res = await db.execute(
                select(Project).where(Project.id == episode.project_id)
            )
            project = proj_res.scalar_one_or_none()

    # 数据隔离：仅项目创建人 / 可访问全部素材的用户可生成
    if project:
        if not user_can_access_all_materials(current_user) and project.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权访问该项目的切片成品")

    candidate = None
    if output.clip_id:
        cand_res = await db.execute(
            select(ClipCandidate).where(ClipCandidate.id == output.clip_id)
        )
        candidate = cand_res.scalar_one_or_none()

    # 组装剧情梗概
    parts = []
    if project and project.name:
        parts.append(f"剧名：{project.name}")
    if project and project.description:
        parts.append(f"项目描述：{project.description}")
    if episode:
        parts.append(
            f"剧集：{('第' + str(episode.episode_no) + '集 ') if episode.episode_no else ''}{episode.title or ''}"
        )
    if candidate:
        if candidate.title:
            parts.append(f"切片标题：{candidate.title}")
        if candidate.content:
            parts.append(f"内容摘要：{candidate.content}")
        if candidate.outline:
            parts.append(f"大纲：{candidate.outline}")
        if candidate.recommend_reason:
            parts.append(f"推荐理由：{candidate.recommend_reason}")
    story = "\n".join(p for p in parts if p).strip()
    if not story:
        # 兜底：至少给出切片文件名，避免空 story 导致生成失败
        story = f"切片成品 {output.file_name or output_id} 的剧情摘要"

    return {
        "story": story,
        "title": (candidate.title if candidate and candidate.title else (episode.title if episode else None)),
    }


@router.post(
    "/shortdrama/publish-material/generate-from-output",
    response_model=PublishMaterialGenerateResponse,
)
async def generate_publish_material_from_output(
    data: PublishMaterialGenerateFromOutputRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """从切片成品自动生成短剧发布素材（短视频产线「最后一公里」）。

    把切片链路上游的上下文（项目名/剧集标题/切片标题/内容摘要/大纲/推荐理由）
    组装成剧情梗概 story，复用短片制作的 `publish_material_generator` 生成
    短标题 / 三款配文 / 成套标签 / 三条神评，存 PublishMaterial 并关联到该切片成品。

    前端「成品预览 → 一键发布」弹窗可直接调本端点生成标题/配文/标签，
    无需用户手写剧情梗概。
    """
    ctx = await _build_story_from_output(db, data.output_id, current_user)

    url = f"{settings.AUTOCLIP_URL}/publish-material/generate"
    payload = {
        "story": ctx["story"],
        "params": {
            "title": ctx.get("title"),
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
            "autoclip publish material generate-from-output failed: %s %s",
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
        record = PublishMaterial(
            story=ctx["story"],
            title=ctx.get("title"),
            theme=data.theme,
            tone=data.tone,
            platform=data.platform,
            extra_requirements=data.extra_requirements,
            model=model or None,
            material_json=material,
        )
        db.add(record)
        await db.flush()
        record_id = str(record.id)
        await db.commit()

    return PublishMaterialGenerateResponse(
        material=material,
        model=model or None,
        record_id=record_id,
        message="已从切片成品生成发布素材",
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
