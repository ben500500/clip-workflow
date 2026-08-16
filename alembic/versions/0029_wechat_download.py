"""add wechat_download tables + episodes.source_url

Revision ID: 0029_wechat_download
Revises: 0028_multi_operator_audit
Create Date: 2026-08-16

视频号素材导入下载能力（Issue #150，立项决策④：并入 + 可剥离）P0：
- 新增 3 张独立表（随 wechat_download 独立包走）：
  - wechat_download_tasks   下载任务表（URL 导入 → 解析 → 拉流 → 入库）
  - wechat_source_auths     已授权素材授权表（立项决策①：允许已授权第三方素材，
                            未授权拦截 R1 硬红线）
  - wechat_parse_records    解析结果记录表（元宝/预览层，可追溯）
- episodes 增加最小粘合字段 source_url（来源链接，便于溯源；剥离时可保留为最小粘合）。

全部为新增，向后兼容；downgrade 可回滚。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0029_wechat_download"
down_revision: Union[str, None] = "0028_multi_operator_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── wechat_download_tasks 下载任务表 ──
    op.create_table(
        "wechat_download_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("video_meta", sa.JSON(), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="authorized"),
        sa.Column("source_authorize", sa.Text(), nullable=True),
        sa.Column("auth_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_key", sa.String(500), nullable=True),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wechat_download_tasks_status", "wechat_download_tasks", ["status"])
    op.create_index("ix_wechat_download_tasks_created_by", "wechat_download_tasks", ["created_by"])
    op.create_index("ix_wechat_download_tasks_episode_id", "wechat_download_tasks", ["episode_id"])

    # ── wechat_source_auths 授权素材表 ──
    op.create_table(
        "wechat_source_auths",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("authorize_owner", sa.String(255), nullable=True),
        sa.Column("authorize_type", sa.String(50), nullable=False, server_default="other"),
        sa.Column("authorize_scope", sa.Text(), nullable=True),
        sa.Column("authorize_note", sa.Text(), nullable=True),
        sa.Column("authorize_file_key", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wechat_source_auths_created_by", "wechat_source_auths", ["created_by"])

    # ── wechat_parse_records 解析结果表 ──
    op.create_table(
        "wechat_parse_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wechat_download_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("play_url", sa.String(2000), nullable=True),
        sa.Column("result_meta", sa.JSON(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("download_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wechat_parse_records_task_id", "wechat_parse_records", ["task_id"])

    # ── episodes 最小粘合字段 source_url（来源链接溯源）──
    op.add_column("episodes", sa.Column("source_url", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "source_url")
    op.drop_index("ix_wechat_parse_records_task_id", table_name="wechat_parse_records")
    op.drop_table("wechat_parse_records")
    op.drop_index("ix_wechat_source_auths_created_by", table_name="wechat_source_auths")
    op.drop_table("wechat_source_auths")
    op.drop_index("ix_wechat_download_tasks_episode_id", table_name="wechat_download_tasks")
    op.drop_index("ix_wechat_download_tasks_created_by", table_name="wechat_download_tasks")
    op.drop_index("ix_wechat_download_tasks_status", table_name="wechat_download_tasks")
    op.drop_table("wechat_download_tasks")
