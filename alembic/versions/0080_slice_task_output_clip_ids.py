"""Persist the task-time output-to-candidate binding snapshot.

Revision ID: 0080_slice_task_output_clip_ids
Revises: 0079_asset_summary_is_shell
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0080_slice_task_output_clip_ids"
down_revision: Union[str, None] = "0079_asset_summary_is_shell"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("slice_tasks", sa.Column("output_clip_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("slice_tasks", "output_clip_ids")
