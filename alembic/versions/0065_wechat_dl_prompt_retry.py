"""反推提示词自动补投（11-09 现网排查，ISSUE #372）：wechat_dl_prompt_tasks.retry_count

现网现象：智令 doc/120 反推任务成批 failed，库里只写下「任务处理失败」。白拿
doc/119 的原始响应才发现上游真正的失败原因在 **errMsg** 字段（「视频理解服务返回
空结果」），我们的 `_truncate(data.get("msg") or data.get("error"))` 从来没读到它；
而且同一条链接换个时刻再投就成功——那是上游读流抖动，不是链接坏了。

本列是「每条链接只自动补投一次」的认领位：
- 0 = 没补投过；1 = 已经补投过一次（补投仍失败就停在 failed，不再自己烧钱）。
- 防并发双扣靠 `UPDATE ... WHERE id = :id AND retry_count = 0` 的原子认领，
  不是靠先读后写；扣费发生在我们这边，所以这个闸门必须落在 DB 层。

可空/带默认，不回填（存量失败行保持"没补投过"，行为与今天一致）。
生效路径同 0055~0064：部署链路只 stamp head、不跑 upgrade，老库加列的唯一生效
路径是 app/database.py 的 ADD COLUMN 清单，本迁移供 fresh DB、版本链与人工核对。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0065_wechat_dl_prompt_retry"
down_revision: Union[str, None] = "0064_user_functions_resubmit_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wechat_dl_prompt_tasks",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("wechat_dl_prompt_tasks", "retry_count")
