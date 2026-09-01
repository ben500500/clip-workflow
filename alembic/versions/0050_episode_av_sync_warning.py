"""剧集新增「秒差检测」标注列（episodes 新增 av_sync_warning / av_sync_diff）

Revision ID: 0050_episode_av_sync_warning
Revises: 0049_slice_task_hook_mix_output_count
Create Date: 2026-09-01

需求：多视频上传「秒差检测」（音画同步粗检）开关。
开启后多视频批量上传会对每个视频做音画时长差校验，命中时不再拦截上传，
而是标注该集为疑似音画不同步（av_sync_warning=True 并记录音视频时长差 av_sync_diff），
供运营在剧集列表识别。存量剧集不受影响（默认 False / NULL）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0050_episode_av_sync_warning"
down_revision: Union[str, None] = "0049_slice_task_hook_mix_output_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("av_sync_warning", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "episodes",
        sa.Column("av_sync_diff", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episodes", "av_sync_diff")
    op.drop_column("episodes", "av_sync_warning")
