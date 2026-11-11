"""文案预取钩子编号（11-09 批 N，ISSUE #372）：asset_summaries.hook_code

用户口径：「现有已经导入的那些文案，你都去取一个编号放着吧」。

取号是外部动作（hook_id.py 写共享台账、一发即烧），过去只能在开单那一屏现取现贴：
批量导入的 85 条每条都要手动粘一遍，慢一步还得回服务器重取。本列把号**提前钉在文案上**，
开单时后端自动顶到缺号的槽位上，顶掉即清空（清空是必须的——留着就是允许同一个号
被第二次开单复用，而拍板③ 在 `asset_productions` 那侧把「已用号」当场 400 拦死了）。

可空、不回填：存量文案默认「没预取」，行为与今天一致，号由 `POST /assets/summaries/hook-codes`
逐条钉上来。

生效路径同 0055~0065：部署链路只 stamp head、不跑 upgrade，老库加列的唯一生效路径是
app/database.py 的 ADD COLUMN 清单，本迁移供 fresh DB、版本链与人工核对。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0066_summary_hook_code"
down_revision: Union[str, None] = "0065_wechat_dl_prompt_retry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_summaries",
        sa.Column("hook_code", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("asset_summaries", "hook_code")
