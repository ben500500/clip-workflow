"""需求三 S3/S4（2026-11-24）：叠加预设表 asset_overlay_presets ＋ asset_outputs.compose_meta

用户 11-24 原话：「s3 和 s4 继续」（把 11-23 定稿时留到下一期的组合导出两批做完）。

- asset_overlay_presets：一线「同一个剧的所有投放素材，角标/警示语/剧名一模一样」，
  一天拼 20 支不可能每支手填一遍位置字号透明度。参数形状直接对齐引擎侧
  `apply_badges` / `apply_text_overlays` 两个纯函数吃的字典，不新造中间结构。
- asset_outputs.compose_meta：矩阵每一格「哪支钩子 × 哪条正片（＋片尾）＋哪套预设的
  哪份参数快照」。可空，老行 NULL＝不是矩阵产物。

生效路径（与 0075 同一套，163 现网实测过）：
- 163：alembic-migrate 容器跑 init_db()——create_all 建新表（含索引），
  asset_outputs 的老表由 app/database.py 的 compat 清单 ADD COLUMN 补列，然后 stamp head。
- 本地 override（alembic upgrade head）：本迁移 create_table＋create_index＋add_column。

⚠️ 预设名「同归属不可重名」的判重**只在接口里做**（409），这里刻意不建唯一索引：
老库靠 ADD COLUMN 补列补不出约束，建了会出现"新库拦、老库不拦"的两套行为
（同 `asset_outputs.composed_from_output_id` 那条注释的理由）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0076_asset_overlay_presets"
down_revision: Union[str, None] = "0075_autoclip_run_reuse"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_overlay_presets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("scope", sa.String(length=12), nullable=False, server_default="user"),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_overlay_presets_scope", "asset_overlay_presets", ["scope"])
    op.create_index("ix_asset_overlay_presets_owner_id", "asset_overlay_presets", ["owner_id"])
    op.create_index("ix_asset_overlay_presets_created_at", "asset_overlay_presets", ["created_at"])
    op.add_column("asset_outputs", sa.Column("compose_meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_outputs", "compose_meta")
    op.drop_index("ix_asset_overlay_presets_created_at", table_name="asset_overlay_presets")
    op.drop_index("ix_asset_overlay_presets_owner_id", table_name="asset_overlay_presets")
    op.drop_index("ix_asset_overlay_presets_scope", table_name="asset_overlay_presets")
    op.drop_table("asset_overlay_presets")
