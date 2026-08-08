"""add video attachment fields to shortdrama_prompts

Revision ID: 0006_shortdrama_prompt_video
Revises: 0005_shortdrama_prompts
Create Date: 2026-08-08

短片制作（v6.1）：shortdrama_prompts 表新增成片视频关联字段，
支持「生成历史上传视频 → 一键导入去水印流程」。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_shortdrama_prompt_video"
down_revision: Union[str, None] = "0005_shortdrama_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_file_name", sa.String(500), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_file_key", sa.String(500), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_bucket", sa.String(50), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_status", sa.String(50), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("video_uploaded_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "video_uploaded_at")
    op.drop_column("shortdrama_prompts", "video_error_message")
    op.drop_column("shortdrama_prompts", "video_status")
    op.drop_column("shortdrama_prompts", "video_file_size")
    op.drop_column("shortdrama_prompts", "video_bucket")
    op.drop_column("shortdrama_prompts", "video_file_key")
    op.drop_column("shortdrama_prompts", "video_file_name")
