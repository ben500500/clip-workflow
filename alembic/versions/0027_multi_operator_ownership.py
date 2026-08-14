"""add multi-operator ownership fields + publish_batches

Revision ID: 0027_multi_operator_ownership
Revises: 0026_worker_node_encoder_capabilities
Create Date: 2026-08-14

视频号「多运营者」发布 Phase 0（方案 v3.1，R14/R17）：
- video_accounts / publish_profiles 新增 created_by（操作人）与 operator_id（号主），
  支撑 RBAC own/all 数据隔离（运营专员仅见自己归属/授权的号）。
- publish_profiles 新增 tier/proxy_url/fingerprint_profile/egress_ip/chrome_debug_host/grad_status
  毕业（Tier 0→3）字段（Part 3）。
- publish_tasks 新增 batch_id（批次外键）与 operator_id（号主，创建后不迁移）。
- 新增 publish_batches 批次表（均分/轮询/指定策略，batch 级分配逻辑）。

全部新列均 DEFAULT NULL，不锁表；存量数据 backfill NULL/创建者，向后兼容。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0027_multi_operator_ownership"
down_revision: Union[str, None] = "0026_worker_node_encoder_capabilities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── video_accounts：归属字段 ──
    if "video_accounts" in inspector.get_table_names():
        for col, coltype in (
            ("created_by", "UUID"),
            ("operator_id", "UUID"),
        ):
            cols = [c["name"] for c in inspector.get_columns("video_accounts")]
            if col not in cols:
                op.execute(
                    f"ALTER TABLE video_accounts ADD COLUMN IF NOT EXISTS {col} {coltype}"
                )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_video_accounts_created_by ON video_accounts (created_by)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_video_accounts_operator_id ON video_accounts (operator_id)"
        )

    # ── publish_profiles：归属 + 毕业字段 ──
    if "publish_profiles" in inspector.get_table_names():
        for col, coltype in (
            ("created_by", "UUID"),
            ("operator_id", "UUID"),
            ("tier", "INTEGER"),
            ("proxy_url", "VARCHAR(500)"),
            ("fingerprint_profile", "JSONB"),
            ("egress_ip", "VARCHAR(100)"),
            ("chrome_debug_host", "VARCHAR(200)"),
            ("grad_status", "VARCHAR(50)"),
        ):
            cols = [c["name"] for c in inspector.get_columns("publish_profiles")]
            if col not in cols:
                default = ""
                if col == "tier":
                    default = " DEFAULT 0"
                op.execute(
                    f"ALTER TABLE publish_profiles ADD COLUMN IF NOT EXISTS {col} {coltype}{default}"
                )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_publish_profiles_created_by ON publish_profiles (created_by)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_publish_profiles_operator_id ON publish_profiles (operator_id)"
        )

    # ── publish_batches 批次表 ──
    if "publish_batches" not in inspector.get_table_names():
        op.create_table(
            "publish_batches",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("strategy", sa.String(50), nullable=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("total_items", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_publish_batches_created_by", "publish_batches", ["created_by"]
        )
        op.create_index(
            "ix_publish_batches_account_id", "publish_batches", ["account_id"]
        )

    # ── publish_tasks：batch_id + operator_id ──
    if "publish_tasks" in inspector.get_table_names():
        for col, coltype in (
            ("batch_id", "UUID"),
            ("operator_id", "UUID"),
        ):
            cols = [c["name"] for c in inspector.get_columns("publish_tasks")]
            if col not in cols:
                op.execute(
                    f"ALTER TABLE publish_tasks ADD COLUMN IF NOT EXISTS {col} {coltype}"
                )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_publish_tasks_batch_id ON publish_tasks (batch_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_publish_tasks_operator_id ON publish_tasks (operator_id)"
        )
        # 批次外键（SET NULL，兼容删除批次场景）
        fks = [fk["name"] for fk in inspector.get_foreign_keys("publish_tasks")]
        if "fk_publish_tasks_batch_id" not in fks:
            op.execute(
                "ALTER TABLE publish_tasks ADD CONSTRAINT fk_publish_tasks_batch_id "
                "FOREIGN KEY (batch_id) REFERENCES publish_batches(id) ON DELETE SET NULL"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "publish_tasks" in inspector.get_table_names():
        fks = [fk["name"] for fk in inspector.get_foreign_keys("publish_tasks")]
        if "fk_publish_tasks_batch_id" in fks:
            op.execute("ALTER TABLE publish_tasks DROP CONSTRAINT fk_publish_tasks_batch_id")
        op.execute("ALTER TABLE publish_tasks DROP COLUMN IF EXISTS batch_id")
        op.execute("ALTER TABLE publish_tasks DROP COLUMN IF EXISTS operator_id")

    if "publish_batches" in inspector.get_table_names():
        op.drop_table("publish_batches")

    if "publish_profiles" in inspector.get_table_names():
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS created_by")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS operator_id")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS tier")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS proxy_url")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS fingerprint_profile")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS egress_ip")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS chrome_debug_host")
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS grad_status")

    if "video_accounts" in inspector.get_table_names():
        op.execute("ALTER TABLE video_accounts DROP COLUMN IF EXISTS created_by")
        op.execute("ALTER TABLE video_accounts DROP COLUMN IF EXISTS operator_id")
