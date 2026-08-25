"""切片配置新增「钩子视频文件夹」（slice_tasks 新增 hook_video_keys）

Revision ID: 0045_slice_task_hook_video_keys
Revises: 0044_drama_theaters
Create Date: 2026-08-25

需求「钩子视频选择改成选择文件夹」：文件夹中会有多个钩子视频，切片时随机组合。
数据层：slice_tasks 新增 hook_video_keys（可空 JSON，值为 MinIO file_key 列表，
每个成品切片随机从中取一个钩子作为片头）。保留既有 hook_video_key（单钩子，
向后兼容，二者并存时 hook_video_keys 优先）。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0045_slice_task_hook_video_keys"
down_revision: Union[str, None] = "0044_drama_theaters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("hook_video_keys", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "hook_video_keys")
