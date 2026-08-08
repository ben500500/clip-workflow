"""add shortdrama_prompts table

Revision ID: 0005_shortdrama_prompts
Revises: 0004_watermark
Create Date: 2026-08-08

短片制作（v6）：新增 shortdrama_prompts（Seedance 提示词生成记录）表，
保存每次「文案 → Seedance 提示词」的生成历史，与去水印任务构成短片制作工作流。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_shortdrama_prompts"
down_revision: Union[str, None] = "0004_watermark"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shortdrama_prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("theme", sa.String(200), nullable=True),
        sa.Column("tone", sa.String(200), nullable=True),
        sa.Column("characters", sa.Text(), nullable=True),
        sa.Column("extra_requirements", sa.Text(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_shortdrama_prompts_created_at", "shortdrama_prompts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_shortdrama_prompts_created_at", table_name="shortdrama_prompts")
    op.drop_table("shortdrama_prompts")
