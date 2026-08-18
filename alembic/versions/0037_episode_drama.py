"""剧集维度打通切片产线：episodes.drama_id 关联剧目

Revision ID: 0037_episode_drama
Revises: 0036_drama_management
Create Date: 2026-08-18

ISSUE #130「视频号自动发布」→ 剧目管理 P2「剧集维度打通切片产线」。

为 `episodes` 表新增可空外键 `drama_id` → `dramas.id`（ondelete=SET NULL），
使剧集能归属到剧目，从而在剧目维度聚合「该剧已切片/待切片」的切片产线状态。

零侵入：既有剧集 drama_id 为空，行为与现状完全一致。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0037_episode_drama"
down_revision: Union[str, None] = "0036_drama_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("episodes")}
    if "drama_id" not in cols:
        op.add_column(
            "episodes",
            sa.Column(
                "drama_id",
                UUID(as_uuid=True),
                sa.ForeignKey("dramas.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    idx_names = {i["name"] for i in inspector.get_indexes("episodes")}
    if "ix_episodes_drama_id" not in idx_names:
        op.create_index("ix_episodes_drama_id", "episodes", ["drama_id"])


def downgrade() -> None:
    op.drop_index("ix_episodes_drama_id", table_name="episodes")
    op.drop_column("episodes", "drama_id")
