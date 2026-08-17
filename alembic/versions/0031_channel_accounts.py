"""add channel_accounts / channel_operators (视频号登记台账)

Revision ID: 0031_channel_accounts
Revises: 0030_publish_task_dead_letter
Create Date: 2026-08-17

新增「视频号列表」登记功能（Issue #93）：
- channel_accounts 表：视频号登记台账
  - channel_name       视频号名称
  - wechat_id          微信号
  - verify_type        实名类型（personal/enterprise）
  - verify_name        实名人
  - register_date      注册日期
  - cooperation_mode   合作模式（IAA/IAP，可空=暂未接入）
  - coop_company       合作公司
  - video_account_id   关联现有发布账号矩阵（video_accounts.id）
  - remark / enabled / 审计字段
- channel_operators 表：运营者多对多（关联 channel_accounts + users）

全部为新增，向后兼容；downgrade 可回滚。
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
    # 视频号登记台账
    op.create_table(
        "channel_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel_name", sa.String(length=100), nullable=False),
        sa.Column("wechat_id", sa.String(length=200), nullable=True),
        sa.Column("verify_type", sa.String(length=20), nullable=True),
        sa.Column("verify_name", sa.String(length=200), nullable=True),
        sa.Column("register_date", sa.Date(), nullable=True),
        sa.Column("cooperation_mode", sa.String(length=20), nullable=True),
        sa.Column("coop_company", sa.String(length=200), nullable=True),
        sa.Column("video_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_channel_accounts_channel_name", "channel_accounts", ["channel_name"])
    op.create_index("ix_channel_accounts_created_by", "channel_accounts", ["created_by"])
    op.create_index("ix_channel_accounts_video_account_id", "channel_accounts", ["video_account_id"])

    # 运营者多对多
    op.create_table(
        "channel_operators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channel_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operator_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_channel_operators_channel_account_id",
        "channel_operators",
        ["channel_account_id"],
    )
    op.create_index(
        "ix_channel_operators_operator_id",
        "channel_operators",
        ["operator_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_operators_operator_id", table_name="channel_operators")
    op.drop_index("ix_channel_operators_channel_account_id", table_name="channel_operators")
    op.drop_table("channel_operators")
    op.drop_index("ix_channel_accounts_video_account_id", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_created_by", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_channel_name", table_name="channel_accounts")
    op.drop_table("channel_accounts")
