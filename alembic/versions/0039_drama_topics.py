"""剧目增加发布话题字段 topics

Revision ID: 0039_drama_topics
Revises: 0038_lan_source
Create Date: 2026-08-19

ISSUE #93「视频号AI短剧切片｜50岁+中老年话题标签组合」。

dramas 表新增 `topics` JSON 列：保存该剧目选好的发布话题标签（如
["#短剧", "#婆媳关系", "#家庭伦理剧"]）。在剧目详情中按「话题大方向」选择
自动带入对应话题组合并保存，发布时直接复用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0039_drama_topics"
down_revision: Union[str, None] = "0038_lan_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "dramas" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("dramas")}
        if "topics" not in cols:
            op.add_column("dramas", sa.Column("topics", sa.JSON, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dramas" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("dramas")}
        if "topics" in cols:
            op.drop_column("dramas", "topics")
