"""视频封面（slice_tasks 新增 cover_image_key）

Revision ID: 0035_slice_task_cover_image
Revises: 0034_multi_video_dedup_variants
Create Date: 2026-02-14

切片配置新增「视频封面」：在成品开头叠加一张静止封面画面作为视频首帧。
数据层：slice_tasks 新增 cover_image_key（封面图片 MinIO key，可空）。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0035_slice_task_cover_image"
down_revision: Union[str, None] = "0034_multi_video_dedup_variants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("slice_tasks", sa.Column("cover_image_key", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("slice_tasks", "cover_image_key")
