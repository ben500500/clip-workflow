"""角色卡独立成库：新建 asset_cards 表（批 W，图片不再当素材入库）

Revision ID: 0078_asset_cards
Revises: 0077_asset_script_favorites
Create Date: 2026-11-25

11-25 用户口径「这个图片不要入库」：批 G 把上传的三视图真写成 asset_items 行
（media_kind=image），结果是完整模式 ② 素材与文案里混着角色卡。批 W 把卡挪到
独立一张表——卡不是素材：不进 asset_items、不占批次、不走五环、不计费、不抽帧；
但卡要跨批复用，所以仍是一行带 file_key 的库记录，挑卡器/交付侧照旧按 id 取。

⚠️ **本迁移只建空表，不搬数据**。存量图片行（asset_items.media_kind='image'）→
asset_cards 的搬迁走显式脚本 `scripts/migrate_cards_from_items.py`（要删旧行，
先备份再动；id 原样保留，已挂卡的生产单不用重挑）。部署链路不跑 alembic
upgrade（只 stamp head），新表靠 `app/database.py` init_db 的 create_all 建——
所以这张表在现网生效不依赖本文件，本文件供 fresh DB / 版本链 / 人工核对。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0078_asset_cards"
down_revision: Union[str, None] = "0077_asset_script_favorites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_key", sa.String(500), nullable=True),
        sa.Column("bucket", sa.String(50), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("resolution", sa.String(50), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asset_cards_code", "asset_cards", ["code"], unique=True)
    op.create_index("ix_asset_cards_owner_id", "asset_cards", ["owner_id"])
    op.create_index("ix_asset_cards_created_at", "asset_cards", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_asset_cards_created_at", table_name="asset_cards")
    op.drop_index("ix_asset_cards_owner_id", table_name="asset_cards")
    op.drop_index("ix_asset_cards_code", table_name="asset_cards")
    op.drop_table("asset_cards")
