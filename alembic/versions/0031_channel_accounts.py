"""add channel_accounts / channel_operators (视频号台账)

Revision ID: 0031_channel_accounts
Revises: 0030_publish_task_dead_letter
Create Date: 2026-08-17

视频号台账（Issue #93，渠道侧商务登记，与发布通道账号库解耦）：
- channel_accounts     台账主表（channel_name/wechat_id/verify_type/verify_name/
                        register_date/cooperation_modes/coop_company/
                        video_account_id(软外键，先登记后关联)/remark/enabled/created_by）
- channel_operators    运营者子表（双轨：operator_user_id 或 operator_name 至少一，
                        operator_phone 外部联系兜底；CheckConstraint 兜底校验）

全部为新增表，向后兼容；downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0031_channel_accounts"
down_revision: Union[str, None] = "0030_publish_task_dead_letter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_name", sa.String(length=100), nullable=False),
        sa.Column("wechat_id", sa.String(length=200), nullable=True),
        sa.Column("verify_type", sa.String(length=20), nullable=True),
        sa.Column("verify_name", sa.String(length=100), nullable=True),
        sa.Column("register_date", sa.Date(), nullable=True),
        sa.Column("cooperation_modes", sa.JSON(), nullable=True),
        sa.Column("coop_company", sa.String(length=200), nullable=True),
        sa.Column("video_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_channel_accounts_channel_name", "channel_accounts", ["channel_name"])
    op.create_index("ix_channel_accounts_wechat_id", "channel_accounts", ["wechat_id"])
    op.create_index("ix_channel_accounts_video_account_id", "channel_accounts", ["video_account_id"])
    op.create_index("ix_channel_accounts_created_by", "channel_accounts", ["created_by"])

    op.create_table(
        "channel_operators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channel_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operator_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operator_name", sa.String(length=100), nullable=True),
        sa.Column("operator_phone", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "operator_user_id IS NOT NULL OR operator_name IS NOT NULL",
            name="ck_channel_operator_identity",
        ),
    )
    op.create_index(
        "ix_channel_operators_channel_account_id", "channel_operators", ["channel_account_id"]
    )
    op.create_index(
        "ix_channel_operators_operator_user_id", "channel_operators", ["operator_user_id"]
    )


def downgrade() -> None:
    op.drop_table("channel_operators")
    op.drop_table("channel_accounts")
