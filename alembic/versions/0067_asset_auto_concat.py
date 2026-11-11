"""成片回收后自动拼接（11-10 批 Q，ISSUE #372）：生产单上的拼装要求 + 幂等键

用户口径（需求⑤原话）：「钩子成片生成出来以后，需要导入拼接视频自动拼接成可投放素材。」
落到 11-10 定的 fork 是「回收后自动拼：钩子片 + 我指定的拼接素材」——第二段由人投板时点名，
机器不挑素材、不做智能选点（沿用 11-04 已经改定过的简单拼接口径）。

四列的分工：
- `asset_productions.concat_asset_id` / `concat_order`：这次投板**要求拼**什么、按什么顺序拼。
  钉在生产单行上而不是只活在请求里，是为了接续回收也能拼——进程重启后带
  `recover_only=true` 再回收一次，拼装要求还在，不用人再点一遍。
- `asset_productions.concat_last_result`：最近一次拼的结果，只给界面看「拼没拼 / 为什么没拼」。
  判据不在这列上，所以它可空、不回填、写坏了也不影响业务。
- `asset_outputs.composed_from_output_id`：自动拼接的**幂等键**（这支豆包成片已经拼过了）。
  手工口 `POST /assets/concat` 恒为 NULL——那是人现场点的，同一支反复拼不同顺序是正常用法。

可空、不回填：没勾过拼接素材的存量单全是 NULL，行为与今天完全一致（回收完就停，不拼）。

索引说明：模型上 `index=True`，fresh DB 由 create_all 带上；老库走下面的 ADD COLUMN 清单，
只补列不补索引（`has_column` 判据之外没有加索引的通道，而且这两列的查询都是小表点查）。
不建 UNIQUE 也是同一类考虑：老库补不出约束，建了会出现「新库拦、老库不拦」两套行为。

生效路径同 0055~0066：部署链路只 stamp head、不跑 upgrade，老库加列的唯一生效路径是
app/database.py 的 ADD COLUMN 清单，本迁移供 fresh DB、版本链与人工核对。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0067_asset_auto_concat"
down_revision: Union[str, None] = "0066_summary_hook_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_productions",
        sa.Column("concat_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "asset_productions",
        sa.Column("concat_order", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "asset_productions",
        sa.Column("concat_last_result", sa.JSON(), nullable=True),
    )
    op.add_column(
        "asset_outputs",
        sa.Column("composed_from_output_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("asset_outputs", "composed_from_output_id")
    op.drop_column("asset_productions", "concat_last_result")
    op.drop_column("asset_productions", "concat_order")
    op.drop_column("asset_productions", "concat_asset_id")
