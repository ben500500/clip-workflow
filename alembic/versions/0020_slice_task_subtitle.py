"""add slice_tasks.subtitle_config

Revision ID: 0020_slice_task_subtitle
Revises: 0019_slice_task_badge_default_width
Create Date: 2026-08-12

字幕烧录：切片任务表新增 subtitle_config（JSON）列，
用于持久化每次切片任务的字幕配置（{"enabled": bool, "srt": str}，重试时保留）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0020_slice_task_subtitle"
down_revision: Union[str, None] = "0019_slice_task_badge_default_width"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS subtitle_config JSON"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS subtitle_config")
