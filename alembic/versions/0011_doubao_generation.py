"""add doubao generation fields for shortdrama prompts and users

Revision ID: 0011_doubao_generation
Revises: 0010_watermark_prompt_link
Create Date: 2026-08-09

短片制作「一键豆包生成」：
- users.doubao_account_type：用户默认豆包账户类型（free=免费 / pro=包月会员），
  用户手动选择后即作为当前登录用户的默认值。
- shortdrama_prompts 新增豆包生成任务字段：
  doubao_status / doubao_account_type / doubao_qrcode / doubao_task_id /
  doubao_message / doubao_error_message / doubao_approved_prompt /
  doubao_rewrite_history / doubao_confirm_token
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011_doubao_generation"
down_revision: Union[str, None] = "0010_watermark_prompt_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "doubao_account_type",
            sa.String(length=20),
            server_default="free",
            nullable=False,
        ),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_account_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_qrcode", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_task_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_approved_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_rewrite_history", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_confirm_token", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "doubao_confirm_token")
    op.drop_column("shortdrama_prompts", "doubao_rewrite_history")
    op.drop_column("shortdrama_prompts", "doubao_approved_prompt")
    op.drop_column("shortdrama_prompts", "doubao_error_message")
    op.drop_column("shortdrama_prompts", "doubao_message")
    op.drop_column("shortdrama_prompts", "doubao_task_id")
    op.drop_column("shortdrama_prompts", "doubao_qrcode")
    op.drop_column("shortdrama_prompts", "doubao_account_type")
    op.drop_column("shortdrama_prompts", "doubao_status")
    op.drop_column("users", "doubao_account_type")
