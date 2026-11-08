"""A′ 按运营隔离（评审团定稿，2026-11-08）：职能开关＋重提说明持久化

1. users.can_review / users.can_produce：operator 拆职能不拆账号——审核（质检）与
   投产（挑选/投板）两个岗位用职能开关区分（默认双开=兼容现状），管理员按人关闭即
   实现岗位隔离；判定收在 review/produce/dispatch 三口的权限汇聚点。
2. asset_summaries.resubmit_note：驳回→改后重提时作者写给审核人的说明，此前只进
   AuditLog（审核人看不见），落列后审核卡直接展示（评审·审核席 top_issue#1）。

全部带默认/可空，不回填；生效路径同 0055~0063：老库由 app/database.py ADD COLUMN
清单兜底，本迁移供 fresh DB、版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0064_user_functions_resubmit_note"
down_revision: Union[str, None] = "0063_board_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("can_review", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("can_produce", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("asset_summaries", sa.Column("resubmit_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_summaries", "resubmit_note")
    op.drop_column("users", "can_produce")
    op.drop_column("users", "can_review")
