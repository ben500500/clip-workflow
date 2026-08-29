"""切片任务新增「钩子混搭输出数量」（slice_tasks 新增 hook_mix_output_count 列）

Revision ID: 0049_slice_task_hook_mix_output_count
Revises: 0048_slice_task_hook_mix_mode
Create Date: 2026-08-29

需求「指定输出文件的数量」：当用户在随机混搭或拼接组合模式下选择输出数量时，
引擎需要生成多个不同钩子组合的成品（-v1, -v2 后缀）。

slice_tasks 新增可空列 hook_mix_output_count（INTEGER）。存量任务不受影响。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0049_slice_task_hook_mix_output_count"
down_revision: Union[str, None] = "0048_slice_task_hook_mix_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("hook_mix_output_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "hook_mix_output_count")
