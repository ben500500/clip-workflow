"""add slice_tasks.badge_default_width

Revision ID: 0019_slice_task_badge_default_width
Revises: 0018_slice_task_badges
Create Date: 2026-08-12

图片角标默认尺寸：切片任务表新增 badge_default_width（Integer）列，
用于持久化角标未单独设置宽度时的默认宽度（0=保持原图尺寸），重试时保留。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0019_slice_task_badge_default_width"
down_revision: Union[str, None] = "0018_slice_task_badges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS badge_default_width INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS badge_default_width")
