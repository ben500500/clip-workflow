"""素材隔离（2026-11-24）：脚本收藏表 asset_script_favorites

用户 11-24 原话：「加入素材隔离的概念，但默认是要能看到全部的，但是可以加入一个开关
或者复选框，仅看自己。这个仅看自己，不是说仅仅是自己导入的文案也可以在已有的脚本库
里面勾选，然后收藏起来。」

「仅看自己」要能装下**别人的脚本**（我收藏的那些），所以需要一个 (人, 脚本) 的关系表：
- 不动 `asset_scripts.owner_id`——owner 是写权限锚点（`_assert_script_owner` 只认它），
  收藏不等于拥有，改了就把原作者的编辑权拿走了；
- 也不给脚本加数组列——"我的收藏"要能走索引查，脚本硬删时关系要自动收干净。

生效路径（与 0075/0076 同一套）：
- 163：alembic-migrate 容器跑 init_db() → create_all 建新表（含索引与唯一约束），随后 stamp head。
  新表**不需要** database.py 的 compat 补列（那张清单只管老表加列）。
- 本地 override（alembic upgrade head）：本迁移 create_table。

唯一约束建在这里是有意的：`(user_id, script_id)` 重复插入是并发双击收藏的实际形态，
接口层的"先查后插"两个请求可以同时穿过；这张表是新表，老库不存在"补不出约束"的问题
（对比 0076 对预设名判重刻意不建唯一索引的理由）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0077_asset_script_favorites"
down_revision: Union[str, None] = "0076_asset_overlay_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_script_favorites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("script_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["script_id"], ["asset_scripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "script_id", name="uq_asset_script_favorites_user_script"),
    )
    op.create_index("ix_asset_script_favorites_user_id", "asset_script_favorites", ["user_id"])
    op.create_index("ix_asset_script_favorites_script_id", "asset_script_favorites", ["script_id"])
    op.create_index("ix_asset_script_favorites_created_at", "asset_script_favorites", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_asset_script_favorites_created_at", table_name="asset_script_favorites")
    op.drop_index("ix_asset_script_favorites_script_id", table_name="asset_script_favorites")
    op.drop_index("ix_asset_script_favorites_user_id", table_name="asset_script_favorites")
    op.drop_table("asset_script_favorites")
