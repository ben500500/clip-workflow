import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import Project, Episode, User
from app.services.upload_service import (
    create_upload_session,
    write_chunk,
    get_upload_progress,
    delete_upload_session,
    finalize_upload,
    validate_file_name,
)
from app.services.minio_service import upload_file_from_path
from app.utils.helpers import utc_iso

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


class MultiUploadResponse(BaseModel):
    project_id: str
    project_name: str
    episodes: List[dict]
    message: str


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


async def _check_project_access(project: Project, current_user: User):
    """数据隔离：上传素材前校验项目访问权限（运营专员仅可向自己创建的项目上传）. """
    if current_user is None:
        raise HTTPException(status_code=404, detail="Project not found")
    from app.models.models import user_can_access_all_materials
    if user_can_access_all_materials(current_user):
        return
    if project.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")


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
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Finalize a tus upload session into an Episode（数据隔离）. """
    try:
        pid = uuid.UUID(data.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    progress = get_upload_progress(data.upload_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if not progress["completed"]:
        raise HTTPException(status_code=400, detail="Upload session is not complete")

    # 数据隔离
    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await _check_project_access(project, current_user)

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
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Simple single-request upload: stores the file and creates an Episode（数据隔离）. """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # 数据隔离
    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await _check_project_access(project, current_user)

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


@router.post("/upload/multi", status_code=201)
async def upload_multi(
    files: List[UploadFile] = File(...),
    project_name: str = Form(...),
    merge: str = Form("false"),
    description: Optional[str] = Form(None),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """多视频批量上传正片（数据隔离）。

    - merge=false：每个视频分别创建一条 Episode（按顺序编号）；
    - merge=true：先用 ffmpeg concat 把多个视频拼接成一个，再创建一条 Episode
      （作为「正片」整体进入 AI 选点/切片流水线）。项目名称由用户输入。
    - 项目按「名称 + 当前用户」查找：已存在则追加剧集（保留原剧集，编号顺延），
      不存在才新建，避免同名重复项目覆盖原剧集。
    """
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一个视频")
    project_name = (project_name or "").strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    # 数据隔离：按项目名查找当前用户已有项目，存在则追加剧集（保留原剧集），
    # 不存在才新建，避免产生同名重复项目把原剧集「冲掉」。
    stmt = select(Project).where(Project.name == project_name)
    if current_user is not None:
        stmt = stmt.where(Project.created_by == current_user.id)
    stmt = stmt.order_by(Project.created_at.asc())
    res = await db.execute(stmt)
    project = res.scalars().first()

    created_new = project is None
    if created_new:
        project = Project(
            name=project_name,
            description=description or "多视频批量上传创建",
            config={"source": "multi_upload"},
            created_by=current_user.id if current_user else None,
        )
        db.add(project)
        await db.flush()
        await db.refresh(project)

    # 已有最大剧集号：新剧集在其后连续编号，避免与原有剧集号冲突
    base_res = await db.execute(
        select(func.coalesce(func.max(Episode.episode_no), 0)).where(Episode.project_id == project.id)
    )
    base_episode_no = base_res.scalar_one()

    # 校验文件扩展名并落盘到临时目录
    tmp_dir = f"/tmp/uploads/multi_{uuid.uuid4().hex}"
    os.makedirs(tmp_dir, exist_ok=True)
    local_paths: List[str] = []
    names: List[str] = []
    try:
        for f in files:
            try:
                safe_name = validate_file_name(f.filename or "")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            p = os.path.join(tmp_dir, safe_name)
            size = 0
            with open(p, "wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > settings.UPLOAD_MAX_SIZE:
                        raise HTTPException(status_code=413, detail=f"{safe_name} 超过最大上传大小")
                    out.write(chunk)
            local_paths.append(p)
            names.append(safe_name)

        do_merge = str(merge).strip().lower() in ("1", "true", "yes")
        if do_merge and len(local_paths) > 1:
            merged_path = os.path.join(tmp_dir, f"merged_{uuid.uuid4().hex}.mp4")
            merged = await _ffmpeg_concat(local_paths, merged_path)
            if merged:
                local_paths = [merged_path]
                names = [f"{project_name}.mp4"]
            else:
                # 拼接失败时不阻断：回退为逐集上传
                do_merge = False

        episodes: List[dict] = []
        for idx, (p, name) in enumerate(zip(local_paths, names), start=1):
            file_key = f"raw-footage/{project.id}/{uuid.uuid4().hex}_{name}"
            ok = await upload_file_from_path(settings.MINIO_BUCKET_RAW, file_key, p)
            if not ok:
                raise HTTPException(status_code=500, detail=f"存储 {name} 失败")
            episode = Episode(
                project_id=project.id,
                title=name,
                episode_no=base_episode_no + idx,
                source_file_key=file_key,
                file_size=os.path.getsize(p),
                status="uploaded",
            )
            db.add(episode)
            await db.flush()
            await db.refresh(episode)
            episodes.append(_serialize_episode(episode))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    await db.flush()
    return MultiUploadResponse(
        project_id=str(project.id),
        project_name=project.name,
        episodes=episodes,
        message=(
            f"{'已追加到' if not created_new else '已创建'}项目「{project.name}」并上传 {len(episodes)} 个正片"
            + ("（已合并为一个）" if do_merge else "")
        ),
    )


async def _ffmpeg_concat(paths: List[str], out_path: str) -> bool:
    """用 ffmpeg concat demuxer 将多个视频顺序拼接为一个。

    直接流拷贝（-c copy）简单拼接，不做转码重编码，速度最快。
    要求各素材编码/分辨率/帧率/采样率一致，否则 concat 会失败并回退为
    各视频分别作为一集（见调用处 do_merge=False 兜底）。失败返回 False。
    """
    try:
        list_path = out_path + ".txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for p in paths:
                f.write(f"file '{p}'\n")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", out_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not os.path.isfile(out_path):
            logger.error("ffmpeg concat 失败: %s", stderr.decode(errors="replace")[-2000:])
            return False
        return True
    except Exception as e:
        logger.error(f"ffmpeg concat 异常: {e}")
        return False
    finally:
        try:
            list_txt = out_path + ".txt"
            if os.path.isfile(list_txt):
                os.unlink(list_txt)
        except OSError:
            pass


@router.delete("/upload/{upload_id}", status_code=204)
async def cancel_upload(upload_id: str):
    """Cancel and delete an upload session."""
    if not delete_upload_session(upload_id):
        raise HTTPException(status_code=404, detail="Upload session not found")
