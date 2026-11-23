"""autoclip_runs 加 config_fp/source_key（选点复用）

同剧集+同源片+同参数指纹的已完成选点可直接复用候选，跳过选点流程。

Revision ID: 0075_autoclip_run_reuse
Revises: 0075_asset_scripts_ui_config
（2026-11-23 zcode：原写 Revises 0074_episode_fps——与同日先提交的 0075_asset_scripts_ui_config
  撞成**双头**，alembic `stamp head` 会报 Multiple head revisions。谁后提交谁接到后面，故改接它。
  本文件的其余内容一字未动。）
"""
from alembic import op
import sqlalchemy as sa

revision = "0075_autoclip_run_reuse"
down_revision = "0075_asset_scripts_ui_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("autoclip_runs", sa.Column("config_fp", sa.String(64), nullable=True))
    op.add_column("autoclip_runs", sa.Column("source_key", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("autoclip_runs", "source_key")
    op.drop_column("autoclip_runs", "config_fp")
