"""slice_tasks.remotion_output_file_key 加宽为 text

背景（2026-11-21 生产实测）：Remotion 多成品任务（本例 20 个产物）完成回写时
`remotion_output_file_key = ",".join(keys)` ≈ 1100 字符，超过 varchar(500) →
commit 抛 DBAPIError → celery 重试耗尽任务失败。每重试一次都完整重跑一遍
Chromium 渲染，浪费严重且无自愈路径。

修复：列加宽为 text（163 生产已手动执行本 ALTER，此迁移用于其余环境对齐）。

Revision ID: 0071_remotion_key_text
Revises: 0070_production_is_trial
"""
from alembic import op
import sqlalchemy as sa

revision = "0071_remotion_key_text"
down_revision = "0070_production_is_trial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "slice_tasks",
        "remotion_output_file_key",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
    )


def downgrade() -> None:
    op.alter_column(
        "slice_tasks",
        "remotion_output_file_key",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
    )
