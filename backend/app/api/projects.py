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
    AutoClipRun,
    SliceTask,
    SliceOutput,
    DetectedInterval,
    user_can_access_all_materials,
)
from app.services.data_scope import check_project_access_by_episode
from app.api.slice_helpers import _not_detect_task, _serialize_output
from app.services.minio_service import get_presigned_url, delete_file, list_files
from app.utils.helpers import utc_iso

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
        "duration": episode.duration,
        "resolution": episode.resolution,
        "file_size": episode.file_size,
        "status": episode.status,
        "created_at": utc_iso(episode.created_at) if episode.created_at else "",
        "updated_at": utc_iso(episode.updated_at) if episode.updated_at else "",
    }


# ---------- Project Routes ----------


def _data_scope_filter(current_user: User):
    """数据隔离：返回用户可见项目的过滤条件。

    - admin/material/publisher：默认可见全部素材
    - operator：默认仅可见自己创建的素材；管理员可通过权限编辑授予 all
    """
    if user_can_access_all_materials(current_user):
        return None
    return Project.created_by == current_user.id


def _check_project_access(project: Project, current_user: User) -> bool:
    """数据隔离：判断当前用户是否可访问该项目。"""
    if user_can_access_all_materials(current_user):
        return True
    return project.created_by == current_user.id


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

    # 数据隔离：非全部范围用户只能访问自己创建的素材
    if not user_can_access_all_materials(current_user) and project.created_by != current_user.id:
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



@router.get("/projects/{project_id}/workflow-status")
async def project_workflow_status(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """项目级工作流状态聚合（P2-4）。

    聚合项目下所有剧集在「选点 autoclip / 区间检测 detect / 切片 slice」
    三个阶段的实时状态与进度，供自动化流程与前端看板一次拿全，避免逐剧集轮询。
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _check_project_access(project, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")

    # 预取项目下所有剧集
    episodes = (
        await db.execute(
            select(Episode)
            .where(Episode.project_id == pid)
            .order_by(Episode.episode_no, Episode.created_at)
        )
    ).scalars().all()
    episode_ids = [e.id for e in episodes]

    # 批量拉取各阶段数据（避免 N+1）
    autoclip_runs = []
    slice_tasks = []
    detect_counts = {}
    if episode_ids:
        autoclip_runs = (
            await db.execute(
                select(AutoClipRun)
                .where(AutoClipRun.episode_id.in_(episode_ids))
                .order_by(AutoClipRun.created_at)
            )
        ).scalars().all()
        slice_tasks = (
            await db.execute(
                select(SliceTask)
                .where(SliceTask.episode_id.in_(episode_ids))
                .where(_not_detect_task())
                .order_by(SliceTask.created_at)
            )
        ).scalars().all()
        detect_rows = (
            await db.execute(
                select(SliceTask.episode_id, func.count())
                .where(SliceTask.episode_id.in_(episode_ids))
                .where(SliceTask.mode.like("detect_%"))
                .group_by(SliceTask.episode_id)
            )
        ).all()
        detect_counts = {str(r[0]): r[1] for r in detect_rows}

    def _stage_status(status: Optional[str]) -> str:
        """归一化各阶段状态到 small 集合。"""
        s = (status or "pending").lower()
        if s in ("completed", "success"):
            return "completed"
        if s in ("failed", "cancelled"):
            return "failed"
        if s in ("running", "processing", "uploading"):
            return "running"
        if s in ("pending", "parsing", "downloading", "queued"):
            return "pending"
        return "unknown"

    episodes_payload = []
    stage_done = [0, 0, 0]  # autoclip/detect/slice 完成数
    total_episodes = len(episodes)
    for ep in episodes:
        eid = ep.id
        # 选点：取最新一次 AutoClipRun
        run = next(
            (r for r in autoclip_runs if r.episode_id == eid),
            None,
        )
        # 切片：取最新一条
        task = next(
            (t for t in slice_tasks if t.episode_id == eid),
            None,
        )
        detect_count = detect_counts.get(str(eid), 0)
        detect_status = "completed" if detect_count > 0 else "pending"

        autoclip_stage = {
            "status": _stage_status(run.status if run else None),
            "progress": (run.progress or 0) if run else 0,
            "message": run.message if run and run.status else ("未启动选点" if not run else ""),
            "run_count": sum(1 for r in autoclip_runs if r.episode_id == eid),
        }
        slice_stage = {
            "status": _stage_status(task.status if task else None),
            "progress": (task.progress or 0) if task else 0,
            "message": task.error_message if task and task.status == "failed" else ("未启动切片" if not task else ""),
            "task_count": sum(1 for t in slice_tasks if t.episode_id == eid),
            "output_count": task.output_count if task else 0,
        }
        detect_stage = {
            "status": detect_status,
            "progress": 100.0 if detect_status == "completed" else 0,
            "interval_count": detect_count,
        }

        # 剧集总状态：任一阶段 running → running；全部 completed → completed；
        # 任一 failed → failed；有 pending/unknown → pending
        stage_statuses = [autoclip_stage["status"], detect_stage["status"], slice_stage["status"]]
        if any(s == "running" for s in stage_statuses):
            ep_status = "running"
        elif all(s == "completed" for s in stage_statuses):
            ep_status = "completed"
        elif any(s == "failed" for s in stage_statuses):
            ep_status = "failed"
        else:
            ep_status = "pending"

        # 统计各阶段完成数
        if autoclip_stage["status"] == "completed":
            stage_done[0] += 1
        if detect_stage["status"] == "completed":
            stage_done[1] += 1
        if slice_stage["status"] == "completed":
            stage_done[2] += 1

        episodes_payload.append(
            {
                "episode": {
                    "id": str(eid),
                    "title": ep.title,
                    "episode_no": ep.episode_no,
                    "duration": ep.duration,
                    "status": ep.status,
                },
                "status": ep_status,
                "stages": {
                    "autoclip": autoclip_stage,
                    "detect": detect_stage,
                    "slice": slice_stage,
                },
            }
        )

    # 项目整体状态
    if total_episodes == 0:
        overall_status = "empty"
        overall_progress = 0.0
    elif all(e["status"] == "completed" for e in episodes_payload):
        overall_status = "completed"
        overall_progress = 100.0
    elif any(e["status"] == "running" for e in episodes_payload):
        overall_status = "running"
        overall_progress = round(sum(e["status"] == "completed" for e in episodes_payload) / total_episodes * 100, 1)
    elif any(e["status"] == "failed" for e in episodes_payload):
        overall_status = "failed"
        overall_progress = round(sum(e["status"] == "completed" for e in episodes_payload) / total_episodes * 100, 1)
    else:
        overall_status = "pending"
        overall_progress = 0.0

    return {
        "project_id": str(pid),
        "project_name": project.name,
        "overall": {
            "status": overall_status,
            "progress": overall_progress,
            "total_episodes": total_episodes,
            "completed_episodes": sum(1 for e in episodes_payload if e["status"] == "completed"),
            "stages": {
                "autoclip": {"completed": stage_done[0], "total": total_episodes},
                "detect": {"completed": stage_done[1], "total": total_episodes},
                "slice": {"completed": stage_done[2], "total": total_episodes},
            },
        },
        "episodes": episodes_payload,
    }


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