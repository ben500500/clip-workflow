"""add slice_tasks.subtitle_mask_config

Revision ID: 0023_slice_task_subtitle_mask
Revises: 0022_batch_item_detect_task
Create Date: 2026-08-13

源视频字幕打码：切片任务表新增 subtitle_mask_config（JSON）列，
用于持久化每次切片任务的源字幕打码配置（{"enabled": bool, "style": str, ...}，重试时保留）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0023_slice_task_subtitle_mask"
down_revision: Union[str, None] = "0022_batch_item_detect_task"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS subtitle_mask_config JSON"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS subtitle_mask_config")
