"""add lan_source_imports table

Revision ID: 0038_lan_source
Revises: 0037_episode_drama
Create Date: 2026-08-19

局域网获取剧集导入能力（ISSUE #142 后续需求）P0：
- 新增 1 张独立表（随 lan_source 独立包走）：
  - lan_source_imports  导入任务表（剧目 → 逐集发现直链 → 下载 → 入库 审计）

剧目落 dramas、剧集落 projects/episodes（复用主系统表），仅通过
episodes.source_url 与 episodes.drama_id 最小粘合，无新增核心字段。

全部为新增，向后兼容；downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0038_lan_source"
down_revision: Union[str, None] = "0037_episode_drama"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── lan_source_imports 局域网剧集导入任务表 ──
    op.create_table(
        "lan_source_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("drama_name", sa.String(200), nullable=False),
        sa.Column("drama_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("total_episodes", sa.Integer(), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("episode_items", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_lan_source_imports_status", "lan_source_imports", ["status"])
    op.create_index("ix_lan_source_imports_created_by", "lan_source_imports", ["created_by"])
    op.create_index("ix_lan_source_imports_drama_name", "lan_source_imports", ["drama_name"])


def downgrade() -> None:
    op.drop_index("ix_lan_source_imports_drama_name", table_name="lan_source_imports")
    op.drop_index("ix_lan_source_imports_created_by", table_name="lan_source_imports")
    op.drop_index("ix_lan_source_imports_status", table_name="lan_source_imports")
    op.drop_table("lan_source_imports")
