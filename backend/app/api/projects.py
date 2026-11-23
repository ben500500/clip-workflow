import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db, async_session_factory
from app.models.models import (
    Project,
    Episode,
    User,
    AutoClipProject,
    SliceTask,
    SliceOutput,
    user_can_access_all_materials,
)
from app.services.data_scope import (
    can_access_project,
    check_project_access_by_episode,
    project_scope_filter,
)
from app.services.minio_service import get_presigned_url, delete_file, list_files
from app.utils.helpers import utc_iso
from app.utils.source_media import probe_media, needs_normalize, normalize_media_file
from app.services.minio_service import upload_file_from_path

logger = logging.getLogger(__name__)


def _remove_path(path: Path) -> None:
    """删除文件或目录（不存在时静默忽略）。"""
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            pass

router = APIRouter()


# ---------- Pydantic Schemas ----------

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    config: Optional[dict] = {}


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    config: Optional[dict] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    config: Optional[dict] = {}
    # 创建人（数据隔离）
    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    episode_count: int = 0

    model_config = {"from_attributes": True}


class EpisodeCreate(BaseModel):
    title: Optional[str] = None
    episode_no: Optional[int] = None
    source_file_key: Optional[str] = None
    duration: Optional[float] = None
    resolution: Optional[str] = None
    file_size: Optional[int] = None


class EpisodeResponse(BaseModel):
    id: str
    project_id: str
    title: Optional[str] = None
    episode_no: Optional[int] = None
    source_file_key: Optional[str] = None
    # 剧集封面（作为切片首帧叠加，按剧集独立存储；为空时切片用源视频首帧）
    cover_image_key: Optional[str] = None
    duration: Optional[float] = None
    resolution: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class EpisodeListResponse(BaseModel):
    items: List[EpisodeResponse]
    total: int


class ProjectOutputItem(BaseModel):
    output_id: str
    task_id: str
    episode_id: str
    episode_no: Optional[int] = None
    episode_title: Optional[str] = None
    mode: Optional[str] = None
    task_status: Optional[str] = None
    clip_id: Optional[str] = None
    file_key: Optional[str] = None
    file_name: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    resolution: Optional[str] = None
    created_at: str
    presigned_url: Optional[str] = None


class ProjectOutputListResponse(BaseModel):
    items: List[ProjectOutputItem]
    total: int


# ---------- Helper ----------

def _serialize_project(project: Project) -> dict:
    # 异步会话下访问未预加载的关系会抛 MissingGreenlet，这里做防御处理
    try:
        episode_count = len(project.episodes)
    except Exception:
        episode_count = 0
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "config": project.config or {},
        "created_by": str(project.created_by) if project.created_by else None,
        "created_at": utc_iso(project.created_at) if project.created_at else "",
        "updated_at": utc_iso(project.updated_at) if project.updated_at else "",
        "episode_count": episode_count,
    }


def _serialize_episode(episode: Episode) -> dict:
    return {
        "id": str(episode.id),
        "project_id": str(episode.project_id),
        "title": episode.title,
        "episode_no": episode.episode_no,
        "source_file_key": episode.source_file_key,
        "cover_image_key": episode.cover_image_key,
        "duration": episode.duration,
        "resolution": episode.resolution,
        "file_size": episode.file_size,
        "status": episode.status,
        "created_at": utc_iso(episode.created_at) if episode.created_at else "",
        "updated_at": utc_iso(episode.updated_at) if episode.updated_at else "",
    }


# ---------- Project Routes ----------


def _data_scope_filter(current_user: User):
    """数据隔离：返回用户可见项目的过滤条件（无主项目=公共，operator 也可见）。

    - admin/material/publisher：默认可见全部素材（不过滤）
    - operator：仅可见自己创建的素材 + 无主公共项目；管理员可授予 all
    """
    return project_scope_filter(current_user)


