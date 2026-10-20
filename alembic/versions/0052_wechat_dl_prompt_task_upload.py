"""wechat_dl_prompt_tasks 增加 source_type / file_name（本地视频上传反推）

Revision ID: 0052_wechat_dl_prompt_task_upload
Revises: 0051_wechat_dl_prompt_tasks
Create Date: 2026-10-20

ISSUE #363：反推提示词支持「本地视频上传」。

- 智令 doc/125 取 S3 POST 签名 → 直传 temp 桶（6h 自动删）→ 拿 fileUrl 喂 doc/120；
- 任务表因此需要区分来源：`source_type`（url / upload）+ `file_name`（原始文件名）。

⚠️ 部署链路不跑 `alembic upgrade head`（alembic-migrate 容器只 stamp head），
存量库加列的唯一生效路径是 backend/app/database.py 的 `_apply_compat_migrations`
幂等补列清单 —— 本迁移**必须**与 models.py、compat 清单三处同步，缺一即 500。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0052_wechat_dl_prompt_task_upload"
down_revision: Union[str, None] = "0051_wechat_dl_prompt_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wechat_dl_prompt_tasks",
        sa.Column("source_type", sa.String(20), nullable=False, server_default="url"),
    )
    op.add_column(
        "wechat_dl_prompt_tasks",
        sa.Column("file_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wechat_dl_prompt_tasks", "file_name")
    op.drop_column("wechat_dl_prompt_tasks", "source_type")
