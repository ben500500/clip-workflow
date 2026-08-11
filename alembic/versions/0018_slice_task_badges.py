"""add slice_tasks.badges_config

Revision ID: 0018_slice_task_badges
Revises: 0017_doubao_account
Create Date: 2026-08-12

图片角标：切片任务表新增 badges_config（JSON）列，
用于持久化每次切片任务的图片角标配置（重试时保留）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0018_slice_task_badges"
down_revision: Union[str, None] = "0017_doubao_account"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slice_tasks ADD COLUMN IF NOT EXISTS badges_config JSON"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slice_tasks DROP COLUMN IF EXISTS badges_config")
