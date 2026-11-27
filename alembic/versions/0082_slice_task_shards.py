"""slice task sharding columns (parent_task_id / shard_index / shard_total)

Revision ID: 0082_slice_task_shards
Revises: 0081_output_clip_set_null

真分片（docs/1128-任务内真分片-工程方案-v2评审修订版）：分片行指向聚合父行。
生产 40/163 只 stamp head 不跑 upgrade——老库补列由 database.py compat 清单 +
部分索引兜底（create_all 不给已存在表补索引），本迁移仅保持 stamp 链一致。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0082_slice_task_shards"
down_revision = "0081_output_clip_set_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slice_tasks", sa.Column("parent_task_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("slice_tasks", sa.Column("shard_index", sa.Integer(), nullable=True))
    op.add_column("slice_tasks", sa.Column("shard_total", sa.Integer(), nullable=True))
    op.create_index(
        "ix_slice_tasks_parent",
        "slice_tasks",
        ["parent_task_id"],
        postgresql_where=sa.text("parent_task_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_slice_tasks_parent", table_name="slice_tasks")
    op.drop_column("slice_tasks", "shard_total")
    op.drop_column("slice_tasks", "shard_index")
    op.drop_column("slice_tasks", "parent_task_id")
