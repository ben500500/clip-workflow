"""试产单标记（2026-11-12 用户口径）：asset_productions.is_trial

审核员在审核台改提示词投豆包验证预期（试产）：成片只进审核台做判定依据，
不进成片墙/交付包（读侧按 is_trial 过滤）。待审候选也允许试产——
试产是「审的辅助证据」，与审核状态解耦。

生效路径同 0055~0068：fresh DB 由 create_all 带上（模型声明 server_default），
存量表由部署链的 db_sync_columns ADD COLUMN IF NOT EXISTS 回填。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0070_production_is_trial"
down_revision: Union[str, None] = "0069_asset_element_guesses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_productions",
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("asset_productions", "is_trial")
