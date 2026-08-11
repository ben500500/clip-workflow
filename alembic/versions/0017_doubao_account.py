"""add doubao_account field for shortdrama_prompts

Revision ID: 0017_doubao_account
Revises: 0016_doubao_screenshot
Create Date: 2026-08-11

豆包账户展示：shortdrama_prompts 新增 doubao_account（当前登录豆包账户昵称，
生成时从豆包网页端提取，供前端展示「当前登录豆包账户」）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0017_doubao_account"
down_revision: Union[str, None] = "0016_doubao_screenshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_account", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "doubao_account")
