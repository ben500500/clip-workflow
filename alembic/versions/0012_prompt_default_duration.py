"""add prompt_default_duration for users

Revision ID: 0012_prompt_default_duration
Revises: 0011_doubao_generation
Create Date: 2026-08-09

短片制作「提示词生成」：
- users.prompt_default_duration：当前登录用户的提示词生成默认时长（秒），
  用户选择时长（10s/15s/20s/25s/30s/自定义）后即作为该用户的默认值。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0012_prompt_default_duration"
down_revision: Union[str, None] = "0011_doubao_generation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("prompt_default_duration", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "prompt_default_duration")
