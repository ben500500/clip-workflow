"""剧目管理：dramas + drama_stills + drama_accounts + drama_materials

Revision ID: 0036_drama_management
Revises: 0035_publish_profile_location
Create Date: 2026-08-18

ISSUE #130「视频号自动发布」→ 剧目管理（《剧目管理设计方案-20260818.md》P0）。

新增 4 张表：
- dramas           剧目主表（code=DR-<8位HEX> 唯一、name 唯一去重、synopsis、cover_file_key）
- drama_stills     剧照（一对多，MinIO key）
- drama_accounts   剧目↔视频号（多对多）
- drama_materials  剧目↔发布素材（记录关联）

均为全新表，不影响既有表；`material_link_pwd` 预留密文存储位（明文可空，
真实密文由应用层写入）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0036_drama_management"
down_revision: Union[str, None] = "0035_publish_profile_location"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. 剧目主表
    if "dramas" not in inspector.get_table_names():
        op.create_table(
            "dramas",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("code", sa.String(20), unique=True, nullable=False),
            sa.Column("name", sa.String(200), unique=True, nullable=False),
            sa.Column("frequency", sa.String(20), nullable=True),
            sa.Column("type", sa.String(30), nullable=True),
            sa.Column("tags", sa.JSON, nullable=True),
            sa.Column("rating", sa.String(20), nullable=True),
            sa.Column("synopsis", sa.Text, nullable=True),
            sa.Column("cover_file_key", sa.String(500), nullable=True),
            sa.Column("listing_status", sa.String(20), nullable=False, server_default="已上架"),
            sa.Column("updated_date", sa.Date, nullable=True),
            sa.Column("listed_at", sa.DateTime, nullable=True),
            sa.Column("material_link", sa.String(1000), nullable=True),
            sa.Column("material_link_pwd", sa.String(200), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_dramas_code", "dramas", ["code"])
        op.create_index("ix_dramas_name", "dramas", ["name"])
        op.create_index("ix_dramas_frequency", "dramas", ["frequency"])
        op.create_index("ix_dramas_listing_status", "dramas", ["listing_status"])
        op.create_index("ix_dramas_created_by", "dramas", ["created_by"])
        op.create_index("ix_dramas_operator_id", "dramas", ["operator_id"])

    # 2. 剧照表
    if "drama_stills" not in inspector.get_table_names():
        op.create_table(
            "drama_stills",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("drama_id", UUID(as_uuid=True), sa.ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False),
            sa.Column("file_key", sa.String(500), nullable=False),
            sa.Column("sort_order", sa.Integer, nullable=True, server_default="0"),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_drama_stills_drama_id", "drama_stills", ["drama_id"])

    # 3. 剧目↔视频号关联表
    if "drama_accounts" not in inspector.get_table_names():
        op.create_table(
            "drama_accounts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("drama_id", UUID(as_uuid=True), sa.ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("video_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("listed_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("drama_id", "account_id", name="uq_drama_account"),
        )
        op.create_index("ix_drama_accounts_drama_id", "drama_accounts", ["drama_id"])
        op.create_index("ix_drama_accounts_account_id", "drama_accounts", ["account_id"])

    # 4. 剧目↔发布素材关联表
    if "drama_materials" not in inspector.get_table_names():
        op.create_table(
            "drama_materials",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("drama_id", UUID(as_uuid=True), sa.ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False),
            sa.Column("material_id", UUID(as_uuid=True), sa.ForeignKey("publish_materials.id", ondelete="SET NULL"), nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_drama_materials_drama_id", "drama_materials", ["drama_id"])
        op.create_index("ix_drama_materials_material_id", "drama_materials", ["material_id"])
        op.create_index("ix_drama_materials_account_id", "drama_materials", ["account_id"])


def downgrade() -> None:
    op.drop_table("drama_materials")
    op.drop_table("drama_accounts")
    op.drop_table("drama_stills")
    op.drop_table("dramas")
