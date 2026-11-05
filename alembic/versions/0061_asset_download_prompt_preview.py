"""批 J（11-05）：反推顺带下载原片 + 过审顺手备豆包提示词预览

Revision ID: 0061_asset_download_prompt_preview
Revises: 0060_asset_card_asset_ids
Create Date: 2026-11-05

两件用户点名的活，各加几列：

1. `asset_items.download_status`——反推时把链接素材的原片拉回自有桶（用户口径：
   「反推文案是默认将视频下载下来」，一线回看不用再回源翻时效直链）。NULL=没有要下的
   （文件素材本来就在桶里、图片不是视频）；running/success/failed 是下载动作自己的状态，
   **不进五阶段**（下载是回看用的副本，不是流水线的一环）。
2. `asset_summaries.prompt_preview` / `prompt_preview_at` / `cost_preview`——文案过审后
   顺手把豆包生产提示词展开一遍存下来（用户口径：「钩子文案出来后，把对应的豆包生产
   提示词也准备好，并通过一个地方展示出来」）。预览是「看」的，投产仍按当时参数重新展开。

⚠️ 全部可空、不回填：存量行没有预览/没下载过，语义就是「还没做」，不需要脚本补数。
⚠️ 生效路径（与 0055~0060 同一条部署约束）：部署链路不跑 `alembic upgrade head`
（alembic-migrate 容器只 stamp head），老库加列的唯一生效路径是 `app/database.py`
那张 ADD COLUMN 清单（已同步登记）；本迁移供 fresh DB、版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0061_asset_download_prompt_preview"
down_revision: Union[str, None] = "0060_asset_card_asset_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_items", sa.Column("download_status", sa.String(length=10), nullable=True))
    op.add_column("asset_summaries", sa.Column("prompt_preview", sa.Text(), nullable=True))
    op.add_column("asset_summaries", sa.Column("prompt_preview_at", sa.DateTime(), nullable=True))
    op.add_column(
        "asset_summaries",
        sa.Column("cost_preview", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("asset_summaries", "cost_preview")
    op.drop_column("asset_summaries", "prompt_preview_at")
    op.drop_column("asset_summaries", "prompt_preview")
    op.drop_column("asset_items", "download_status")
