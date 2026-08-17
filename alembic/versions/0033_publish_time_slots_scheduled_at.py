"""add publish time slots and scheduled_at

Revision ID: 0033_publish_time_slots_scheduled_at
Revises: 0032_channel_video_account_unique
Create Date: 2026-08-17

定时发布（R99）：
- publish_tasks 新增 scheduled_at（预约发布时间，非空=定时、空=立即）与 time_slot_label（窗口快照）。
- 新增 publish_time_slots 时间窗口配置表（预置 07:00-08:00 / 18:00-20:00 + 自定义），
  用于前端选择发布窗口并在窗口内错峰随机选点。

downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0033_publish_time_slots_scheduled_at"
down_revision: Union[str, None] = "0032_channel_video_account_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # publish_tasks：定时预约字段（可空，保持立即发布兼容）
    op.add_column("publish_tasks", sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("publish_tasks", sa.Column("time_slot_label", sa.String(length=100), nullable=True))
    op.create_index("ix_publish_tasks_scheduled_at", "publish_tasks", ["scheduled_at"])

    # publish_time_slots 时间窗口配置表
    op.create_table(
        "publish_time_slots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("is_preset", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_publish_time_slots_created_by", "publish_time_slots", ["created_by"])

    # 预置两个时间窗口（系统内置，不可删除/改时段）
    _insert_slot("早晨黄金档", "07:00", "08:00", True)
    _insert_slot("晚间黄金档", "18:00", "20:00", True)


def _insert_slot(name: str, start: str, end: str, preset: bool) -> None:
    import uuid as _uuid
    from datetime import datetime
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO publish_time_slots (id, name, start_time, end_time, enabled, is_preset, created_at) "
            "VALUES (:id, :name, :start_time, :end_time, true, :preset, :created_at)"
        ),
        {
            "id": str(_uuid.uuid4()),
            "name": name,
            "start_time": start,
            "end_time": end,
            "preset": preset,
            "created_at": datetime.utcnow(),
        },
    )


def downgrade() -> None:
    op.drop_index("ix_publish_time_slots_created_by", table_name="publish_time_slots")
    op.drop_table("publish_time_slots")
    op.drop_index("ix_publish_tasks_scheduled_at", table_name="publish_tasks")
    op.drop_column("publish_tasks", "time_slot_label")
    op.drop_column("publish_tasks", "scheduled_at")
