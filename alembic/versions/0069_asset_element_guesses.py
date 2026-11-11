"""模型提炼结果缓存表 asset_element_guesses（11-11 批 Z，ISSUE #372）

用户口径原话：「你不能按照固定的词典去识别，你要调用大模型的能力去做这个事情啊。」
于是词表退成第一道免费粗筛，认不出的那一格**自动**问模型（不再等人点按钮）。但问一次
花一次钱、还要等十几秒，所以抄回来的原值必须存下来——同一份稿子的同一个参数项只花一次
模型钱，之后反复开单、刷新页面、换浏览器全部 0 元。

为什么键是 `body_hash`（投递稿正文的 sha256）而不是 `summary_id`：
- 稿子一改写哈希就变，旧行自然不再命中——不需要失效逻辑，也不会拿旧稿的词去新稿里换；
- 同一份稿子被两条生产单引用时只占一份缓存；
- 稿子回滚到旧版时那批行还能重新命中（所以不删，只在读侧按当前字典重判后丢弃坏行）。

`slot_key` 是字典行的参数项 key。存的是**原串**，判据不存：读出来时照样过一遍
`accept_guessed_values`（逐字在不在稿子里、有没有落在保护行、长度上限）。保护规则来自
**当前**生效的元素字典，字典一改，陈旧判定就该重算——过不了的那行缓存会被删掉，
下次自动重新问。

生效路径同 0055~0068：部署链路只 stamp head、不跑 upgrade，fresh DB 由 app/database.py
的 `create_all` 建表（模型已在 app/models/models.py 登记）；本迁移供版本链与人工核对。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0069_asset_element_guesses"
down_revision: Union[str, None] = "0068_hook_code_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_element_guesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("slot_key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="asset_element_guesses_pkey"),
        sa.UniqueConstraint("body_hash", "slot_key", name="uq_asset_element_guesses_hash_slot"),
    )
    op.create_index(
        "ix_asset_element_guesses_body_hash", "asset_element_guesses", ["body_hash"]
    )
    op.create_index(
        "ix_asset_element_guesses_created_at", "asset_element_guesses", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_asset_element_guesses_created_at", table_name="asset_element_guesses")
    op.drop_index("ix_asset_element_guesses_body_hash", table_name="asset_element_guesses")
    op.drop_table("asset_element_guesses")
