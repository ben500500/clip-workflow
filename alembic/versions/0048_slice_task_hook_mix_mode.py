"""切片任务新增「钩子混搭模式」（slice_tasks 新增 hook_mix_mode 列）

Revision ID: 0048_slice_task_hook_mix_mode
Revises: 0047_slice_task_remotion_result
Create Date: 2026-08-28

需求「钩子视频随机混搭」：多钩子场景下支持三种混搭策略：
- sequential（默认，向后兼容）：按顺序循环取用；
- random：每个切片随机选一个钩子；
- combine：所有钩子依次拼接成片头。

slice_tasks 新增可空列 hook_mix_mode（VARCHAR(20)）。存量任务不受影响。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0048_slice_task_hook_mix_mode"
down_revision: Union[str, None] = "0047_slice_task_remotion_result"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("hook_mix_mode", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "hook_mix_mode")
