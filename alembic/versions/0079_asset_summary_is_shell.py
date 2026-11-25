"""asset_summaries.is_shell：脚本生产载体标记（批 X，文案写入面打通的前置）

Revision ID: 0079_asset_summary_is_shell
Revises: 0078_asset_cards
Create Date: 2026-11-25

11-25 用户口径「两种模式下的文案数据要打通」＝写入面：完整模式出的候选要落一行脚本
（镜像），镜像脚本把真候选当自己的生产载体（carrier_summary_id 指真候选）。
以前的载体判别是**引用式**（有脚本指向它＝壳），镜像一上，真候选也会被脚本指着——
引用式会把真候选误藏进 ②③。所以给壳自己立标记列：

- `_ensure_script_carrier` 造壳时置 true；
- `_not_script_carrier`（②③ 默认藏壳）改读这一列；
- **存量壳的补标**走 `scripts/backfill_summary_is_shell.py`（一次性：现存被脚本引用
  且非镜像的行）。alembic 只建列不搬数据；现网生效走 database.py ADD COLUMN 清单。

为什么不用「link 且无 url」属性式：贴文案导入的素材行同形（docstring 自认），
本机实测就有 5 条真素材符合该形状——只有显式列分得开。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0079_asset_summary_is_shell"
down_revision: Union[str, None] = "0078_asset_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_summaries",
        sa.Column("is_shell", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_asset_summaries_is_shell", "asset_summaries", ["is_shell"])


def downgrade() -> None:
    op.drop_index("ix_asset_summaries_is_shell", table_name="asset_summaries")
    op.drop_column("asset_summaries", "is_shell")
