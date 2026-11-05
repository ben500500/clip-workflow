"""新增抽帧表 asset_frames（审核台卡片图 + 封面图的落点）

Revision ID: 0058_asset_frames
Revises: 0057_asset_categories
Create Date: 2026-11-04

11-04 批 F：一线审文案时只能读字，读不出"这条片子到底是不是那个画面"。
所以给每条素材抽 3 张单帧 + 1 张九宫格、给每个产物补 1 张帧，挂到卡片上。
这张表是**纯呈现层**——审核过不过、风险词命不命中、一致性判不判得过，全都不看它；
抽不出来（链接素材桶里没文件、ffmpeg 失败、片长超 `ASSET_FRAME_MAX_SOURCE_SECONDS`）
不报错、不拦任何步骤。

⚠️ 幂等键是**两条部分唯一索引**，不是一条 `UniqueConstraint(asset_id, kind, seq)`：
后者会把产物的帧撞死——一条素材拼过 3 版就有 3 个产物，它们全都要占
`(asset_id, 'output_thumb', 0)` 这一个键。所以素材级帧看 `(asset_id, kind, seq)`、
产物级帧看 `(output_id, kind, seq)`，各自幂等（模型里同一套定义，别改一边）。

⚠️ 生效路径（和 0055/0056/0057 同一条部署约束）：部署链路**不跑** `alembic upgrade head`
（alembic-migrate 容器只 stamp head），所以新表唯一生效路径是 `init_db()` 的
`Base.metadata.create_all` —— 依赖 `AssetFrame` 已被 `app/models/models.py` import 注册（已做）。
本迁移供 fresh DB / 版本链与人工核对使用；`asset_items.cover_image_key` 是 0055 就有的列，
本次只补**写入方**（抽帧时写第 1 张单帧），不动表结构，因此不需要 compat 条目。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0058_asset_frames"
down_revision: Union[str, None] = "0057_asset_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_frames",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "output_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_outputs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("t_offset", sa.Float(), nullable=True),
        sa.Column("file_key", sa.String(500), nullable=False),
        sa.Column("bucket", sa.String(50), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("source_file_key", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_asset_frames_asset_id", "asset_frames", ["asset_id"])
    op.create_index("ix_asset_frames_output_id", "asset_frames", ["output_id"])
    op.create_index("ix_asset_frames_kind", "asset_frames", ["kind"])

    # 两把部分唯一锁：按"挂在哪"分别幂等（见文件头那段 ⚠️）
    op.create_index(
        "uq_asset_frames_asset_kind_seq",
        "asset_frames",
        ["asset_id", "kind", "seq"],
        unique=True,
        postgresql_where=sa.text("output_id IS NULL"),
    )
    op.create_index(
        "uq_asset_frames_output_kind_seq",
        "asset_frames",
        ["output_id", "kind", "seq"],
        unique=True,
        postgresql_where=sa.text("output_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_asset_frames_output_kind_seq", table_name="asset_frames")
    op.drop_index("uq_asset_frames_asset_kind_seq", table_name="asset_frames")
    op.drop_index("ix_asset_frames_kind", table_name="asset_frames")
    op.drop_index("ix_asset_frames_output_id", table_name="asset_frames")
    op.drop_index("ix_asset_frames_asset_id", table_name="asset_frames")
    op.drop_table("asset_frames")
