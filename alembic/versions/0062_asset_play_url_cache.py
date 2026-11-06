"""时效直链缓存（11-06）：resolve 取到的 play_url 落库，有效期内免费回放

Revision ID: 0062_asset_play_url_cache
Revises: 0061_asset_download_prompt_preview
Create Date: 2026-11-06

用户报的洞：链接素材点「取直链并播放」（0.01 元）拿到直链后，关掉抽屉再进来
直链就没了——resolve 只把**时长**写库，play_url 本身只活在当次响应里；而前端
每次开抽屉把播放器清空。更堵的是 resolve 对「已有时长」的素材直接 skip（防重复
扣费），所以再点按钮也只会回「没有一条需要回源」：链接既拿不回来、也不会再扣钱。

修法：`asset_items` 加 `play_url` / `play_url_at` 两列。resolve 成功后落库；
有效期内（`ASSET_PLAY_URL_TTL_HOURS`，默认 6，与「原站时效直链约 6 小时有效」
同口径）`source-preview` 直接回缓存直链（开抽屉免费自动回放）、resolve 免费返回；
过期不作数，resolve 带上 retake 重新解析（该扣 0.01 扣 0.01）——这是直链失效
后的唯一自愈出口。

⚠️ 全部可空、不回填：存量行没解析过或没存过，语义就是「没有缓存」，走老路径。
⚠️ 生效路径（与 0055~0061 同一条部署约束）：部署链路不跑 `alembic upgrade head`
（alembic-migrate 容器只 stamp head），老库加列的唯一生效路径是 `app/database.py`
那张 ADD COLUMN 清单（已同步登记）；本迁移供 fresh DB、版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0062_asset_play_url_cache"
down_revision: Union[str, None] = "0061_asset_download_prompt_preview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_items", sa.Column("play_url", sa.Text(), nullable=True))
    op.add_column("asset_items", sa.Column("play_url_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_items", "play_url_at")
    op.drop_column("asset_items", "play_url")
