"""add autoclip_runs table

Revision ID: 0002_autoclip_runs
Revises: 0001_initial
Create Date: 2026-08-07

AI 选点执行历史表：每次「启动选点 / 重新选点」都会落库一条记录，
供工作台历史展示。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_autoclip_runs"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autoclip_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("autoclip_project_id", sa.String(100), nullable=True),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("progress", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_autoclip_runs_episode_id", "autoclip_runs", ["episode_id"])


def downgrade() -> None:
    op.drop_index("ix_autoclip_runs_episode_id", table_name="autoclip_runs")
    op.drop_table("autoclip_runs")
