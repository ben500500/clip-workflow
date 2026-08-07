"""add watermark tables

Revision ID: 0004_watermark
Revises: 0003_slice_task_vert2horiz
Create Date: 2026-08-07

去水印功能（v4）：新增 watermark_tasks（任务）与 watermark_videos（任务下视频）
两张表，用于批量去水印任务的异步执行、进度展示、历史保存与资源文件删除。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_watermark"
down_revision: Union[str, None] = "0003_slice_task_vert2horiz"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watermark_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engine", sa.String(50), nullable=False),
        sa.Column("options", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "watermark_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("watermark_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("source_file_key", sa.String(500), nullable=False),
        sa.Column("source_bucket", sa.String(50), nullable=True, server_default="raw-footage"),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("output_file_key", sa.String(500), nullable=True),
        sa.Column("output_bucket", sa.String(50), nullable=True),
        sa.Column("output_file_size", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_watermark_videos_task_id", "watermark_videos", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_watermark_videos_task_id", table_name="watermark_videos")
    op.drop_table("watermark_videos")
    op.drop_table("watermark_tasks")
