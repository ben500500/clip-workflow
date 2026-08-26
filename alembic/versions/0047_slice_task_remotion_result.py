"""切片任务新增「Remotion 渲染结果列」（slice_tasks 新增 remotion_output_file_key / remotion_status）

Revision ID: 0047_slice_task_remotion_result
Revises: 0046_slice_task_remotion_mix
Create Date: 2026-08-26

需求「Remotion 混剪增强（P2 结果回写）」：渲染成功后写入产物 MinIO file_key 与
渲染状态。slice_tasks 新增两个可空列：
- remotion_output_file_key: 渲染产物在 sliced 桶的 file_key（成品库可预览/发布）；
- remotion_status: 渲染状态（pending/rendering/done/failed，未启用时为 None）。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0047_slice_task_remotion_result"
down_revision: Union[str, None] = "0046_slice_task_remotion_mix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slice_tasks",
        sa.Column("remotion_output_file_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "slice_tasks",
        sa.Column("remotion_status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("slice_tasks", "remotion_status")
    op.drop_column("slice_tasks", "remotion_output_file_key")
