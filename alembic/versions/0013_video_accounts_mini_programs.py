"""add video_accounts / mini_programs and publish source links

Revision ID: 0013_video_accounts_mini_programs
Revises: 0012_prompt_default_duration
Create Date: 2026-08-09

一期「视频号矩阵 + 短片分析」：
- 新增 video_accounts 表：矩阵账号库（分组 / 平台标识 / 关联发布配置 / 小程序挂载资质）
- 新增 mini_programs 表：小程序链接库（appid / path / 带渠道归因参数的完整链接）
- publish_tasks 新增关联字段：
  video_account_id / mini_program_id / prompt_record_id / material_id
- video_metrics 新增 platform 字段：显式标记平台（wechat_channel / douyin / kuaishou）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013_video_accounts_mini_programs"
down_revision: Union[str, None] = "0012_prompt_default_duration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 视频号/抖音/快手账号库（矩阵管理）
    op.create_table(
        "video_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("group_name", sa.String(length=100), nullable=True),
        sa.Column("wxid", sa.String(length=200), nullable=True),
        sa.Column("account_uid", sa.String(length=200), nullable=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mini_program_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("remark", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_video_accounts_account_name", "video_accounts", ["account_name"])
    op.create_index("ix_video_accounts_platform", "video_accounts", ["platform"])

    # 小程序链接库
    op.create_table(
        "mini_programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("appid", sa.String(length=200), nullable=True),
        sa.Column("path", sa.String(length=500), nullable=True),
        sa.Column("full_link", sa.String(length=1000), nullable=False),
        sa.Column("remark", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    # publish_tasks 关联字段（账号矩阵 / 小程序库 / 短片来源）
    op.add_column(
        "publish_tasks",
        sa.Column("video_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("mini_program_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("prompt_record_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "publish_tasks",
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # video_metrics 平台显式标记
    op.add_column(
        "video_metrics",
        sa.Column("platform", sa.String(length=50), nullable=True),
    )

    # publish_materials 来源提示词记录（短片分析链路：发布素材 → 提示词）
    op.add_column(
        "publish_materials",
        sa.Column("prompt_record_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publish_materials", "prompt_record_id")
    op.drop_column("video_metrics", "platform")
    op.drop_column("publish_tasks", "material_id")
    op.drop_column("publish_tasks", "prompt_record_id")
    op.drop_column("publish_tasks", "mini_program_id")
    op.drop_column("publish_tasks", "video_account_id")
    op.drop_table("mini_programs")
    op.drop_index("ix_video_accounts_platform", table_name="video_accounts")
    op.drop_index("ix_video_accounts_account_name", table_name="video_accounts")
    op.drop_table("video_accounts")
