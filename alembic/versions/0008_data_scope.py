"""add data isolation columns (data_scope / created_by)

Revision ID: 0008_data_scope
Revises: 0007_publish_materials
Create Date: 2026-08-08

二期方案·数据隔离：
- users.data_scope：用户数据可见范围（all=全部素材，own=仅自己创建）
  默认按角色：admin/material/publisher=all，operator=own
- projects.created_by：项目创建人（运营专员默认仅可见自己创建的素材）

同时补充去重配置恢复默认相关的结构（无需新列，仅数据）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008_data_scope"
down_revision: Union[str, None] = "0007_publish_materials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 用户数据可见范围
    op.add_column(
        "users",
        sa.Column("data_scope", sa.String(20), nullable=False, server_default="own"),
    )
    # 项目创建人（数据隔离归属）
    op.add_column(
        "projects",
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_projects_created_by", "projects", ["created_by"])

    # 存量数据回填：按角色默认值
    op.execute(
        "UPDATE users SET data_scope = 'all' WHERE role IN ('admin', 'material', 'publisher')"
    )
    op.execute(
        "UPDATE users SET data_scope = 'own' WHERE data_scope IS NULL OR data_scope = ''"
    )


def downgrade() -> None:
    op.drop_index("ix_projects_created_by", table_name="projects")
    op.drop_column("projects", "created_by")
    op.drop_column("users", "data_scope")
