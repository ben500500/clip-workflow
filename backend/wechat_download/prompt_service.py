"""视频反推提示词业务编排（智令 doc/120 提交 + doc/119 轮询）。

职责边界：
- 只读写本包独立表 `wechat_dl_prompt_tasks`，不碰主系统表；
- 外部调用 fail-soft：提交被拒/轮询网络异常一律写库 `failed` + `error`，
  由 API 层返回任务本体（不抛 500），保证「一次外部抖动不产生 5xx」。

竞态教训（沿用 create_import_task 的既有注释约定）：提交前先 commit 落行，
再调外部接口，避免持有事务跨网络 IO 导致连接池被长时间占用。
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import User, user_can_access_all_materials
from wechat_download.models import (
    PST_UPLOAD,
    PST_URL,
    PT_FAILED,
    PT_PROCESSING,
    PT_SUCCESS,
    WechatDlPromptTask,
)
from wechat_download.prompt_client import PromptClient, PromptError
from wechat_download.upload_client import UploadClient, UploadError

logger = logging.getLogger(__name__)


def serialize_prompt_task(t: WechatDlPromptTask) -> dict:
    return {
        "id": str(t.id),
        "created_by": str(t.created_by) if t.created_by else None,
        "source_type": t.source_type or PST_URL,
        "source_url": t.source_url,
        "file_name": t.file_name,
        "provider_task_id": t.provider_task_id,
        "status": t.status,
        "content": t.content,
        "error": t.error,
        "max_duration": t.max_duration,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def can_access_prompt_task(task: WechatDlPromptTask, current_user: Optional[User]) -> bool:
    """可见口径与 wechat-dl 下载任务列表保持一致。

    - scope=all（admin/material/publisher）：可见全部
    - operator：仅见自己发起的；**发起人为空（历史/系统任务）视为公共**，
      与 ISSUE #361 任务 C「无主即公共」的口径一致。
    """
    if current_user is None:
        return False
    if user_can_access_all_materials(current_user):
        return True
    if task.created_by is None:
        return True
    return task.created_by == current_user.id


async def prompt_task_scope_stmt(current_user: Optional[User], limit: int = 50):
    """按可见口径构造列表查询（供 API 复用，避免口径漂移）。"""
    stmt = select(WechatDlPromptTask).order_by(WechatDlPromptTask.created_at.desc()).limit(limit)
    if current_user is not None and not user_can_access_all_materials(current_user):
        stmt = stmt.where(
            WechatDlPromptTask.created_by.is_(None)
            | (WechatDlPromptTask.created_by == current_user.id)
        )
    return stmt


async def create_prompt_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    source_url: str,
    max_duration: Optional[int] = None,
    source_type: str = PST_URL,
    file_name: Optional[str] = None,
) -> WechatDlPromptTask:
    """建行 + 提交智令。返回落库后的任务（失败时 status=failed，带 error）。

    source_type=upload 时 source_url 是 doc/125 上传后拿到的 fileUrl，
    file_name 保留用户原始文件名（仅作展示/追溯）。
    """
    task = WechatDlPromptTask(
        created_by=created_by,
        source_url=(source_url or "").strip()[:1000],
        source_type=source_type or PST_URL,
        file_name=(file_name or None) and str(file_name)[:255],
        max_duration=max_duration,
        status=PT_PROCESSING,
    )
    db.add(task)
    # 先提交：外部请求可能耗时数秒，且失败时要保证用户能在列表里看到这条失败的记录
    await db.commit()
    await db.refresh(task)

    client = PromptClient()
    try:
        provider_task_id = await client.submit(task.source_url, max_duration)
    except PromptError as e:
        task.status = PT_FAILED
        task.error = str(e)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("反推提示词任务提交失败 task=%s: %s", task.id, e)
        return task
    finally:
        await client.close()

    task.provider_task_id = provider_task_id
    task.status = PT_PROCESSING
    task.error = None
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    return task


async def get_prompt_task(db: AsyncSession, task_id: uuid.UUID) -> Optional[WechatDlPromptTask]:
    result = await db.execute(select(WechatDlPromptTask).where(WechatDlPromptTask.id == task_id))
    return result.scalar_one_or_none()


async def refresh_prompt_task(db: AsyncSession, task: WechatDlPromptTask) -> WechatDlPromptTask:
    """仍在 processing 时向智令查询一次并按 schedule 更新状态/内容。

    只在 `processing` 且已有 provider_task_id 时才发起外部查询，终态任务不重复扣费/请求。
    """
    if task.status != PT_PROCESSING or not task.provider_task_id:
        return task

    client = PromptClient()
    try:
        st = await client.query(task.provider_task_id)
    finally:
        await client.close()

    if st.status == PT_SUCCESS:
        task.status = PT_SUCCESS
        task.content = st.content
        task.error = None
    elif st.status == PT_FAILED:
        task.status = PT_FAILED
        task.error = (st.error or "任务处理失败")[:500]
    else:
        # 处理中：仅刷新 updated_at，保持轮询可继续
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        return task

    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    return task


# 允许上传的视频扩展名（前端 accept 与后端校验共用一份，避免两边漂移）
UPLOAD_ALLOWED_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v")

# 扩展名 → content type：doc/125 签名要按 contentType 签，S3 侧写入同值
EXT_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


def upload_max_bytes() -> int:
    """上传大小上限（字节）。每次现读 settings，便于测试/运维改 env 后即时生效。"""
    return int(settings.WECHAT_DL_PROMPT_UPLOAD_MAX_MB) * 1024 * 1024


def validate_upload_ext(file_name: Optional[str]) -> Optional[str]:
    """校验扩展名白名单。返回错误原因（None 表示通过）。

    与大小分开两个函数：API 层要在**落盘之前**先拒非法扩展名，
    此时还不知道真实大小，硬塞一个假 size 进来只会让校验语义变浑浊。
    """
    name = (file_name or "").strip()
    if not name:
        return "缺少文件名"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in UPLOAD_ALLOWED_EXTS:
        return f"不支持的文件类型 {ext or '(无扩展名)'}，仅支持 {' '.join(UPLOAD_ALLOWED_EXTS)}"
    return None


def validate_upload_size(size_bytes: int) -> Optional[str]:
    """校验文件大小。返回错误原因（None 表示通过）。超限由 API 层转 413。"""
    if size_bytes <= 0:
        return "上传文件为空"
    limit = upload_max_bytes()
    if size_bytes > limit:
        return f"文件过大（{size_bytes / 1024 / 1024:.1f}MB），上限 {limit // 1024 // 1024}MB"
    return None


def validate_upload_file(file_name: Optional[str], size_bytes: int) -> Optional[str]:
    """扩展名 + 大小一起校验（组合便捷入口），返回错误原因或 None。"""
    return validate_upload_ext(file_name) or validate_upload_size(size_bytes)


def content_type_for(file_name: Optional[str]) -> str:
    name = (file_name or "").lower()
    ext = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""
    return EXT_CONTENT_TYPES.get(ext, "video/mp4")


async def create_upload_prompt_task(
    db: AsyncSession,
    *,
    created_by: Optional[uuid.UUID],
    file_obj,
    file_name: str,
    size_bytes: int,
    max_duration: Optional[int] = None,
) -> WechatDlPromptTask:
    """本地视频上传 → 反推：建行（先 commit）→ doc/125 签名 → S3 POST → doc/120 提交。

    与 create_prompt_task 同样 fail-soft：签名/S3 失败只把任务写 failed + error，
    绝不向上抛（API 层仍返回 201 任务本体），保证一次外部抖动不产生 5xx。
    文件对象由调用方（API 层）负责生命周期：这里只读不关，临时文件在 API 层 finally 删。
    """
    task = WechatDlPromptTask(
        created_by=created_by,
        # doc/125 上传完成前还不知道 fileUrl，先占位，成功后回填
        source_url="",
        source_type=PST_UPLOAD,
        file_name=(file_name or "")[:255] or None,
        max_duration=max_duration,
        status=PT_PROCESSING,
    )
    db.add(task)
    # 先提交：上传大文件可能耗时数分钟，必须先让用户在列表里看到这条在跑的任务
    await db.commit()
    await db.refresh(task)

    ctype = content_type_for(file_name)
    up = UploadClient()
    try:
        ticket = await up.sign(file_name=file_name, content_type=ctype)
        await up.post_file(
            ticket, file_obj, file_name=file_name, size_bytes=size_bytes, content_type=ctype,
        )
    except UploadError as e:
        task.status = PT_FAILED
        task.error = str(e)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("反推提示词上传失败 task=%s: %s", task.id, e)
        return task
    finally:
        await up.close()

    task.source_url = (ticket.file_url or "")[:1000]
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)

    # 拿到 fileUrl 后走既有提交链路（doc/120），复用同一套 fail-soft 与计费口径
    client = PromptClient()
    try:
        provider_task_id = await client.submit(task.source_url, max_duration)
    except PromptError as e:
        task.status = PT_FAILED
        task.error = str(e)[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("反推提示词任务提交失败 task=%s: %s", task.id, e)
        return task
    finally:
        await client.close()

    task.provider_task_id = provider_task_id
    task.status = PT_PROCESSING
    task.error = None
    task.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)
    return task