def _check_project_access(project: Project, current_user: User) -> bool:
    """数据隔离：判断当前用户是否可访问该项目（口径见 services.data_scope）。"""
    return can_access_project(project, current_user)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Create a new project（记录创建人，用于数据隔离）."""
    project = Project(
        name=data.name,
        description=data.description,
        config=data.config or {},
        created_by=current_user.id,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return _serialize_project(project)


@router.get("/projects")
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List projects with search, status filter and pagination（数据隔离）. """
    filters = []
    if search:
        filters.append(Project.name.ilike(f"%{search}%"))
    if status:
        filters.append(Project.status == status)

    # 数据隔离：运营专员默认仅可见自己创建的素材
    scope_filter = _data_scope_filter(current_user)
    if scope_filter is not None:
        filters.append(scope_filter)

    count_query = select(func.count(Project.id))
    if filters:
        count_query = count_query.where(*filters)
    total = (await db.execute(count_query)).scalar() or 0

    query = select(Project).options(selectinload(Project.episodes))
    if filters:
        query = query.where(*filters)
    query = query.order_by(Project.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    projects = (await db.execute(query)).scalars().all()

    return {
        "items": [_serialize_project(p) for p in projects],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/projects/stats")
async def project_stats(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return dashboard statistics for projects/episodes/slices（数据隔离）. """
    from app.models.models import Episode, SliceTask

    scope_filter = _data_scope_filter(current_user)

    total_projects_q = select(func.count(Project.id))
    active_projects_q = select(func.count(Project.id)).where(Project.status.in_(["processing", "completed"]))
    total_episodes_q = select(func.count(Episode.id))
    processed_episodes_q = select(func.count(Episode.id)).where(
        Episode.status.in_(["clips_detected", "intervals_detected", "slicing", "completed"])
    )
    total_slices_q = select(func.count(SliceTask.id))
    recent_q = select(Project).options(selectinload(Project.episodes)).order_by(Project.updated_at.desc()).limit(5)

    if scope_filter is not None:
        total_projects_q = total_projects_q.where(scope_filter)
        active_projects_q = active_projects_q.where(scope_filter)
        total_episodes_q = total_episodes_q.where(
            Episode.project_id.in_(
                select(Project.id).where(scope_filter)
            )
        )
        processed_episodes_q = processed_episodes_q.where(
            Episode.project_id.in_(
                select(Project.id).where(scope_filter)
            )
        )
        total_slices_q = total_slices_q.where(
            SliceTask.episode_id.in_(
                select(Episode.id).where(
                    Episode.project_id.in_(
                        select(Project.id).where(scope_filter)
                    )
                )
            )
        )
        recent_q = recent_q.where(scope_filter)

    total_projects = (await db.execute(total_projects_q)).scalar() or 0
    active_projects = (await db.execute(active_projects_q)).scalar() or 0
    total_episodes = (await db.execute(total_episodes_q)).scalar() or 0
    processed_episodes = (await db.execute(processed_episodes_q)).scalar() or 0
    total_slices = (await db.execute(total_slices_q)).scalar() or 0

    recent = (await db.execute(recent_q)).scalars().all()

    return {
        "total_projects": total_projects,
        "active_projects": active_projects,
        "total_episodes": total_episodes,
        "processed_episodes": processed_episodes,
        "total_slices": total_slices,
        "recent_projects": [_serialize_project(p) for p in recent],
    }


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a project by ID（数据隔离）. """
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(Project).options(selectinload(Project.episodes)).where(Project.id == uid)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 数据隔离：非全部范围用户只能访问自己创建的素材（无主项目=公共项目，人人可见）
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    return _serialize_project(project)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Update a project（数据隔离）. """
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.status is not None:
        project.status = data.status
    if data.config is not None:
        project.config = data.config
    project.updated_at = datetime.utcnow()

    await db.flush()
    await db.refresh(project)
    return _serialize_project(project)


async def _cleanup_episode_minio(episode) -> None:
    """清理单条剧集关联的 MinIO 对象（在 DB 删除前调用，避免级联删除后丢失引用）。

    - 源素材：episode.source_file_key（raw-footage 对象）
    - 切片成品：sliced/slices/{episode_id}/ 下所有对象
    """
    if episode.source_file_key:
        await delete_file(settings.MINIO_BUCKET_RAW, episode.source_file_key)
    try:
        sliced_objs = await list_files(
            settings.MINIO_BUCKET_SLICED, f"slices/{episode.id}/"
        )
        for obj in sliced_objs:
            await delete_file(settings.MINIO_BUCKET_SLICED, obj["key"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"清理剧集 MinIO 切片失败 (episode={episode.id}): {e}")


async def _cleanup_episode_media(db: AsyncSession, episode_id) -> None:
    """清理单条剧集关联的本地 media 文件（幂等，失败不阻塞删除，只记日志）。"""
    media_uuid = None
    try:
        ap = (
            await db.execute(
                select(AutoClipProject).where(AutoClipProject.episode_id == episode_id)
            )
        ).scalar_one_or_none()
        if ap and ap.autoclip_project_id:
            media_uuid = ap.autoclip_project_id
    except Exception as e:  # noqa: BLE001
        logger.warning(f"定位剧集 media 引用失败 (episode={episode_id}): {e}")
    if media_uuid:
        _cleanup_episode_media_files(media_uuid)
    # 兜底：清扫 media 卷中无 autoclip_projects 引用的孤儿文件
    await _cleanup_orphan_media_files()


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Delete a project and all its episodes（数据隔离）. """
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(Project).options(selectinload(Project.episodes)).where(Project.id == uid)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    # ── 清理 MinIO / 本地 media 文件资源（在 DB 删除前收集引用，避免级联删除后丢失） ──
    episodes = list(project.episodes or [])
    for ep in episodes:
        await _cleanup_episode_minio(ep)

    await db.delete(project)
    await db.flush()

    # DB 删除成功后执行本地 media 文件清理（失败不阻塞删除，只记日志）
    for ep in episodes:
        await _cleanup_episode_media(db, ep.id)

    # 兜底：清扫 raw-footage 桶中按项目前缀遗留的孤儿对象（上传 key 约定为
    # raw-footage/{project_id}/...，删除项目后若有未落库残留一并清掉）
    try:
        orphan_objs = await list_files(settings.MINIO_BUCKET_RAW, f"{uid}/")
        for obj in orphan_objs:
            await delete_file(settings.MINIO_BUCKET_RAW, obj["key"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"清理项目 raw-footage 孤儿对象失败 (project={uid}): {e}")


# ---------- Episode Routes ----------


@router.post("/projects/{project_id}/episodes", response_model=EpisodeResponse, status_code=201)
async def create_episode(
    project_id: str,
    data: EpisodeCreate,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Add an episode to a project（数据隔离）. """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    episode = Episode(
        project_id=pid,
        title=data.title,
        episode_no=data.episode_no,
        source_file_key=data.source_file_key,
        duration=data.duration,
        resolution=data.resolution,
        file_size=data.file_size,
    )
    db.add(episode)
    await db.flush()
    await db.refresh(episode)
    return _serialize_episode(episode)


@router.get("/projects/{project_id}/episodes", response_model=EpisodeListResponse)
async def list_episodes(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all episodes for a project（数据隔离）. """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Episode)
        .where(Episode.project_id == pid)
        .order_by(Episode.episode_no.asc().nullslast(), Episode.created_at.asc())
    )
    episodes = result.scalars().all()
    return {
        "items": [_serialize_episode(e) for e in episodes],
        "total": len(episodes),
    }


@router.get("/projects/{project_id}/outputs", response_model=ProjectOutputListResponse)
async def list_project_outputs(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """项目级成品预览：聚合项目下所有剧集的已完成切片任务产出（数据隔离）。

    供「剧集列表下方成品预览 Tab」一次拉全，避免逐剧集轮询。
    仅返回 completed 任务的成品，附带所属剧集信息便于按集展示。
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=404, detail="Project not found")

    # 取项目下所有剧集 + 已完成切片任务
    episodes_res = await db.execute(
        select(Episode).where(Episode.project_id == pid)
    )
    episodes = episodes_res.scalars().all()
    ep_ids = [e.id for e in episodes]
    ep_map = {str(e.id): e for e in episodes}

    if not ep_ids:
        return {"items": [], "total": 0}

    tasks_res = await db.execute(
        select(SliceTask)
        .where(SliceTask.episode_id.in_(ep_ids), SliceTask.status == "completed")
        .order_by(SliceTask.created_at.asc())
    )
    tasks = tasks_res.scalars().all()
    if not tasks:
        return {"items": [], "total": 0}
    task_ids = [t.id for t in tasks]
    task_map = {str(t.id): t for t in tasks}

    outputs_res = await db.execute(
        select(SliceOutput)
        .where(SliceOutput.task_id.in_(task_ids))
        .order_by(SliceOutput.created_at.asc())
    )
    outputs = outputs_res.scalars().all()

    items = []
    for out in outputs:
        task = task_map.get(str(out.task_id))
        if not task:
            continue
        episode = ep_map.get(str(task.episode_id))
        url = None
        if out.file_key:
            url = await get_presigned_url("sliced", out.file_key, expires_seconds=3600)
        items.append({
            "output_id": str(out.id),
            "task_id": str(out.task_id),
            "episode_id": str(task.episode_id),
            "episode_no": episode.episode_no if episode else None,
            "episode_title": episode.title if episode else None,
            "mode": task.mode,
            "task_status": task.status,
            "clip_id": str(out.clip_id) if out.clip_id else None,
            "file_key": out.file_key,
            "file_name": out.file_name,
            "duration": out.duration,
            "file_size": out.file_size,
            "resolution": out.resolution,
            "created_at": utc_iso(out.created_at) if out.created_at else "",
            "presigned_url": url,
        })

    return {"items": items, "total": len(items)}


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get an episode by ID（数据隔离）. 

    自愈：当剧集状态停留在 slicing 时，根据实际切片任务状态刷新（
    避免 Worker 回调丢失/异常导致"已切完还显示切片中"）。
    """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 数据隔离：通过剧集所属项目判断访问权限
    project = await db.execute(select(Project).where(Project.id == episode.project_id))
    proj = project.scalar_one_or_none()
    if proj and not _check_project_access(proj, current_user):
        raise HTTPException(status_code=404, detail="Episode not found")

    # 自愈：只有 slicing 状态才做任务状态核对，避免每次查询都额外开销
    if episode.status == "slicing":
        from app.models.models import SliceTask
        from sqlalchemy import or_

        tasks_res = await db.execute(
            select(SliceTask).where(
                SliceTask.episode_id == eid,
                or_(
                    SliceTask.mode.is_(None),
                    ~SliceTask.mode.like("detect_%"),
                ),
            )
        )
        all_tasks = tasks_res.scalars().all()
        if all_tasks:
            has_running = any(t.status in ("running", "pending") for t in all_tasks)
            has_completed = any(t.status == "completed" for t in all_tasks)
            has_failed = any(t.status in ("failed", "cancelled") for t in all_tasks)
            if not has_running:
                if has_completed:
                    episode.status = "completed"
                else:
                    episode.status = "failed"
                await db.flush()

    return _serialize_episode(episode)


class EpisodeUpdate(BaseModel):
    title: Optional[str] = None
    cover_image_key: Optional[str] = None


@router.put("/episodes/{episode_id}", response_model=EpisodeResponse)
async def update_episode(
    episode_id: str,
    data: EpisodeUpdate,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Update an episode（数据隔离）.

    当前支持更新标题与剧集封面（cover_image_key 按剧集独立存储，
    作为切片首帧叠加；传 null 即清除该集封面）。仅更新显式提供的字段。
    """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 数据隔离：通过剧集所属项目判断访问权限
    project = await db.execute(select(Project).where(Project.id == episode.project_id))
    proj = project.scalar_one_or_none()
    if proj and not _check_project_access(proj, current_user):
        raise HTTPException(status_code=404, detail="Episode not found")

    # 仅更新显式提供的字段（model_fields_set 区分「未传」与「传 null」，
    # 传 null 的 cover_image_key 表示清除该集封面）
    fields = data.model_fields_set
    if "title" in fields and data.title is not None:
        episode.title = data.title
    if "cover_image_key" in fields:
        episode.cover_image_key = data.cover_image_key

    episode.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(episode)
    return _serialize_episode(episode)



async def _fallback_download_task_url(db, eid):
    """孤儿下载任务的预览兜底：源直链优先，其次按 file_key 出 presigned URL。

    历史任务可能标记「下载并入库完成」，但项目/剧集记录与 MinIO 对象已被清理，
    按 episode 查必然 404。此时优先用任务保存的微信源直链（有时效），
    否则用 file_key（bucket 名已含在首段）按原逻辑生成 presigned URL。
    （163 local-overrides 热修收编入仓 2026-11-23）
    """
    import logging
    from sqlalchemy import text
    log = logging.getLogger(__name__)
    try:
        row = (await db.execute(text(
            "SELECT file_key, video_meta FROM wechat_download_tasks "
            "WHERE episode_id::text = :eid AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"eid": str(eid)})).mappings().first()
    except Exception as exc:  # noqa: BLE001
        log.warning("fallback download task query failed: %s", exc)
        return None
    if not row:
        return None
    meta = row.get("video_meta") or {}
    data = meta.get("data") if isinstance(meta, dict) else None
    src = (data or {}).get("url") if isinstance(data, dict) else None
    if isinstance(src, str) and src.startswith("http"):
        return src
    file_key = row.get("file_key") or ""
    if file_key:
        try:
            return await get_presigned_url(
                settings.MINIO_BUCKET_RAW, file_key, expires_seconds=3600
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("fallback presigned url failed: %s", exc)
    return None


@router.get("/episodes/{episode_id}/video-url")
async def get_episode_video_url(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned URL for the episode's source video for preview（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        # 孤儿下载任务：文件与剧集记录已不在，按 episode 查必然 404，走兜底取直链
        fallback = await _fallback_download_task_url(db, eid)
        if fallback:
            return {"url": fallback, "duration": None, "title": ""}
        raise HTTPException(status_code=404, detail="Episode not found")

    # 数据隔离
    project = await db.execute(select(Project).where(Project.id == episode.project_id))
    proj = project.scalar_one_or_none()
    if proj and not _check_project_access(proj, current_user):
        raise HTTPException(status_code=404, detail="Episode not found")

    if not episode.source_file_key:
        raise HTTPException(status_code=404, detail="Episode has no source video file")

    # 视频实际上传/存储于 raw-footage 桶（upload.py 使用 settings.MINIO_BUCKET_RAW），
    # 这里若用不存在的 "videos" 桶，presigned URL 生成会失败，导致片段审核页预览不可用。
    url = await get_presigned_url(settings.MINIO_BUCKET_RAW, episode.source_file_key, expires_seconds=3600)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to generate presigned URL")
    return {"url": url, "duration": episode.duration, "title": episode.title}


@router.delete("/episodes/{episode_id}", status_code=204)
async def delete_episode(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Delete an episode（数据隔离）. """
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    project = await db.execute(select(Project).where(Project.id == episode.project_id))
    proj = project.scalar_one_or_none()
    if proj and not _check_project_access(proj, current_user):
        raise HTTPException(status_code=404, detail="Episode not found")

    # ── 清理文件资源（在 DB 删除前收集引用，避免级联删除后丢失） ──
    await _cleanup_episode_minio(episode)

    await db.delete(episode)
    await db.flush()

    # DB 删除成功后执行本地文件清理（失败不阻塞删除，只记日志）
    # （场景：选点任务中途失败——autoclip 已下载视频副本到 media，但 DB 无
    # autoclip_projects 记录 → 上面按 media_uuid 定位不到 → 残留）
    await _cleanup_episode_media(db, eid)


async def _cleanup_orphan_media_files() -> None:
    """清扫 media 卷中无 autoclip_projects 引用的孤儿文件。

    keep 规则：media 文件名 = autoclip_project_id，autoclip_projects 表引用的
    即现存剧集的副本，必须保留；其余（历史已删剧集/选点失败残留）全部清理。
    覆盖：{uuid}.mp4、data/output/metadata/{uuid}/、data/asr_cache/{uuid}-*
    """
    media_base = Path("/app/media")
    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(AutoClipProject.autoclip_project_id).where(
                        AutoClipProject.autoclip_project_id.is_not(None)
                    )
                )
            ).scalars().all()
            # 事务内只读：显式结束事务，避免把 idle in transaction 的连接归还连接池
            await session.rollback()
        keep = set(rows)
        removed = 0
        for p in media_base.glob("*.mp4"):
            if p.stem not in keep:
                _remove_path(p)
                removed += 1
        metadata_dir = media_base / "data/output/metadata"
        if metadata_dir.is_dir():
            for d in metadata_dir.glob("*"):
                if d.is_dir() and d.name not in keep:
                    _remove_path(d)
                    removed += 1
        asr_dir = media_base / "data/asr_cache"
        if asr_dir.is_dir():
            for f in asr_dir.glob("*"):
                prefix = f.name.split("-")[0]
                if prefix and prefix not in keep:
                    _remove_path(f)
                    removed += 1
        if removed:
            logger.info(f"已清扫 media 孤儿文件 {removed} 个")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"清扫 media 孤儿文件失败: {e}")


def _cleanup_episode_media_files(media_uuid: str) -> None:
    """清理剧集删除后遗留的本地 media 文件与 MinIO raw-footage 残留对象。

    media 卷挂载在 backend 容器 /app/media：
      - {media_uuid}.mp4           源视频副本（autoclip 上传/下载生成）
      - data/output/metadata/{uuid} AI 选点产物
      - data/asr_cache/{uuid}-*    ASR 转写缓存
      - data/output/frame_cache/*  画面理解帧缓存（按视频 hash 命名，删除该剧集全部帧缓存）
    """
    media_base = Path("/app/media")
    try:
        for p in [
            media_base / f"{media_uuid}.mp4",
            media_base / "data/output/metadata" / media_uuid,
        ]:
            _remove_path(p)
        for p in media_base.glob(f"data/asr_cache/{media_uuid}-*"):
            _remove_path(p)
        for p in media_base.glob("data/output/frame_cache/*"):
            _remove_path(p)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"清理剧集本地文件失败: {e}")

# ── 原片素材二次处理（2026-11-23 用户需求：上传后可手动降档到 720P@30）──
# 状态存进程内存（backend 单进程）：{episode_id: {"status": "...", "message": "..."}}
_src_norm_jobs: dict = {}


@router.post("/episodes/{episode_id}/source/normalize")
async def normalize_episode_source(
    episode_id: str,
    tier: str = Query("720p"),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """tier 档位与切片输出档位同语义（仅降档不升档）：
    original=不处理 / auto=宽>720 或 fps>30 才降 / 1080p / 720p（默认）/ 480p。"""
    """把本剧集原片归一化到 720P@30（等比降档+降帧，音频直拷）。

    - 已符合（宽≤720 且 fps≤30）→ 直接返回 compliant，不转码
    - 该剧集有运行中的切片/选点任务 → 拒绝（409，防替换源片打断渲染/选点）
    - 后台异步转码；进度与结果走 GET 同路径查询
    """
    if _src_norm_jobs.get(episode_id, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="该剧集原片已在降档处理中")
    result = await db.execute(
        select(Episode, SliceTask)
        .outerjoin(SliceTask, SliceTask.episode_id == Episode.id)
        .where(Episode.id == episode_id)
        .limit(1)
    )
    row = result.first()
    episode = row[0] if row else None
    if episode is None:
        raise HTTPException(status_code=404, detail="剧集不存在")
    running_task = await db.execute(
        select(func.count(SliceTask.id)).where(
            SliceTask.episode_id == episode_id,
            SliceTask.status.in_(("running", "pending", "processing")),
        )
    )
    if (running_task.scalar_one() or 0) > 0:
        raise HTTPException(status_code=409, detail="该剧集有运行中的切片任务，降档会替换源片——请等任务完成")
    if not episode.source_file_key:
        raise HTTPException(status_code=404, detail="该剧集没有已上传的原片")

    _src_norm_jobs[episode_id] = {"status": "running", "message": "下载源片到本地", "old_key": episode.source_file_key}

    async def _run():
        import asyncio as _aio
        tmp_dir = f"/tmp/srcnorm_{episode_id[:8]}"
        os.makedirs(tmp_dir, exist_ok=True)
        src_path = os.path.join(tmp_dir, "source.mp4")
        dst_path = os.path.join(tmp_dir, "source_720p30.mp4")
        try:
            from app.services.minio_service import download_file as _dl
            _data = await _dl(settings.MINIO_BUCKET_RAW, episode.source_file_key)
            with open(src_path, "wb") as _f:
                _f.write(_data)
            _src_norm_jobs[episode_id]["message"] = "探测规格"
            probe = await _aio.to_thread(probe_media, src_path)
            if not probe:
                _src_norm_jobs[episode_id] = {"status": "failed", "message": "ffprobe 探测失败（文件损坏？）"}
                return
            _TIER_CAPS = {"auto": (720, 30), "1080p": (1080, 60), "720p": (720, 30), "480p": (480, 30)}
            cap_w, cap_fps = _TIER_CAPS.get(tier.lower(), _TIER_CAPS["720p"])
            _src_norm_jobs[episode_id]["message"] = (
                f"探测规格：{probe['width']}x{probe['height']}@{probe['fps']:.0f}fps，目标档位 {tier}")
            if not needs_normalize(probe, cap_w=cap_w, cap_fps=cap_fps):
                _src_norm_jobs[episode_id] = {
                    "status": "compliant",
                    "message": f"已符合档位 {tier}（{probe['width']}x{probe['height']} @{probe['fps']:.0f}fps），无需处理",
                }
                return
            _src_norm_jobs[episode_id]["message"] = (
                f"转码中：{probe['width']}x{probe['height']}@{probe['fps']:.0f}fps → 档位 {tier}")
            ok = await _aio.to_thread(normalize_media_file, src_path, dst_path, cap_w=cap_w, cap_fps=cap_fps)
            if not ok:
                _src_norm_jobs[episode_id] = {"status": "failed", "message": "ffmpeg 转码失败（保留原片不变）"}
                return
            _src_norm_jobs[episode_id]["message"] = "上传新源片"
            old_key = episode.source_file_key
            base, _, ext = old_key.rpartition(".")
            new_key = f"{base or old_key}_{tier.lower()}.{ext or 'mp4'}"
            from app.services.minio_service import upload_file_from_path as _up
            # 修复（2026-11-23）：upload/delete 是协程函数——此前误塞 to_thread 只创建
            # 协程对象从未执行，假真值导致「已完成」但对象根本没上传
            up_ok = await _up(settings.MINIO_BUCKET_RAW, new_key, dst_path, "video/mp4")
            logger.info("降档上传：bucket=%s key=%s ok=%s size=%s",
                        settings.MINIO_BUCKET_RAW, new_key, up_ok,
                        os.path.getsize(dst_path) if os.path.exists(dst_path) else "gone")
            if not up_ok:
                _src_norm_jobs[episode_id] = {"status": "failed", "message": "新源片上传失败（保留原片不变）"}
                return
            # 原子更新源指针 + 删旧对象省存储
            async with async_session_factory() as wdb:
                wrow = await wdb.execute(select(Episode).where(Episode.id == episode.id))
                wep = wrow.scalar_one_or_none()
                if wep is not None:
                    wep.source_file_key = new_key
                    await wdb.commit()
            try:
                from app.services.minio_service import delete_file as _del
                await _del(settings.MINIO_BUCKET_RAW, old_key)
            except Exception:
                pass
            old_size = os.path.getsize(src_path)
            new_size = os.path.getsize(dst_path)
            _src_norm_jobs[episode_id] = {
                "status": "completed",
                "message": f"已完成：{probe['width']}x{probe['height']}@{probe['fps']:.0f}fps → 档位 {tier}，"
                           f"{old_size // (1024*1024)}MB → {new_size // (1024*1024)}MB",
            }
        except Exception as e:  # noqa: BLE001
            _src_norm_jobs[episode_id] = {"status": "failed", "message": f"处理异常：{str(e)[:160]}"}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    import asyncio as _aio
    _aio.get_event_loop().create_task(_run())
    return {"status": "running", "message": "降档处理已启动"}


@router.get("/episodes/{episode_id}/source/normalize")
async def get_source_normalize_status(
    episode_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    return _src_norm_jobs.get(episode_id, {"status": "idle", "message": None})
