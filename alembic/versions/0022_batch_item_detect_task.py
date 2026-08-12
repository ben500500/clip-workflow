"""add batch_slice_items.detect_task_id

Revision ID: 0022_batch_item_detect_task
Revises: 0021_slice_task_text_overlays
Create Date: 2026-08-12

一键切片新增「通用区间检测」阶段：批量切片批次项表新增 detect_task_id（UUID）列，
用于追踪每个剧集对应的区间检测 SliceTask（mode=detect_*）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0022_batch_item_detect_task"
down_revision: Union[str, None] = "0021_slice_task_text_overlays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE batch_slice_items ADD COLUMN IF NOT EXISTS detect_task_id UUID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE batch_slice_items DROP COLUMN IF EXISTS detect_task_id")
