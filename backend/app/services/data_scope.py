"""数据隔离辅助模块（二期方案）。

规则：
- 管理员 / 素材专员 / 发布专员：默认可见全部素材（data_scope=all）
- 运营专员：默认仅可见自己账号创建的素材（data_scope=own），
  管理员可通过「权限编辑」授予 all（全部素材）
- **无主项目（created_by IS NULL）视为公共项目**：所有登录用户可访问。
  历史数据存在 created_by 为 NULL 的项目（如 wechat-dl 默认项目），旧口径会把
  它们判为「不匹配任何用户」→ operator 访问剧集/视频地址一律 404；
  新口径统一按公共资源处理（不做存量 backfill，源头已修）。

项目/剧集等素材数据以 projects.created_by 为归属；所有按剧集（episode）
下钻的接口都应先校验当前用户对所属项目的访问权限，防止越权访问。
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Project, User, user_can_access_all_materials


def is_project_public(project: Project) -> bool:
    """无主项目（created_by 为 NULL）= 公共项目，所有登录用户可访问。"""
    return project is not None and project.created_by is None


def can_access_project(project: Project, current_user: User) -> bool:
    """判断当前用户是否可访问该项目（含无主项目=公共项目口径）。

    与 projects.py `_check_project_access`、upload.py `_check_project_access`
    保持同一口径，任何数据隔离判断都必须走这里，避免三处各写一份再漂移。
    """
    if user_can_access_all_materials(current_user):
        return True
    if project is None:
        return False
    if is_project_public(project):
        return True
    return project.created_by == getattr(current_user, "id", None)


def project_scope_filter(current_user: User):
    """按数据隔离口径返回「可见项目」的 SQL 过滤条件（None=不过滤）。

    operator（data_scope=own）可见：自己创建的项目 + 无主公共项目。
    """
    if user_can_access_all_materials(current_user):
        return None
    return (
        Project.created_by.is_(None)
        | (Project.created_by == current_user.id)
    )


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
    if not can_access_project(project, current_user):
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
    if not can_access_project(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")
