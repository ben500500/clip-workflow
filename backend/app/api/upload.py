import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Project, Episode
from app.services.upload_service import (
    create_upload_session,
    write_chunk,
    get_upload_progress,
    delete_upload_session,
    finalize_upload,
    validate_file_name,
)
from app.services.minio_service import upload_file_from_path

logger = logging.getLogger(__name__)

router = APIRouter()


class UploadResumeRequest(BaseModel):
    file_name: str
    file_size: int
    chunk_size: Optional[int] = 5 * 1024 * 1024
    metadata: Optional[dict] = {}


class UploadResumeResponse(BaseModel):
    id: str
    file_name: str
    file_size: int
    chunk_size: int
    offset: int
    metadata: dict


class UploadProgressResponse(BaseModel):
    id: str
    file_name: str
    file_size: int
    offset: int
    completed: bool
    progress_pct: float


class UploadCompleteRequest(BaseModel):
    upload_id: str
    project_id: str
    title: Optional[str] = None
    episode_no: Optional[int] = None


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


async def _store_uploaded_file(
    upload_id: str,
    project_id: uuid.UUID,
    file_name: str,
    file_size: int,
    db: AsyncSession,
    title: Optional[str] = None,
    episode_no: Optional[int] = None,
) -> Episode:
    """Finalize an upload session into MinIO and create an Episode record."""
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    safe_name = validate_file_name(file_name)
    local_path = f"/tmp/uploads/{upload_id}_final.mp4"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    result_path = finalize_upload(upload_id, local_path)
    if not result_path:
        raise HTTPException(status_code=400, detail="Upload session is not complete or invalid")

    file_key = f"raw-footage/{project_id}/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(settings.MINIO_BUCKET_RAW, file_key, result_path)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to store file in object storage")

    episode = Episode(
        project_id=project_id,
        title=title or safe_name,
        episode_no=episode_no,
        source_file_key=file_key,
        file_size=file_size,
        status="uploaded",
    )
    db.add(episode)
    await db.flush()
    await db.refresh(episode)

    delete_upload_session(upload_id)
    return episode


@router.post("/upload/resume", response_model=UploadResumeResponse, status_code=201)
async def create_upload(data: UploadResumeRequest):
    """Create a new upload session (tus-like resume protocol)."""
    if data.file_size <= 0:
        raise HTTPException(status_code=400, detail="file_size must be positive")
    if data.file_size > settings.UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=400, detail="file_size exceeds maximum allowed")

    try:
        validate_file_name(data.file_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    session = create_upload_session(
        file_name=data.file_name,
        file_size=data.file_size,
        chunk_size=data.chunk_size,
        metadata=data.metadata,
    )
    return UploadResumeResponse(
        id=session["id"],
        file_name=session["file_name"],
        file_size=session["file_size"],
        chunk_size=session["chunk_size"],
        offset=session["offset"],
        metadata=session["metadata"],
    )


@router.head("/upload/{upload_id}", response_model=None)
async def get_upload_info(
    upload_id: str,
    tus_resumable: Optional[str] = Header(None, alias="Tus-Resumable"),
):
    """Query upload progress (HEAD request, tus-compatible)."""
    progress = get_upload_progress(upload_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Upload session not found")

    from fastapi.responses import Response
    response = Response()
    response.headers["Upload-Offset"] = str(progress["offset"])
    response.headers["Upload-Length"] = str(progress["file_size"])
    if tus_resumable:
        response.headers["Tus-Resumable"] = tus_resumable
    return response


@router.patch("/upload/{upload_id}", response_model=UploadProgressResponse)
async def upload_chunk(
    upload_id: str,
    request: Request,
    upload_offset: Optional[str] = Header(None, alias="Upload-Offset"),
):
    """Upload a chunk of data (PATCH request, tus-compatible)."""
    offset = 0
    if upload_offset is not None:
        try:
            offset = int(upload_offset)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Upload-Offset header")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    new_offset = write_chunk(upload_id, body, offset)
    if new_offset is None:
        raise HTTPException(status_code=400, detail="Chunk upload failed (offset mismatch or invalid session)")

    progress = get_upload_progress(upload_id)
    return UploadProgressResponse(
        id=progress["id"],
        file_name=progress["file_name"],
        file_size=progress["file_size"],
        offset=progress["offset"],
        completed=progress["completed"],
        progress_pct=progress["progress_pct"],
    )


@router.get("/upload/{upload_id}/progress", response_model=UploadProgressResponse)
async def get_upload_progress_endpoint(upload_id: str):
    """Get the current upload progress."""
    progress = get_upload_progress(upload_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Upload session not found")
    return UploadProgressResponse(
        id=progress["id"],
        file_name=progress["file_name"],
        file_size=progress["file_size"],
        offset=progress["offset"],
        completed=progress["completed"],
        progress_pct=progress["progress_pct"],
    )


@router.post("/upload/complete")
async def complete_upload(
    data: UploadCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Finalize a tus upload session into an Episode."""
    try:
        pid = uuid.UUID(data.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    progress = get_upload_progress(data.upload_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if not progress["completed"]:
        raise HTTPException(status_code=400, detail="Upload session is not complete")

    episode = await _store_uploaded_file(
        data.upload_id,
        pid,
        progress["file_name"],
        progress["file_size"],
        db,
        title=data.title,
        episode_no=data.episode_no,
    )
    return _serialize_episode(episode)


@router.post("/upload", status_code=201)
async def upload_single(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    title: Optional[str] = Form(None),
    episode_no: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Simple single-request upload: stores the file and creates an Episode."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    try:
        safe_name = validate_file_name(file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upload_id = str(uuid.uuid4())
    local_path = f"/tmp/uploads/{upload_id}.bin"
    os.makedirs("/tmp/uploads", exist_ok=True)
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
                raise HTTPException(status_code=413, detail="File exceeds maximum allowed size")
            out.write(chunk)

    file_key = f"raw-footage/{pid}/{upload_id}_{safe_name}"
    ok = await upload_file_from_path(settings.MINIO_BUCKET_RAW, file_key, local_path)
    if not ok:
        os.unlink(local_path)
        raise HTTPException(status_code=500, detail="Failed to store file in object storage")
    os.unlink(local_path)

    episode = Episode(
        project_id=pid,
        title=title or safe_name,
        episode_no=episode_no,
        source_file_key=file_key,
        file_size=size,
        status="uploaded",
    )
    db.add(episode)
    await db.flush()
    await db.refresh(episode)
    return _serialize_episode(episode)


@router.delete("/upload/{upload_id}", status_code=204)
async def cancel_upload(upload_id: str):
    """Cancel and delete an upload session."""
    if not delete_upload_session(upload_id):
        raise HTTPException(status_code=404, detail="Upload session not found")
