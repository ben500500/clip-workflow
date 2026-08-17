"""多视频号素材去重数据层（ClipVariant / VideoFingerprint + 列扩展）

Revision ID: 0034_multi_video_dedup_variants
Revises: 0033_publish_time_slots_scheduled_at
Create Date: 2026-08-17

圆桌定稿 Phase 0 数据层：
- 新表 clip_variants：素材变体（一个切片输出的 N 套去重版本），硬约束一账号一变体。
- 新表 video_fingerprints：视频指纹（phash / 音频声纹 / 时域序列，覆盖 L3/L4 盲区）。
- slice_outputs 新增 variant_group_id（变体组聚合，未开多版本为 NULL，零侵入）。
- publications 新增 variant_id（发布回写变体，便于审计）。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0034_multi_video_dedup_variants"
down_revision: Union[str, None] = "0033_publish_time_slots_scheduled_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 现有表列扩展 ──
    op.add_column("slice_outputs", sa.Column("variant_group_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_slice_outputs_variant_group_id", "slice_outputs", ["variant_group_id"])

    op.add_column("publications", sa.Column("variant_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_publications_variant_id", "publications", ["variant_id"])

    op.add_column("slice_tasks", sa.Column("variant_count", sa.Integer(), nullable=True))

    # ── clip_variants 素材变体表 ──
    op.create_table(
        "clip_variants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("output_id", UUID(as_uuid=True), sa.ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_group_id", UUID(as_uuid=True), nullable=True),
        sa.Column("variant_index", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("file_key", sa.String(length=500), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("resolution", sa.String(length=50), nullable=True),
        sa.Column("dedupe_config", sa.JSON(), nullable=True),
        sa.Column("structural_diff", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True, server_default="pending"),
        sa.Column("phash_distance", sa.Float(), nullable=True),
        sa.Column("audio_distance", sa.Float(), nullable=True),
        sa.Column("collision", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("collision_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", name="uq_clip_variants_account_id"),
    )
    op.create_index("ix_clip_variants_output_id", "clip_variants", ["output_id"])
    op.create_index("ix_clip_variants_variant_group_id", "clip_variants", ["variant_group_id"])
    op.create_index("ix_clip_variants_account_id", "clip_variants", ["account_id"])
    op.create_index("ix_clip_variants_created_by", "clip_variants", ["created_by"])

    # ── video_fingerprints 视频指纹表 ──
    op.create_table(
        "video_fingerprints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("output_id", UUID(as_uuid=True), sa.ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("clip_variants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("file_key", sa.String(length=500), nullable=True),
        sa.Column("algorithm", sa.String(length=50), nullable=False, server_default="phash_v1"),
        sa.Column("hash_value", sa.Text(), nullable=True),
        sa.Column("vector", sa.Text(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("resolution", sa.String(length=50), nullable=True),
        sa.Column("variant_group_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_video_fingerprints_output_id", "video_fingerprints", ["output_id"])
    op.create_index("ix_video_fingerprints_variant_id", "video_fingerprints", ["variant_id"])
    op.create_index("ix_video_fingerprints_variant_group_id", "video_fingerprints", ["variant_group_id"])

    # 启用 pgvector 扩展（可选；不可用时不影响，指纹服务回退字符串距离）
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column("slice_tasks", "variant_count")
    op.drop_index("ix_publications_variant_id", table_name="publications")
    op.drop_column("publications", "variant_id")
    op.drop_index("ix_slice_outputs_variant_group_id", table_name="slice_outputs")
    op.drop_column("slice_outputs", "variant_group_id")
    op.drop_table("video_fingerprints")
    op.drop_table("clip_variants")
