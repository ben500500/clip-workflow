"""切片候选新增「高光形态」（clip_candidates 新增 clip_type）

Revision ID: 0042_clip_candidate_clip_type
Revises: 0041_slice_task_hook_video
Create Date: 2026-08-24

选点端高光识别：AI 智能选点新增「高光片段识别」，找出多段 ≤10s 的短高光。
数据层：clip_candidates 新增 clip_type（可空）：
  - suspense_cut / full_highlight：常规出片形态（默认按时长推断）；
  - highlight：高光识别模式产出的短高光段（≤10s）。
切片端高光混剪依赖该字段标记的高光段按源时间顺序混剪拼接。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0042_clip_candidate_clip_type"
down_revision: Union[str, None] = "0041_slice_task_hook_video"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clip_candidates",
        sa.Column("clip_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clip_candidates", "clip_type")
