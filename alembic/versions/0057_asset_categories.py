"""新增钩子原型字典 asset_categories，并给素材/文案两张表挂 category_id

Revision ID: 0057_asset_categories
Revises: 0056_asset_jobs
Create Date: 2026-11-04

11-04 拍板①：运营要的那根分类轴是《钩子模版换皮参数设定.docx》里的**结构层**
（原型 A–G，整条片子四镜怎么排），既不是 `asset_summaries.formula_tag`（文字层、
自由文本、没字典就筛不动）也不是 `style_tag`（句式层）。三轴并存、不合并、不重叠，
也**不碰 `dramas.tags`**（现网 655 行该列全为 JSON null，从没填过的空位）。

表与列：
- asset_categories      单层字典（`parent_id` 按拍板"留着不填"，恒 NULL）；
                        行只做 `active=false` 软下线、**不硬删**——真删了会把一线
                        已经点好的分类顺着 FK(SET NULL) 静默清空
- asset_items.category_id      素材属于哪个原型（导入时可整批默认，之后可改）
- asset_summaries.category_id  出文案时**继承**所属素材，审核台可单独改；素材日后
                        重新归类**不回写**已出候选（已定性的文案不该被带走）

⚠️ 生效路径（和 0055/0056 同一条部署约束，别再看错一次）：
部署链路**不跑** `alembic upgrade head`（alembic-migrate 容器只 stamp head），
所以新表唯一生效路径是 `init_db()` 的 `Base.metadata.create_all` —— 依赖
`AssetCategory` 已被 `app/models/models.py` import 注册（已做）；老库两张表的新列
靠 `app/database.py` 的 compat 清单 `ADD COLUMN IF NOT EXISTS`（也已登记）。
本迁移供 fresh DB / 版本链与人工核对使用，顺带把 7 个原型名种进空库——
现网首上线时那 7 行由 `init_db()` 的 `_seed_asset_categories()` 补，两处幂等键都是 name。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0057_asset_categories"
down_revision: Union[str, None] = "0056_asset_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 与 app/models/asset.py 的 DEFAULT_ASSET_CATEGORIES 同源（docx 原名照抄，别润色）。
# 改那边要改这边：两边都只按 name 判重，写歪了就是"多出一行"而不是"改名"。
DEFAULT_CATEGORIES = [
    (10, "原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）",
     "钩法内核：温情/无意善举 → 非人角色开口 → 给反直觉预言或指令 → 逼看后续。"),
    (20, "原型 B：偷听泄密（获取关键情报）",
     "钩法内核：主角躲在某处摸鱼/藏身 → 意外听到大人物泄密（内部消息/阴谋）→ 得知将改变命运的信息 → 逼看后续。"),
    (30, "原型 C：隐藏财富 / 秘境发现（反转爆发）",
     "钩法内核：日常场景 → 触发机关/暗格 → 财富或秘境曝光 → 归属悬念。"),
    (40, "原型 D：虐待 / 冲突 / 不公反转（情绪引爆）",
     "钩法内核：弱势者（老人/孕妇/妻）被当众打/推/弃 → 极致不公 → 留一句引爆情绪的台词 → 逼看后续（反转打脸）。"
     "合规（docx 原文要求）：必须加 本故事纯属虚构 + 请勿模仿，肢体冲突尽量侧拍/借位。"),
    (50, "原型 E：超能力 / 异常 / 猎奇（设定反差）",
     "钩法内核：普通表象 → 异常初现 → 设定被点破 → 反差悬念。"),
    (60, "原型 F：神力 / 温情 / 绝境反转（其他）",
     "钩法内核：绝境 → 神力介入 → 结果反转 → 爽点悬念。"),
    (70, "原型 G：前置故事叙事（口播）",
     "钩法内核：生成一小段前置剧情 + 衔接原剧高光剧情 → 情绪或爽点爆发。"),
]


def upgrade() -> None:
    op.create_table(
        "asset_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        # 单层字典：列先建、恒 NULL（11-04 拍板①第 1 条），日后分层不用再动表结构
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_asset_categories_name", "asset_categories", ["name"])
    op.create_index("ix_asset_categories_parent_id", "asset_categories", ["parent_id"])
    op.create_index("ix_asset_categories_created_by", "asset_categories", ["created_by"])

    # 7 个原型名照 docx 原文种入；现网已有行时这里按 name 跳过（幂等）
    for sort, name, note in DEFAULT_CATEGORIES:
        op.execute(sa.text(
            "INSERT INTO asset_categories (id, name, sort, active, note, created_at, updated_at) "
            "SELECT gen_random_uuid(), :name, :sort, true, :note, now(), now() "
            "WHERE NOT EXISTS (SELECT 1 FROM asset_categories WHERE name = :name)"
        ).bindparams(name=name, sort=sort, note=note))

    # 老库补列（现网实际走 app/database.py 的 compat 清单，这里为版本链一致）。
    # 只加列 + FK，不加唯一约束：一个原型下多条素材/文案是常态。
    op.add_column(
        "asset_items",
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_asset_items_category_id", "asset_items", ["category_id"])
    op.add_column(
        "asset_summaries",
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_asset_summaries_category_id", "asset_summaries", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_asset_summaries_category_id", table_name="asset_summaries")
    op.drop_column("asset_summaries", "category_id")
    op.drop_index("ix_asset_items_category_id", table_name="asset_items")
    op.drop_column("asset_items", "category_id")
    op.drop_index("ix_asset_categories_created_by", table_name="asset_categories")
    op.drop_index("ix_asset_categories_parent_id", table_name="asset_categories")
    op.drop_index("ix_asset_categories_name", table_name="asset_categories")
    op.drop_table("asset_categories")
