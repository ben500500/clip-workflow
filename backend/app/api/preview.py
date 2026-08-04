import io
import logging
import os
import uuid
import zipfile
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import SliceOutput, SliceTask
from app.services.minio_service import (
    get_presigned_url,
    download_file,
    list_files,
    get_file_info,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class BatchDownloadRequest(BaseModel):
    output_ids: List[str]


class BatchDownloadResponse(BaseModel):
    download_url: str
    file_count: int
    total_size: int


@router.get("/outputs/{output_id}/preview/frames")
async def preview_frames(
    output_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get preview frame URLs for a slice output."""
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    if not output.file_key:
        raise HTTPException(status_code=400, detail="Output has no file key")

    # Look for preview frames in the previews bucket
    preview_prefix = f"previews/{output.file_key.replace('.mp4', '/')}"
    frames = await list_files("previews", prefix=preview_prefix)

    frame_urls = []
    for frame in frames:
        url = await get_presigned_url("previews", frame["key"], expires_seconds=3600)
        if url:
            frame_urls.append({
                "key": frame["key"],
                "url": url,
                "size": frame["size"],
            })

    # If no preview frames exist, generate a placeholder
    if not frame_urls:
        # Return a single frame from the video itself
        video_url = await get_presigned_url("sliced", output.file_key, expires_seconds=3600)
        frame_urls = [{
            "key": output.file_key,
            "url": video_url,
            "size": output.file_size,
            "note": "Direct video URL (no preview frames generated)",
        }]

    return {
        "output_id": output_id,
        "frames": frame_urls,
        "count": len(frame_urls),
    }


@router.get("/outputs/{output_id}/preview/video")
async def preview_video(
    output_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned video URL for preview."""
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    if not output.file_key:
        raise HTTPException(status_code=400, detail="Output has no file key")

    url = await get_presigned_url("sliced", output.file_key, expires_seconds=3600)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to generate presigned URL")

    return {
        "output_id": output_id,
        "url": url,
        "file_name": output.file_name,
        "duration": output.duration,
        "file_size": output.file_size,
        "expires_in_seconds": 3600,
    }


@router.get("/outputs/{output_id}/download")
async def download_output(
    output_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a single output file via presigned URL."""
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    if not output.file_key:
        raise HTTPException(status_code=400, detail="Output has no file key")

    url = await get_presigned_url("sliced", output.file_key, expires_seconds=7200)
    if not url:
        # Fallback: try to download and stream directly
        data = await download_file("sliced", output.file_key)
        if data is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve file")

        return StreamingResponse(
            io.BytesIO(data),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{output.file_name or "output.mp4"}"',
                "Content-Length": str(len(data)),
            },
        )

    # Redirect to presigned URL
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=url)


@router.post("/outputs/batch-download", response_model=BatchDownloadResponse)
async def batch_download(
    data: BatchDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    """Batch download multiple outputs as a ZIP file."""
    if not data.output_ids:
        raise HTTPException(status_code=400, detail="No output IDs provided")

    if len(data.output_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="Cannot batch download more than 100 files at once",
        )

    # Collect all output records
    outputs = []
    for oid_str in data.output_ids:
        try:
            oid = uuid.UUID(oid_str)
        except ValueError:
            continue

        result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
        output = result.scalar_one_or_none()
        if output and output.file_key:
            outputs.append(output)

    if not outputs:
        raise HTTPException(status_code=404, detail="No valid outputs found")

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    total_size = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for output in outputs:
            data = await download_file("sliced", output.file_key)
            if data:
                file_name = output.file_name or f"output_{output.id}.mp4"
                zf.writestr(file_name, data)
                total_size += len(data)

    zip_buffer.seek(0)

    # Return as streaming response
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="batch_download_{uuid.uuid4().hex[:8]}.zip"',
            "Content-Length": str(zip_buffer.getbuffer().nbytes),
        },
    )