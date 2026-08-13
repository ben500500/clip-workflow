import io
import logging
import os
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import SliceOutput, SliceTask, Episode, User
from app.services.data_scope import check_project_access_by_episode
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


class BatchDownloadItem(BaseModel):
    output_id: str
    file_name: str
    url: str


class BatchDownloadResponse(BaseModel):
    files: List[BatchDownloadItem]


async def _check_output_scope(db: AsyncSession, output: SliceOutput, current_user: User):
    """数据隔离：根据输出文件所属切片任务 → 剧集 → 项目校验访问权限."""
    if current_user is None:
        raise HTTPException(status_code=404, detail="Output not found")
    task = (
        await db.execute(select(SliceTask).where(SliceTask.id == output.task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Output not found")
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)


@router.get("/outputs/{output_id}/preview/frames")
async def preview_frames(
    output_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get preview frame URLs for a slice output（数据隔离）. """
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    # 数据隔离
    await _check_output_scope(db, output, current_user)

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
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned video URL for preview（数据隔离）. """
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    # 数据隔离
    await _check_output_scope(db, output, current_user)

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
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned download URL for a single output（数据隔离）.

    返回 JSON 直链（带 Content-Disposition: attachment），由前端拿到后触发下载；
    不直接 302 跳转，因为前端 a 标签导航无法携带 Authorization header。
    """
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    # 数据隔离
    await _check_output_scope(db, output, current_user)

    if not output.file_key:
        raise HTTPException(status_code=400, detail="Output has no file key")

    file_name = output.file_name or f"output_{str(output.id)[:8]}.mp4"
    url = await get_presigned_url(
        "sliced",
        output.file_key,
        expires_seconds=7200,
        as_attachment=True,
        filename=file_name,
    )
    if not url:
        # Fallback: try to download and stream directly
        data = await download_file("sliced", output.file_key)
        if data is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve file")

        return StreamingResponse(
            io.BytesIO(data),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{file_name}"',
                "Content-Length": str(len(data)),
            },
        )

    return {"url": url, "file_name": file_name}


async def _cleanup_tmp(path: str):
    """Remove a temporary file after the response is sent."""
    try:
        os.unlink(path)
    except OSError:
        pass


@router.post("/outputs/batch-download")
async def batch_download(
    data: BatchDownloadRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """批量下载：返回每个输出文件的直链列表，由前端按顺序逐个下载（不再打包 ZIP，数据隔离）. """
    if not data.output_ids:
        raise HTTPException(status_code=400, detail="No output IDs provided")

    if len(data.output_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="Cannot batch download more than 100 files at once",
        )

    # 逐个生成 presigned 直链，跳过无效/无文件的输出（含越权项）
    files: List[BatchDownloadItem] = []
    for oid_str in data.output_ids:
        try:
            oid = uuid.UUID(oid_str)
        except ValueError:
            continue

        result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
        output = result.scalar_one_or_none()
        if not output or not output.file_key:
            continue

        # 数据隔离：越权项直接跳过
        try:
            await _check_output_scope(db, output, current_user)
        except HTTPException:
            continue

        file_name = output.file_name or f"output_{str(output.id)[:8]}.mp4"
        url = await get_presigned_url(
            "sliced",
            output.file_key,
            expires_seconds=7200,
            as_attachment=True,
            filename=file_name,
        )
        if not url:
            logger.warning("Failed to generate presigned URL for %s", output.file_key)
            continue

        files.append(
            BatchDownloadItem(
                output_id=str(output.id),
                file_name=file_name,
                url=url,
            )
        )

    if not files:
        raise HTTPException(status_code=404, detail="No valid outputs found")

    return BatchDownloadResponse(files=files)