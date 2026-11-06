"""素材表加媒体类型 asset_items.media_kind（图片真收进素材库，但只做生产输入）

Revision ID: 0059_asset_media_kind
Revises: 0058_asset_frames
Create Date: 2026-11-05

11-04 拍板③ / 11-05 批 G：角色卡（图片）以前只活在"生产单手填一个 MinIO key"这条
野路子上——填错一个字符就静默出无卡任务。这批把图片当**素材**收进库里，
但它**不参与**反推、出文案、生产、拼接四环，也不抽帧（它自己就是一张图）。
所以给 `asset_items` 加一列 `media_kind`（video | image），四环闸门按这一列拒图，
派生态按这一列走 `image_ready` 那一支（否则每张卡都会显示"待反推"）。

⚠️ 默认值口径：`NOT NULL DEFAULT 'video'` 对存量行是安全的——库里现存的全是视频，
补列时由数据库自己填默认值，**不需要回填脚本**，也不会出现"半新半旧"的空窗。

⚠️ 生效路径（和 0055/0056/0057/0058 同一条部署约束）：部署链路**不跑**
`alembic upgrade head`（alembic-migrate 容器只 stamp head），老库加列的唯一生效路径是
`app/database.py` 那张 ADD COLUMN 清单（已同步登记本列）；本迁移供 fresh DB /
版本链与人工核对使用。

⚠️ **故意不建索引**：只有两个取值、现网 99% 是 video，Postgres 会直接 seq scan；
而且 `create_all` 不给已存在的表补索引，留着只会得到一个"以为有索引"的假象。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0059_asset_media_kind"
down_revision: Union[str, None] = "0058_asset_frames"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_items",
        sa.Column("media_kind", sa.String(10), nullable=False, server_default="video"),
    )


def downgrade() -> None:
    op.drop_column("asset_items", "media_kind")
