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

from app.models.models import User, user_can_access_all_materials
from wechat_download.models import (
    PT_FAILED,
    PT_PROCESSING,
    PT_SUCCESS,
    WechatDlPromptTask,
)
from wechat_download.prompt_client import PromptClient, PromptError

logger = logging.getLogger(__name__)


def serialize_prompt_task(t: WechatDlPromptTask) -> dict:
    return {
        "id": str(t.id),
        "created_by": str(t.created_by) if t.created_by else None,
        "source_url": t.source_url,
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
) -> WechatDlPromptTask:
    """建行 + 提交智令。返回落库后的任务（失败时 status=failed，带 error）。"""
    task = WechatDlPromptTask(
        created_by=created_by,
        source_url=(source_url or "").strip()[:1000],
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
