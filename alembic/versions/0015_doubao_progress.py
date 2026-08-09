"""add doubao progress field for shortdrama_prompts

Revision ID: 0015_doubao_progress
Revises: 0014_seedance_generate
Create Date: 2026-08-09

一键豆包生成加入进度显示：shortdrama_prompts 新增 doubao_progress
（0~100 整数百分比），由 Celery 任务通过 progress_cb 实时写入，
前端在「豆包任务」列展示进度条 + 当前状态。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0015_doubao_progress"
down_revision: Union[str, None] = "0014_seedance_generate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_progress", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "doubao_progress")
