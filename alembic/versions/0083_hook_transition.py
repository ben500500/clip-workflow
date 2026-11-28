"""slice task hook transition toggle

Revision ID: 0083_hook_transition
Revises: 0082_slice_task_shards

外部素材接缝转场开关（docs/1128-v2 后增量，用户自主控制）：
老库补列走 database.py compat 清单（NOT NULL DEFAULT FALSE），本迁移保 stamp 链。
"""
from alembic import op
import sqlalchemy as sa

revision = "0083_hook_transition"
down_revision = "0082_slice_task_shards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("hook_transition_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "hook_transition_enabled")
