"""切片任务新增「Remotion 混剪增强配置」（slice_tasks 新增 remotion_mix_config）

Revision ID: 0046_slice_task_remotion_mix
Revises: 0045_slice_task_hook_video_keys
Create Date: 2026-08-26

需求「Remotion 混剪增强（P1 MVP）」：开启后由独立 Remotion 渲染容器做模板化编排
（片头/片尾/段间转场/动态字幕），替代裸 concat 高光混剪。数据层在 slice_tasks
新增 remotion_mix_config（可空 JSON，整包 config：enabled/template/intro/outro/
transition_frames/subtitle_style/output_tier），重试时保留该配置。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0046_slice_task_remotion_mix"
down_revision: Union[str, None] = "0045_slice_task_hook_video_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("remotion_mix_config", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "remotion_mix_config")
