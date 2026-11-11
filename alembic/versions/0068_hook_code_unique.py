"""一钩一号的 DB 底线（2026-11-11 七席评审·业务 P0）：钩子编号双表部分唯一索引

为什么要在数据库层兜：应用层查重（投产口 7556、预取口 _auto_park、手工钉号）都是
普通 SELECT 前置提示，而投产口从查重到真实 INSERT 之间隔着 n×90-150s 的模型展开——
竞态窗口是分钟级不是毫秒级。两人先后开同一个号，后查的人看到的是前者未提交的空库，
两张单都落库、板上出现两条同名任务、回收对不上账：这正是 11-06 拍板③ 要防的事故，
查重 SELECT 拦不住，唯一索引拦得住。

两张表各建一条**部分唯一索引**（WHERE hook_code IS NOT NULL）：
- asset_productions.hook_code  —— 已投出去的号（一发即烧的事实台账）
- asset_summaries.hook_code    —— 预取位（号先钉在文案上等着开单顶掉）

NULL（无号单/未预取/已消费清空）不参与唯一性。163 现网两表已核对零重复（2026-11-11），
索引可直接建；写入路径撞约束时由 assets.py 统一转 409 点名。

生效路径同 0055~0067：alembic-migrate 容器随 alembic/ 变更重建后跑 upgrade head。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0068_hook_code_unique"
down_revision: Union[str, None] = "0067_asset_auto_concat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HOOK_WHERE = sa.text("hook_code IS NOT NULL")


def upgrade() -> None:
    op.create_index(
        "uq_asset_productions_hook_code",
        "asset_productions",
        ["hook_code"],
        unique=True,
        postgresql_where=_HOOK_WHERE,
        sqlite_where=_HOOK_WHERE,
    )
    op.create_index(
        "uq_asset_summaries_hook_code",
        "asset_summaries",
        ["hook_code"],
        unique=True,
        postgresql_where=_HOOK_WHERE,
        sqlite_where=_HOOK_WHERE,
    )


def downgrade() -> None:
    op.drop_index("uq_asset_summaries_hook_code", table_name="asset_summaries")
    op.drop_index("uq_asset_productions_hook_code", table_name="asset_productions")
