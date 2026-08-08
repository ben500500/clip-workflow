"""add publish_materials table

Revision ID: 0007_publish_materials
Revises: 0006_shortdrama_prompt_video
Create Date: 2026-08-08

短片制作（v7）：新增 publish_materials（短剧发布素材生成记录）表，
保存每次「剧情梗概 → 发布素材」的生成历史：
短标题 / 三款视频配文 / 成套话题标签 / 三条置顶互动神评。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_publish_materials"
down_revision: Union[str, None] = "0006_shortdrama_prompt_video"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publish_materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("story", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("theme", sa.String(200), nullable=True),
        sa.Column("tone", sa.String(200), nullable=True),
        sa.Column("platform", sa.String(200), nullable=True),
        sa.Column("extra_requirements", sa.Text(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("material_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_publish_materials_created_at", "publish_materials", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_publish_materials_created_at", table_name="publish_materials")
    op.drop_table("publish_materials")
