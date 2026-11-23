"""极简模式 S1/S2（2026-11-23）：脚本库表 asset_scripts ＋ user_preferences.ui_config

用户原话：「个人可自定义脚本库，把想要的脚本添加到个人脚本库，并可打开脚本修改」
「勾选脚本（打开个人脚本库可一次多选）→上传三视图→豆包生成视频」。

- asset_scripts：「脚本」＝直接投给豆包的成品提示词（不是钩子文案）。单独建表的理由：
  asset_summaries.asset_id 是 NOT NULL＋CASCADE（素材一删文案即消失），且只有 reviewed_by
  没有 owner，表达不了「个人的」。carrier_summary_id 回指生产载体（生产单必须挂在候选
  文案上），五环的 ②③ 列表默认把载体藏起来。
- user_preferences.ui_config：素材库界面偏好（极简/全量）。不复用 slice_config。

生效路径（两套环境都成立）：
- 163：alembic-migrate 容器跑 init_db()——create_all 建新表（含索引），
  user_preferences 的老表由 app/database.py 的 compat 清单 ADD COLUMN 补列，然后 stamp head。
- 本地 override（alembic upgrade head）：本迁移 create_table＋create_index＋add_column。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0075_asset_scripts_ui_config"
down_revision: Union[str, None] = "0074_episode_fps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_scripts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False, server_default="draft"),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("source_kind", sa.String(length=12), nullable=False, server_default="manual"),
        sa.Column("origin_asset_id", sa.UUID(), nullable=True),
        sa.Column("based_on_script_id", sa.UUID(), nullable=True),
        sa.Column("carrier_summary_id", sa.UUID(), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["category_id"], ["asset_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["origin_asset_id"], ["asset_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["based_on_script_id"], ["asset_scripts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["carrier_summary_id"], ["asset_summaries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_scripts_owner_id", "asset_scripts", ["owner_id"])
    op.create_index("ix_asset_scripts_created_at", "asset_scripts", ["created_at"])
    op.create_index("ix_asset_scripts_carrier_summary_id", "asset_scripts", ["carrier_summary_id"])
    # 只约束 ready 行：草稿允许重复（派生草稿在改字前与母稿逐字相同）
    op.create_index(
        "uq_asset_scripts_ready_body",
        "asset_scripts",
        ["owner_id", "body_hash"],
        unique=True,
        postgresql_where=sa.text("state = 'ready'"),
        sqlite_where=sa.text("state = 'ready'"),
    )
    op.add_column("user_preferences", sa.Column("ui_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_preferences", "ui_config")
    op.drop_index("uq_asset_scripts_ready_body", table_name="asset_scripts")
    op.drop_index("ix_asset_scripts_carrier_summary_id", table_name="asset_scripts")
    op.drop_index("ix_asset_scripts_created_at", table_name="asset_scripts")
    op.drop_index("ix_asset_scripts_owner_id", table_name="asset_scripts")
    op.drop_table("asset_scripts")
