"""add prompt_long/prompt_short columns for three-version prompts

Revision ID: 0009_prompt_versions
Revises: 0008_data_scope
Create Date: 2026-08-08

短片制作提示词三版本：
- 长提示词 / 短提示词：固定模板（仅替换 [视频文案]）
- AI 提示词：Seedance 七段结构（大模型生成，保留在 prompt_text）
shortdrama_prompts 表新增 prompt_long / prompt_short 两列保存长 / 短版本。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009_prompt_versions"
down_revision: Union[str, None] = "0008_data_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shortdrama_prompts",
        sa.Column("prompt_long", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("prompt_short", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "prompt_short")
    op.drop_column("shortdrama_prompts", "prompt_long")
