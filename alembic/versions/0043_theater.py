"""新增剧场（theaters）表 + 剧目/视频号挂剧场列

Revision ID: 0043_theater
Revises: 0042_clip_candidate_clip_type
Create Date: 2026-08-24

对应需求「剧目直接挂剧场 + 视频号列表页剧场管理」：
- 新增 `theaters` 剧场主数据表；
- `dramas.theater_id`：剧目直接挂剧场（一剧一场，可空，删除剧场置空）；
- `channel_accounts.theater_id`：视频号台账挂剧场（用于视频号列表按剧场筛选）；
- `video_accounts.theater_id`：发布账号库挂剧场（与台账口径一致）。

downgrade 可回滚（删除列/表）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0043_theater"
down_revision: Union[str, None] = "0042_clip_candidate_clip_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "theaters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_theaters_name", "theaters", ["name"], unique=True)
    op.create_index("ix_theaters_created_by", "theaters", ["created_by"])
    op.create_index("ix_theaters_operator_id", "theaters", ["operator_id"])

    # 剧目挂剧场（删除剧场置空）
    op.add_column(
        "dramas",
        sa.Column("theater_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_dramas_theater_id", "dramas", ["theater_id"])
    op.create_foreign_key(
        "fk_dramas_theater_id",
        "dramas",
        "theaters",
        ["theater_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 视频号台账挂剧场（可空，软关联，不设物理 FK 以对齐 video_account_id 的软关联风格）
    op.add_column(
        "channel_accounts",
        sa.Column("theater_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_channel_accounts_theater_id", "channel_accounts", ["theater_id"])

    # 发布账号库挂剧场（可空）
    op.add_column(
        "video_accounts",
        sa.Column("theater_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_video_accounts_theater_id", "video_accounts", ["theater_id"])


def downgrade() -> None:
    op.drop_index("ix_video_accounts_theater_id", table_name="video_accounts")
    op.drop_column("video_accounts", "theater_id")

    op.drop_index("ix_channel_accounts_theater_id", table_name="channel_accounts")
    op.drop_column("channel_accounts", "theater_id")

    op.drop_constraint("fk_dramas_theater_id", "dramas", type_="foreignkey")
    op.drop_index("ix_dramas_theater_id", table_name="dramas")
    op.drop_column("dramas", "theater_id")

    op.drop_index("ix_theaters_operator_id", table_name="theaters")
    op.drop_index("ix_theaters_created_by", table_name="theaters")
    op.drop_index("ix_theaters_name", table_name="theaters")
    op.drop_table("theaters")
