"""add slice_tasks.vert2horiz_config

Revision ID: 0003_slice_task_vert2horiz
Revises: 0002_autoclip_runs
Create Date: 2026-08-07

竖屏转横屏智能裁切：切片任务表新增 vert2horiz_config（JSON）列，
用于持久化每次切片任务的竖屏转横屏预处理配置（重试时保留）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_slice_task_vert2horiz"
down_revision: Union[str, None] = "0002_autoclip_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS vert2horiz_config JSON"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS vert2horiz_config")
