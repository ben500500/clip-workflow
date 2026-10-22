"""新增 zhiling_service_tasks 表（智令其他服务：文案提取/AI消除/画质修复/TTS/音色训练）

Revision ID: 0054_zhiling_service_tasks
Revises: 0053_board_metrics_import
Create Date: 2026-10-22

ISSUE #370：资源下载新增「其他服务」页签，接入智令 doc/102 / doc/114 / doc/123 /
doc/108 / doc/128 五个能力。五条链路结构高度重合，共用一张表 + `task_type` 区分，
差异参数收在 `params`（JSON）里。

该表属 wechat_download 独立包（自持 WechatDownloadBase），随包走；仅新增表、
不改动主系统任何表，downgrade 可回滚。

⚠️ 与 0051 同理：新表由 init_db() 的 `_ensure_wechat_download_tables()` create_all
兜底创建，部署链路不跑 `alembic upgrade head` 也不会缺表；本迁移供 fresh DB / 版本链参考。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0054_zhiling_service_tasks"
down_revision: Union[str, None] = "0053_board_metrics_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "zhiling_service_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("input_url", sa.String(1000), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("provider_task_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("result_url", sa.String(1000), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("srt_text", sa.Text(), nullable=True),
        sa.Column("voice_model_id", sa.String(100), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_zhiling_service_tasks_created_by", "zhiling_service_tasks", ["created_by"])
    op.create_index("ix_zhiling_service_tasks_task_type", "zhiling_service_tasks", ["task_type"])
    op.create_index("ix_zhiling_service_tasks_status", "zhiling_service_tasks", ["status"])
    op.create_index(
        "ix_zhiling_service_tasks_provider_task_id", "zhiling_service_tasks", ["provider_task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_zhiling_service_tasks_provider_task_id", table_name="zhiling_service_tasks")
    op.drop_index("ix_zhiling_service_tasks_status", table_name="zhiling_service_tasks")
    op.drop_index("ix_zhiling_service_tasks_task_type", table_name="zhiling_service_tasks")
    op.drop_index("ix_zhiling_service_tasks_created_by", table_name="zhiling_service_tasks")
    op.drop_table("zhiling_service_tasks")
