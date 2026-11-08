"""出钩子文案双产出：AssetSummary.doubao_prompt（豆包网页版完整提示词）

Revision ID: 0063_asset_summary_doubao_prompt
Revises: 0062_asset_play_url_cache
Create Date: 2026-11-06

用户 2026-11-06 口径：出钩子文案时要出两样东西——①一句话文案（现状）；
②按 NAS《豆包文案生成模板与规则.md》生成的完整豆包提示词，可直接拿去
doubao.com 网页生成。落在 AssetSummary 每条候选一行：出文案任务里候选落库后
调 autoclip /hook-copy/prompt-web（新模板 hook_prompt_web.txt，网页版裁剪——
无段头编号/推荐标题/发布标签，10s/15s 模型逐条判断），按 seq 对号存本列。

⚠️ 全部可空、不回填：NULL=生成失败/未生成（文案本身不受影响），
用 POST /assets/summaries/prompt-web 单独补。
⚠️ 生效路径与 0055~0062 同一条部署约束：部署链路不跑 `alembic upgrade head`
（alembic-migrate 容器只 stamp head），老库加列的唯一生效路径是 `app/database.py`
那张 ADD COLUMN 清单（已同步登记）；本迁移供 fresh DB、版本链与人工核对使用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0063_asset_summary_doubao_prompt"
down_revision: Union[str, None] = "0062_asset_play_url_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_summaries", sa.Column("doubao_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_summaries", "doubao_prompt")
