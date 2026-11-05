"""生产单加多卡列 asset_productions.card_asset_ids（角色卡数组，顺序＝板上 picDatas）

Revision ID: 0060_asset_card_asset_ids
Revises: 0059_asset_media_kind
Create Date: 2026-11-05

11-04 拍板③ / 11-05 批 G：角色卡以前只有一列 `character_card_key`（单个 MinIO key，
值由前端**手填**）——填错一个字符，任务照样建、picDatas 却是空的，画中人全靠模型自由发挥，
事后从台账上看不出来。这批把"手填 key"换成"从素材库挑图"，而一部剧常常不止一张定妆照
（男女主各一张），板侧 `picDatas` 又是**按数组顺序**理解主次的，所以需要一列保序的数组。

⚠️ **不回填、可空**：存量单的卡只活在 `character_card_key` 里（那边存的是 key，
不是素材 id，无法反查成 id——素材可能早已不在库里）。读侧统一走 `_card_refs()`：
有数组用数组，没数组回退单值列。少这一句就会出现"改了前端之后，昨天的单导出没卡"，
那是一张已经烧过额度的单。

⚠️ 生效路径（和 0055～0059 同一条部署约束）：部署链路**不跑** `alembic upgrade head`
（alembic-migrate 容器只 stamp head），老库加列的唯一生效路径是
`app/database.py` 那张 ADD COLUMN 清单（已同步登记本列）；本迁移供 fresh DB、
版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0060_asset_card_asset_ids"
down_revision: Union[str, None] = "0059_asset_media_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_productions", sa.Column("card_asset_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_productions", "card_asset_ids")
