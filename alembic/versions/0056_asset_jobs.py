"""新增素材库后台任务台账 asset_jobs（D-1 队列化）

Revision ID: 0056_asset_jobs
Revises: 0055_asset_library
Create Date: 2026-11-04

11-04 第二轮四席位审核 D-1：出文案与投产是**同步等模型**的（单条 ~95s，一批 10 条
串跑 15 分钟），一线只能靠浏览器干等——刷新、切标签、网关抖动，一次长等待就白扔，
而模型钱与钩子编号那次已经花掉了。现在提交当场落一行 job 并回 job_id，
前端轮询台账；进程重启把 queued/running 一律标 interrupted（协程没了＝结果不可信）。

表（挂主系统 `app.database.Base`）：
- asset_jobs  一次后台批量出文案 / 批量投产 = 一行；params=原请求体，result=整份接口响应

⚠️ 生效路径（与 0055 同一条部署约束，别再看错一次）：
部署链路**不跑** `alembic upgrade head`（alembic-migrate 容器只 stamp head），
新表唯一生效路径是 `init_db()` 的 `Base.metadata.create_all` —— 依赖
`app/models/asset.py` 里的 `AssetJob` 已被 `app/models/models.py` import 注册（已做）。
本迁移供 fresh DB / 版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0056_asset_jobs"
down_revision: Union[str, None] = "0055_asset_library"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("planned_units", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["asset_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_asset_jobs_kind", "asset_jobs", ["kind"])
    op.create_index("ix_asset_jobs_status", "asset_jobs", ["status"])
    op.create_index("ix_asset_jobs_batch_id", "asset_jobs", ["batch_id"])
    op.create_index("ix_asset_jobs_created_by", "asset_jobs", ["created_by"])
    op.create_index("ix_asset_jobs_created_at", "asset_jobs", ["created_at"])
    # 轮询与「同范围是否已有在跑的活」都按 (kind, status) 打，这条是热点索引
    op.create_index("ix_asset_jobs_kind_status", "asset_jobs", ["kind", "status"])


def downgrade() -> None:
    op.drop_index("ix_asset_jobs_kind_status", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_created_at", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_created_by", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_batch_id", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_status", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_kind", table_name="asset_jobs")
    op.drop_table("asset_jobs")
