"""add publish_task retry/dead_letter fields

Revision ID: 0030_publish_task_dead_letter
Revises: 0029_wechat_download
Create Date: 2026-08-16

发布增强（Issue #150，方向② 批量发布体验 + 方向④ 稳定性）：
- publish_tasks 新增：
  - retry_count          重试计数（默认 0）
  - dead_letter          死信标记（默认 False，失败不再静默丢失）
  - dead_letter_reason   死信原因（Text，可回溯重发）

全部为新增，向后兼容；downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0030_publish_task_dead_letter"
down_revision: Union[str, None] = "0029_wechat_download"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publish_tasks",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("dead_letter", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("dead_letter_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publish_tasks", "dead_letter_reason")
    op.drop_column("publish_tasks", "dead_letter")
    op.drop_column("publish_tasks", "retry_count")
