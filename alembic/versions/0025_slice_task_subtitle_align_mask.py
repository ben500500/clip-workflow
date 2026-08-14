"""add slice_tasks.subtitle_align_mask

Revision ID: 0025_slice_task_subtitle_align_mask
Revises: 0024_user_preferences
Create Date: 2026-08-14

字幕对齐源字幕打码区域：切片任务表新增 subtitle_align_mask（Boolean）列，
用于持久化每次切片任务的「ASR 字幕位置对齐源字幕打码区域」开关（默认 True，重试时保留）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0025_slice_task_subtitle_align_mask"
down_revision: Union[str, None] = "0024_user_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS subtitle_align_mask BOOLEAN NOT NULL DEFAULT TRUE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS subtitle_align_mask")
