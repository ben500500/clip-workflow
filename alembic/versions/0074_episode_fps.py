"""episodes 加 fps（帧率），供剧集列表显示规格

Revision ID: 0074_episode_fps
Revises: 0073_outro_video_key
"""
from alembic import op
import sqlalchemy as sa

revision = "0074_episode_fps"
down_revision = "0073_outro_video_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("fps", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "fps")
