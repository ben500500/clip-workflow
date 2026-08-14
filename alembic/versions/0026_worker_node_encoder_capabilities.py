"""add worker_nodes.encoder_capabilities

Revision ID: 0026_worker_node_encoder_capabilities
Revises: 0025_slice_task_subtitle_align_mask
Create Date: 2026-08-14

Worker 节点新增硬件编码能力（encoder_capabilities）字段，用于预留「GPU 节点
自动分派任务」接口：Go slice-worker 启动时检测本机 ffmpeg 硬件编码器能力
（h264_nvenc/hevc_nvenc/h264_videotoolbox 等）并通过心跳上报，后端持久化到
worker_nodes 表。当前单机自动模式仅作能力上报/界面展示，不影响任务下发。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0026_worker_node_encoder_capabilities"
down_revision: Union[str, None] = "0025_slice_task_subtitle_align_mask"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE worker_nodes ADD COLUMN IF NOT EXISTS encoder_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE worker_nodes DROP COLUMN IF EXISTS encoder_capabilities")
