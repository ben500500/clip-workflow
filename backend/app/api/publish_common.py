"""publish API 子域共享工具（Phase 1 上帝类拆分）。

存放被多个发布子域 router 复用的序列化器与辅助函数，
避免子域模块之间相互 import 形成环：
- `_serialize_publish_task`：publish_tasks / publish_batches 复用
- `_require_admin`：publish_audit / publish_login_qr 复用
"""
from typing import TYPE_CHECKING

from fastapi import HTTPException

from app.models.models import PublishTask, User, UserRole
from app.utils.helpers import utc_iso

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _serialize_publish_task(task: PublishTask) -> dict:
    return {
        "id": str(task.id),
        "output_id": str(task.output_id),
        "platform": task.platform,
        "account_name": task.account_name,
        "status": task.status,
        "celery_task_id": task.celery_task_id,
        "title": task.title,
        "description": task.description,
        "tags": task.tags,
        "cover_file_key": task.cover_file_key,
        "mini_program_link": task.mini_program_link,
        "publish_jump": list(task.publish_jump) if task.publish_jump else None,
        "link_attached": task.link_attached or False,
        "published_url": task.published_url,
        "published_id": task.published_id,
        "published_at": utc_iso(task.published_at) if task.published_at else None,
        "error_message": task.error_message,
        "require_manual_confirm": task.require_manual_confirm if task.require_manual_confirm is not None else True,
        "screenshot_key": task.screenshot_key,
        "video_account_id": str(task.video_account_id) if task.video_account_id else None,
        "mini_program_id": str(task.mini_program_id) if task.mini_program_id else None,
        "prompt_record_id": str(task.prompt_record_id) if task.prompt_record_id else None,
        "material_id": str(task.material_id) if task.material_id else None,
        "batch_id": str(task.batch_id) if task.batch_id else None,
        "operator_id": str(task.operator_id) if task.operator_id else None,
        "scheduled_at": utc_iso(task.scheduled_at) if task.scheduled_at else None,
        "time_slot_label": task.time_slot_label,
        "created_at": utc_iso(task.created_at) if task.created_at else "",
        "updated_at": utc_iso(task.updated_at) if task.updated_at else "",
    }


def _require_admin(current_user: User) -> None:
    """审计类接口仅 superadmin/admin 可查（方案 5.4：审计仅 superadmin/admin 可查看）。"""
    if not current_user or getattr(current_user, "role", None) != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Admin permission required")
