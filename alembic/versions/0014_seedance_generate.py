"""add seedance official API direct-generate fields for shortdrama_prompts

Revision ID: 0014_seedance_generate
Revises: 0013_video_accounts_mini_programs
Create Date: 2026-08-09

短片制作「Seedance 官方 API 直连出片」（与豆包 RPA 并行、独立通道）：
- shortdrama_prompts 新增 seedance_* 任务字段 + gen_channel（成片来源追溯）：
  seedance_status / seedance_task_id / seedance_message /
  seedance_error_message / seedance_resolution / gen_channel
- 成片仍写回 video_* 字段，下游（去水印 / 发布）零改动。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0014_seedance_generate"
down_revision: Union[str, None] = "0013_video_accounts_mini_programs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shortdrama_prompts",
        sa.Column("seedance_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("seedance_task_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("seedance_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("seedance_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("seedance_resolution", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "shortdrama_prompts",
        sa.Column("gen_channel", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "gen_channel")
    op.drop_column("shortdrama_prompts", "seedance_resolution")
    op.drop_column("shortdrama_prompts", "seedance_error_message")
    op.drop_column("shortdrama_prompts", "seedance_message")
    op.drop_column("shortdrama_prompts", "seedance_task_id")
    op.drop_column("shortdrama_prompts", "seedance_status")
