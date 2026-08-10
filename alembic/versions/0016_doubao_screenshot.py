"""add doubao_screenshot field for shortdrama_prompts

Revision ID: 0016_doubao_screenshot
Revises: 0015_doubao_progress
Create Date: 2026-08-10

豆包/Seedance 制作过程展示：shortdrama_prompts 新增 doubao_screenshot
（当前豆包对话窗口截图 data URL，running 时由 Celery 周期截图）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0016_doubao_screenshot"
down_revision: Union[str, None] = "0015_doubao_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shortdrama_prompts",
        sa.Column("doubao_screenshot", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shortdrama_prompts", "doubao_screenshot")
