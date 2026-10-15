"""新增 wechat_dl_prompt_tasks 表（视频反推提示词，智令 doc/120 + doc/119）

Revision ID: 0051_wechat_dl_prompt_tasks
Revises: 0050_episode_av_sync_warning
Create Date: 2026-09-01

ISSUE #361 任务 A：接入智令「视频反推提示词（计时）」。

- 提交 POST https://api.17zhiling.com/api/video-inference/parse-video-url-time
  → 返回 taskId；轮询 GET /api/video-inference/task-status 取 schedule/content。
- 该表属 wechat_download 独立包（自持 WechatDownloadBase），随包走；
  仅新增表、不改动主系统任何表，向后兼容，downgrade 可回滚。

注：新表由 init_db() 的 `_ensure_wechat_download_tables()` create_all 兜底创建，
线上未跑 `alembic upgrade head` 也不会缺表；本迁移供 fresh DB / 版本链参考。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0051_wechat_dl_prompt_tasks"
down_revision: Union[str, None] = "0050_episode_av_sync_warning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_dl_prompt_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("provider_task_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("max_duration", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wechat_dl_prompt_tasks_created_by", "wechat_dl_prompt_tasks", ["created_by"])
    op.create_index("ix_wechat_dl_prompt_tasks_status", "wechat_dl_prompt_tasks", ["status"])
    op.create_index("ix_wechat_dl_prompt_tasks_provider_task_id", "wechat_dl_prompt_tasks", ["provider_task_id"])


def downgrade() -> None:
    op.drop_index("ix_wechat_dl_prompt_tasks_provider_task_id", table_name="wechat_dl_prompt_tasks")
    op.drop_index("ix_wechat_dl_prompt_tasks_status", table_name="wechat_dl_prompt_tasks")
    op.drop_index("ix_wechat_dl_prompt_tasks_created_by", table_name="wechat_dl_prompt_tasks")
    op.drop_table("wechat_dl_prompt_tasks")
