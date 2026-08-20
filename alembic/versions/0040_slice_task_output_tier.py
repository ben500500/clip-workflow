"""切片配置新增「输出档位」（slice_tasks 新增 output_tier）

Revision ID: 0040_slice_task_output_tier
Revises: 0039_drama_topics
Create Date: 2026-08-20

切片配置新增「输出档位」：高分辨率/高 fps 素材可降档提速。
数据层：slice_tasks 新增 output_tier（original/auto/1080p/720p/480p，默认 original）。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0040_slice_task_output_tier"
down_revision: Union[str, None] = "0039_drama_topics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("output_tier", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "output_tier")
