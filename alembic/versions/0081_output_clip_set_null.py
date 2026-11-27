"""set null on slice output candidate deletion

Revision ID: 0081_output_clip_set_null
Revises: 0080_slice_task_output_clip_ids
"""
from alembic import op

revision = "0081_output_clip_set_null"
down_revision = "0080_slice_task_output_clip_ids"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("slice_outputs_clip_id_fkey", "slice_outputs", type_="foreignkey")
    op.create_foreign_key(
        "slice_outputs_clip_id_fkey",
        "slice_outputs",
        "clip_candidates",
        ["clip_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("slice_outputs_clip_id_fkey", "slice_outputs", type_="foreignkey")
    op.create_foreign_key(
        "slice_outputs_clip_id_fkey",
        "slice_outputs",
        "clip_candidates",
        ["clip_id"],
        ["id"],
    )
