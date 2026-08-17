"""add unique index on channel_accounts.video_account_id

Revision ID: 0032_channel_video_account_unique
Revises: 0031_channel_accounts
Create Date: 2026-08-17

方向1：台账以账号库为主数据。
- video_account_id 改为逻辑必填（服务层强制），服务层已有幂等校验；
  此处追加 DB 层唯一索引兜底，防止同一发布账号被重复登记多条台账。
- 兼容历史数据：保留可空（未关联的历史台账仍存在），Postgres 允许 NULL 重复，
  仅对已关联的非空值唯一。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032_channel_video_account_unique"
down_revision: Union[str, None] = "0031_channel_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_channel_accounts_video_account_id",
        "channel_accounts",
        ["video_account_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_channel_accounts_video_account_id",
        "channel_accounts",
        type_="unique",
    )
