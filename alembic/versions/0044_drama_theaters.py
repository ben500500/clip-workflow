"""新增 剧目↔剧场 多对多关联表 drama_theaters（ISSUE #142）

Revision ID: 0044_drama_theaters
Revises: 0043_theater
Create Date: 2026-08-24

需求「剧目库中的剧目关联剧场，一对多」：
- 同一剧目可出现在多个剧场（如「海漫剧场」及其它剧场同时上架）。
- 新增 `drama_theaters` 关联表（drama_id ↔ theater_id，联合唯一）。
- 兼容既有 `dramas.theater_id`（一剧一场遗留）：老库升级由 database.py
  `_backfill_drama_theaters` 把存量 theater_id 回填进关联表；此后以关联表为权威。

downgrade 可回滚（删除表）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0044_drama_theaters"
down_revision: Union[str, None] = "0043_theater"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drama_theaters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("drama_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theater_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("theaters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("drama_id", "theater_id", name="uq_drama_theater"),
    )
    op.create_index("ix_drama_theaters_drama_id", "drama_theaters", ["drama_id"])
    op.create_index("ix_drama_theaters_theater_id", "drama_theaters", ["theater_id"])

    # 存量回填：把 dramas.theater_id 带入关联表（幂等）
    op.execute(
        sa.text("""
            INSERT INTO drama_theaters (id, drama_id, theater_id, created_at)
            SELECT gen_random_uuid(), d.id, d.theater_id, now()
            FROM dramas d
            WHERE d.theater_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM drama_theaters dt
                  WHERE dt.drama_id = d.id AND dt.theater_id = d.theater_id
              )
        """)
    )


def downgrade() -> None:
    op.drop_index("ix_drama_theaters_theater_id", table_name="drama_theaters")
    op.drop_index("ix_drama_theaters_drama_id", table_name="drama_theaters")
    op.drop_table("drama_theaters")
