"""slice_tasks 加 outro_video_key（片尾视频）

片尾视频（2026-11-23）：拼接到每个成品末尾（[...][本体][片尾]），与钩子独立。

Revision ID: 0073_outro_video_key
Revises: 0072_dual_mix_config
"""
from alembic import op
import sqlalchemy as sa

revision = "0073_outro_video_key"
down_revision = "0072_dual_mix_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slice_tasks", sa.Column("outro_video_key", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("slice_tasks", "outro_video_key")
