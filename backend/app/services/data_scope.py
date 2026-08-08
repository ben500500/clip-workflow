"""数据隔离辅助模块（二期方案）。

规则：
- 管理员 / 素材专员 / 发布专员：默认可见全部素材（data_scope=all）
- 运营专员：默认仅可见自己账号创建的素材（data_scope=own），
  管理员可通过「权限编辑」授予 all（全部素材）

项目/剧集等素材数据以 projects.created_by 为归属；所有按剧集（episode）
下钻的接口都应先校验当前用户对所属项目的访问权限，防止越权访问。
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Project, User, user_can_access_all_materials


async def check_project_access_by_episode(
    db: AsyncSession,
    episode,
    current_user: User,
) -> None:
    """根据剧集所属项目校验当前用户访问权限（无权限时抛 404，避免泄露存在性）."""
    if current_user is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if user_can_access_all_materials(current_user):
        return
    project = (
        await db.execute(select(Project).where(Project.id == episode.project_id))
    ).scalar_one_or_none()
    if project is None or project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Episode not found")


async def check_project_access_by_id(
    db: AsyncSession,
    project_id,
    current_user: User,
) -> None:
    """根据项目 ID 校验当前用户访问权限."""
    if current_user is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if user_can_access_all_materials(current_user):
        return
    try:
        pid = uuid.UUID(str(project_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if project is None or project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
