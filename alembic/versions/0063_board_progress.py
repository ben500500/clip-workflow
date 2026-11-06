"""投放进度可视化（11-06 批 L）：板子侧状态写回生产单行

Revision ID: 0063_board_progress
Revises: 0062_asset_play_url_cache
Create Date: 2026-11-06

用户报的洞：投板之后界面上看不到进度——生产单列表不会自动刷新，状态列停在
「投放中」，也看不出板子是在排队还是真在出片。板子侧其实每 45s 都在被后台
协程回读，只是回读结果没落到生产单行上，前端无从展示。

修法：`asset_productions` 加 `board_last_status` / `board_last_check_at` 两列。
轮询每轮把板面看到的行状态（waiting/running/succ…）连同检查时间写回；认领 tid
的瞬间先写「已投板」。前端据此展示「板子：出片中·上轮检查 20:47」并自动刷新。

⚠️ 全部可空、不回填：没投过板的单/老单＝NULL，语义就是「没有板侧信息」。
⚠️ 生效路径（与 0055~0062 同一条部署约束）：部署链路不跑 `alembic upgrade head`
（alembic-migrate 容器只 stamp head），老库加列的唯一生效路径是 `app/database.py`
那张 ADD COLUMN 清单（已同步登记）；本迁移供 fresh DB、版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0063_board_progress"
down_revision: Union[str, None] = "0062_asset_play_url_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_productions", sa.Column("board_last_status", sa.String(60), nullable=True))
    op.add_column("asset_productions", sa.Column("board_last_check_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_productions", "board_last_check_at")
    op.drop_column("asset_productions", "board_last_status")
