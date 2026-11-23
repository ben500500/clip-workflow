"""slice_tasks 加 dual_mix_config（双批混拼参数 JSON 快照）

双批混拼（2026-11-23）：高光批×N + 正片批×M 混拼成条，参数 JSON 挂任务行。

Revision ID: 0072_dual_mix_config
Revises: 0071_remotion_key_text
"""
from alembic import op
import sqlalchemy as sa

revision = "0072_dual_mix_config"
down_revision = "0071_remotion_key_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slice_tasks", sa.Column("dual_mix_config", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("slice_tasks", "dual_mix_config")
