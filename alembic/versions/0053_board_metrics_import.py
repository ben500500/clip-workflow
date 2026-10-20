"""video_metrics 增加看板自动导入所需列（today_play_count / avg_play_time / drama_name / source）

Revision ID: 0053_board_metrics_import
Revises: 0052_wechat_dl_prompt_task_upload
Create Date: 2026-10-21

ISSUE #366：看板接入真实数据源 —— 163 同机 `data-update` 视频号采集系统的
`board_data.json`（每 2 小时一轮）自动导入 `video_metrics`。

源字段比现有表多几列口径，补齐：
- `today_play_count`：源 `today_plays`（今日播放）
- `avg_play_time`：源 `avg_play_time`（平均播放时长，秒）
- `drama_name`：源 `drama_name`（has_drama=false 时置 NULL）
- `source`：数据来源标记，手动 Excel 导入留默认 'import'，自动同步写 'board'

⚠️ 部署链路不跑 `alembic upgrade head`（alembic-migrate 容器只 stamp head），
存量库加列的唯一生效路径是 backend/app/database.py 的 `_apply_compat_migrations`
幂等补列清单 —— 本迁移**必须**与 models/dashboard.py、compat 清单三处同步，缺一即 500。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0053_board_metrics_import"
down_revision: Union[str, None] = "0052_wechat_dl_prompt_task_upload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("video_metrics", sa.Column("today_play_count", sa.Integer(), nullable=True))
    op.add_column("video_metrics", sa.Column("avg_play_time", sa.Double(), nullable=True))
    op.add_column("video_metrics", sa.Column("drama_name", sa.String(200), nullable=True))
    op.add_column(
        "video_metrics",
        sa.Column("source", sa.String(20), nullable=False, server_default="import"),
    )


def downgrade() -> None:
    op.drop_column("video_metrics", "source")
    op.drop_column("video_metrics", "drama_name")
    op.drop_column("video_metrics", "avg_play_time")
    op.drop_column("video_metrics", "today_play_count")
