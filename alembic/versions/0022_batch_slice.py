"""add batch_slices and batch_slice_items

Revision ID: 0022_batch_slice
Revises: 0021_slice_task_text_overlays
Create Date: 2026-08-12

三期：批量切片工作流（上传 JSON 剧名+剧集 → 按剧名建项目 → 逐集选点/自动审核/切片/删除源视频）。
新增 batch_slices（批次）与 batch_slice_items（批次项=剧集）两张表。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0022_batch_slice"
down_revision: Union[str, None] = "0021_slice_task_text_overlays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_slices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255),
            drama_name VARCHAR(255),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            slice_config JSON,
            status VARCHAR(50) DEFAULT 'pending',
            total INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            output_count INTEGER DEFAULT 0,
            delete_source BOOLEAN DEFAULT TRUE,
            created_by UUID,
            error_message TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_slice_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES batch_slices(id) ON DELETE CASCADE,
            seq INTEGER,
            title VARCHAR(255),
            source_path VARCHAR(1000),
            source_file_key VARCHAR(500),
            episode_id UUID REFERENCES episodes(id) ON DELETE SET NULL,
            autoclip_run_id UUID,
            slice_task_id UUID,
            status VARCHAR(50) DEFAULT 'pending',
            progress DOUBLE PRECISION DEFAULT 0,
            message TEXT,
            error_message TEXT,
            output_count INTEGER DEFAULT 0,
            processed_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_slices_project_id ON batch_slices(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_slices_created_by ON batch_slices(created_by)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_slice_items_batch_id ON batch_slice_items(batch_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_slice_items_episode_id ON batch_slice_items(episode_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS batch_slice_items")
    op.execute("DROP TABLE IF EXISTS batch_slices")
