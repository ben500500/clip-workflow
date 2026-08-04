import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Project, Episode

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


# ---------- Helper ----------

def _serialize_project(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "config": project.config or {},
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
        "episode_count": len(project.episodes) if project.episodes else 0,
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
        "created_at": episode.created_at.isoformat() if episode.created_at else "",
        "updated_at": episode.updated_at.isoformat() if episode.updated_at else "",
    }


# ---------- Project Routes ----------


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new project."""
    project = Project(
        name=data.name,
        description=data.description,
        config=data.config or {},
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return _serialize_project(project)


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """List all projects."""
    result = await db.execute(
        select(Project).offset(skip).limit(limit).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return [_serialize_project(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get a project by ID."""
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _serialize_project(project)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a project."""
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
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


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a project and all its episodes."""
    try:
        uid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == uid))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await db.delete(project)
    await db.flush()


# ---------- Episode Routes ----------


@router.post("/projects/{project_id}/episodes", response_model=EpisodeResponse, status_code=201)
async def create_episode(
    project_id: str,
    data: EpisodeCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add an episode to a project."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if not project:
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
    db: AsyncSession = Depends(get_db),
):
    """List all episodes for a project."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

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


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: str, db: AsyncSession = Depends(get_db)):
    """Get an episode by ID."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return _serialize_episode(episode)


@router.delete("/episodes/{episode_id}", status_code=204)
async def delete_episode(episode_id: str, db: AsyncSession = Depends(get_db)):
    """Delete an episode."""
    try:
        eid = uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode ID format")

    result = await db.execute(select(Episode).where(Episode.id == eid))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    await db.delete(episode)
    await db.flush()