"""add slice_tasks.text_overlays_config

Revision ID: 0021_slice_task_text_overlays
Revises: 0020_slice_task_subtitle
Create Date: 2026-08-12

固定文字角标：切片任务表新增 text_overlays_config（JSON）列，
用于持久化每次切片任务的固定文字叠加配置（在成品上叠加文字，重试时保留）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021_slice_task_text_overlays"
down_revision: Union[str, None] = "0020_slice_task_subtitle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS text_overlays_config JSON"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS text_overlays_config")
