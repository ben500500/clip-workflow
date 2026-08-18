"""add location config to publish_profiles

Revision ID: 0035_publish_profile_location
Revises: 0034_multi_video_dedup_variants
Create Date: 2026-08-18

发布页输入框 × 短片制作流程结合（P2）：PublishProfile 补 `location` 配置，
按账号在视频号发布页注入「位置」控件（如"广东·深圳"）。留空则不填，向后兼容。

新列为 DEFAULT NULL，不锁表。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0035_publish_profile_location"
down_revision: Union[str, None] = "0034_multi_video_dedup_variants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "publish_profiles" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("publish_profiles")]
        if "location" not in cols:
            op.execute(
                "ALTER TABLE publish_profiles ADD COLUMN location VARCHAR(200)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "publish_profiles" in inspector.get_table_names():
        op.execute("ALTER TABLE publish_profiles DROP COLUMN IF EXISTS location")
