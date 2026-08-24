"""切片配置新增「钩子视频」（slice_tasks 新增 hook_video_key）

Revision ID: 0041_slice_task_hook_video
Revises: 0040_slice_task_output_tier
Create Date: 2026-08-24

切片配置新增「钩子视频」：选择一段视频作为片头，拼接在封面首帧与本体视频之间
（[封面][钩子][本体]）。数据层：slice_tasks 新增 hook_video_key（可空，重试时保留）。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0041_slice_task_hook_video"
down_revision: Union[str, None] = "0040_slice_task_output_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("hook_video_key", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "hook_video_key")
