"""「去重处理」独立入口 API（圆桌定稿 Phase 2 可观测）。

提供：
- POST /dedupe/upload：批量文件拖入——把视频上传到服务器本地临时目录，
  返回本地 path 供 batch-slice/run 复用（batch_slice_task 处理完会自动清理临时文件）。

设计：只补「文件落地」这一环，去重/变体逻辑完全复用现有链路：
batch-slice/run（上传→切片）→ variants/generate-batch（对 SliceOutput 生成变体）。
"""
import logging
import os
import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.auth import get_current_user
from app.config import settings
from app.models.models import User
from app.services.upload_service import validate_file_name

logger = logging.getLogger(__name__)

router = APIRouter()

# 去重处理上传的临时落地目录（batch_slice_task 处理完自动清理对应源文件）
DEDUPE_UPLOAD_DIR = "/tmp/dedupe_upload"


@router.post("/dedupe/upload")
async def upload_dedupe_video(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """批量文件拖入入口：上传一个视频到服务器本地临时目录。

    返回 {path, file_name, file_size, content_type}。前端用 path 组装
    batch-slice/run 的 episodes[].path 触发切片，切片完成后变体逻辑走
    variants/generate-batch。
    """
    file_name = file.filename or ""
    try:
        safe_name = validate_file_name(file_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upload_id = uuid.uuid4().hex
    os.makedirs(DEDUPE_UPLOAD_DIR, exist_ok=True)
    local_path = os.path.join(DEDUPE_UPLOAD_DIR, f"{upload_id}_{safe_name}")

    size = 0
    try:
        with open(local_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.UPLOAD_MAX_SIZE:
                    out.close()
                    os.unlink(local_path)
                    raise HTTPException(status_code=413, detail="文件超过大小上限")
                out.write(chunk)
    except Exception:
        if os.path.isfile(local_path):
            try:
                os.unlink(local_path)
            except OSError:
                pass
        raise

    if size == 0:
        os.unlink(local_path)
        raise HTTPException(status_code=400, detail="文件为空")

    logger.info("去重处理上传完成 path=%s size=%s user=%s", local_path, size,
                getattr(current_user, "username", None))
    return {
        "path": local_path,
        "file_name": safe_name,
        "file_size": size,
        "content_type": file.content_type or "video/mp4",
    }
