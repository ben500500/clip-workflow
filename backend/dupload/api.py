"""dupload API 路由（前缀 /api/dupload/*，独立路由）。

提供：
- GET  /api/dupload/config            获取 dupload 配置（只读，不含 auth_headers 明文）
- POST /api/dupload/trigger           推送单个剧目到下载平台（仅下载）

鉴权：由 main.py 统一挂载到 `_protected_routers`（Depends(get_current_user)）。
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.drama import Drama
from app.models.models import SystemConfig, User

from dupload.client import DuploadError, get_client
from dupload.config import DuploadConfig, load_dupload_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dupload", tags=["dupload"])

# system_config 表里的配置 key（与 backend/app/api/config.py DEFAULT_CONFIGS 一致）
DUPLOAD_CONFIG_KEY = "dupload_config"


async def _load_config(db: AsyncSession) -> DuploadConfig:
    """读取 dupload 配置：system_config > 环境变量 > 默认。"""
    try:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == DUPLOAD_CONFIG_KEY)
        )
        row = result.scalar_one_or_none()
        db_config = row.value if (row and isinstance(row.value, dict)) else {}
    except Exception:
        db_config = {}
    return load_dupload_config(db_config=db_config)


@router.get("/config")
async def dupload_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回 dupload 配置（只读，不含 auth_headers 明文）。"""
    return (await _load_config(db)).to_public_dict()


class DuploadTriggerRequest(BaseModel):
    """推送请求：可传 drama_id（从剧目库取素材链接），或直接传 drama_name + share_url。"""
    drama_id: Optional[uuid.UUID] = Field(None, description="剧目 id（从剧目库自动取素材链接）")
    drama_name: Optional[str] = Field(None, description="剧名（与 drama_id 二选一，直接传时必填）")
    share_url: Optional[str] = Field(None, description="素材链接/网盘 shareUrl（与 drama_id 二选一）")


class DuploadTriggerResponse(BaseModel):
    drama_name: str
    share_url: str
    action: str
    sent: bool
    message: str
    remote: Optional[dict] = None


@router.post("/trigger", response_model=DuploadTriggerResponse)
async def dupload_trigger(
    data: DuploadTriggerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """推送单个剧目到下载平台（action=only_download）。

    二选一：
    - 传 `drama_id`：自动从剧目库读素材链接（share_url_field 字段，默认 material_link）；
    - 直接传 `drama_name` + `share_url`。
    """
    cfg = await _load_config(db)
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="推送到下载平台(dupload)功能未开启（可在系统设置-推送到下载平台中开启）")

    drama_name = (data.drama_name or "").strip()
    share_url = (data.share_url or "").strip()

    if data.drama_id is not None:
        result = await db.execute(select(Drama).where(Drama.id == data.drama_id))
        drama = result.scalar_one_or_none()
        if drama is None:
            raise HTTPException(status_code=404, detail="剧目不存在")
        drama_name = drama.name or drama_name
        share_url = share_url or getattr(drama, cfg.share_url_field, None) or ""
    else:
        if not drama_name or not share_url:
            raise HTTPException(status_code=400, detail="需提供 drama_name + share_url，或传入 drama_id 从剧目库取素材链接")

    if not drama_name:
        raise HTTPException(status_code=400, detail="剧名不能为空")
    if not share_url:
        raise HTTPException(
            status_code=400,
            detail=f"该剧目未填写素材链接（字段 {cfg.share_url_field} 为空），请先在剧目详情录入网盘 shareUrl",
        )

    client = get_client(cfg)
    try:
        remote = await client.push_task(drama_name, share_url)
    except DuploadError as e:
        raise HTTPException(status_code=502, detail=f"推送失败: {e}")

    return DuploadTriggerResponse(
        drama_name=drama_name,
        share_url=share_url,
        action=cfg.action or "only_download",
        sent=True,
        message="已推送到下载平台（仅下载）",
        remote=remote,
    )
