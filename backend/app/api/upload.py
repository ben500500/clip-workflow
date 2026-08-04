import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel

from app.services.upload_service import (
    create_upload_session,
    write_chunk,
    get_upload_progress,
    delete_upload_session,
)

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


@router.post("/upload/resume", response_model=UploadResumeResponse, status_code=201)
async def create_upload(data: UploadResumeRequest):
    """Create a new upload session (tus-like resume protocol).

    The client initiates an upload by providing file metadata.
    Returns an upload ID that the client uses for subsequent chunk uploads.
    """
    if data.file_size <= 0:
        raise HTTPException(status_code=400, detail="file_size must be positive")
    if data.file_size > 50 * 1024 * 1024 * 1024:  # 50GB limit
        raise HTTPException(status_code=400, detail="file_size exceeds maximum allowed (50GB)")

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
    request: Request,
    tus_resumable: Optional[str] = Header(None, alias="Tus-Resumable"),
):
    """Query upload progress (HEAD request, tus-compatible).

    Returns the current upload offset in the Upload-Offset header.
    """
    progress = get_upload_progress(upload_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Upload session not found")

    # Return tus-compatible headers
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
    content_type: Optional[str] = Header(None),
):
    """Upload a chunk of data (PATCH request, tus-compatible).

    The client sends the chunk data in the request body and specifies
    the expected offset via the Upload-Offset header.
    """
    # Get offset from header or body parameter
    if upload_offset is not None:
        try:
            offset = int(upload_offset)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Upload-Offset header")
    else:
        # Try to get from query parameter
        offset = 0

    # Read body
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


@router.delete("/upload/{upload_id}", status_code=204)
async def cancel_upload(upload_id: str):
    """Cancel and delete an upload session."""
    if not delete_upload_session(upload_id):
        raise HTTPException(status_code=404, detail="Upload session not found")