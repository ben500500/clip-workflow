"""add watermark_videos.prompt_record_id for task association

Revision ID: 0010_watermark_prompt_link
Revises: 0009_prompt_versions
Create Date: 2026-08-08

短片制作工作流任务关联：
- 提示词记录 → 去水印任务（导入成片视频时携带来源提示词记录 id）
- 去水印完成 → 发布素材（根据关联自动代入原始文案）
watermark_videos 表新增 prompt_record_id 列记录来源提示词记录。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_watermark_prompt_link"
down_revision: Union[str, None] = "0009_prompt_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watermark_videos",
        sa.Column("prompt_record_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_watermark_videos_prompt_record_id",
        "watermark_videos",
        ["prompt_record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_watermark_videos_prompt_record_id", table_name="watermark_videos")
    op.drop_column("watermark_videos", "prompt_record_id")
