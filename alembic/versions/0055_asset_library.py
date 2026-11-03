"""新增素材库（asset_library）5 张表

Revision ID: 0055_asset_library
Revises: 0054_zhiling_service_tasks
Create Date: 2026-11-03

设计方案《素材库模块-设计方案-20261103.md》P0：团队每日批量收集的外部素材
（多平台分享链接 / 直接视频文件）导入 → 反推提示词 → 钩子文案（多候选 + 审核）
→ 生产单（过审文案 × N 条差异化提示词）→ 合成 → 交付包。

表（全部挂主系统 `app.database.Base`，不是 WechatDownloadBase）：
- asset_batches      导入批次（成本预估/实扣 + 熔断标记，对账落点）
- asset_items        素材主表（一行 = 一条素材；5 个阶段态 + 1 个派生 status）
- asset_summaries    钩子文案（1:N 候选 + 审核态，驳回必填理由，改后通过留痕）
- asset_productions  生产单条目（一条过审文案 × 第 i 个产物 = 一行；board_* 列 = 与
                     企微后台 AI 视频任务板的对账主键，通道取值 wework_aivideo 为默认）
- asset_outputs      产物文件（豆包原片 / 合成成片 / 交付包 / 文案，每条一行不覆盖）

⚠️ 生效路径说明（本仓库最高危的部署约束，改动前先读）：
部署链路**不跑** `alembic upgrade head`（alembic-migrate 容器只 stamp head），
所以新表的唯一生效路径是 `init_db()` 里的 `Base.metadata.create_all` —— 前提是
模型在 `app/models/models.py` 里被 import 注册（已做）。本迁移供 fresh DB / 版本链
与人工核对使用；`scripts/db_sync_columns.py` 只补列、不建表，指望不上。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0055_asset_library"
down_revision: Union[str, None] = "0054_zhiling_service_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("source_kind", sa.String(10), nullable=False, server_default="link"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_max_duration", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("cost_actual", sa.Float(), nullable=True),
        sa.Column("budget_cap", sa.Float(), nullable=True),
        sa.Column("budget_gate", sa.String(20), nullable=True),
        sa.Column("budget_note", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_asset_batches_code", "asset_batches", ["code"])
    op.create_index("ix_asset_batches_source_kind", "asset_batches", ["source_kind"])
    op.create_index("ix_asset_batches_created_by", "asset_batches", ["created_by"])

    op.create_table(
        "asset_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.String(10), nullable=False, server_default="link"),
        sa.Column("source_url", sa.String(2000), nullable=True),
        # 归一化去重键：只用于跨批次查重命中，绝不用来拉流（宁可漏合不可误合）
        sa.Column("source_url_norm", sa.String(2000), nullable=True),
        sa.Column("platform", sa.String(40), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_key", sa.String(500), nullable=True),
        sa.Column("bucket", sa.String(50), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # wechat_dl_prompt_tasks.id：跨 Base 只存 id 不建 relationship（否则 mapper 未注册）
        sa.Column("prompt_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("cover_image_key", sa.String(500), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("resolution", sa.String(50), nullable=True),
        sa.Column("prompt_max_duration", sa.Integer(), nullable=True),
        # 5 个阶段态（每环都烧钱，不能压成一个字段——重试没有落点）
        sa.Column("stage_import", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("stage_prompt", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("stage_summary", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("stage_produce", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("stage_compose", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("has_approved_copy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_prompt", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_produce", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_parse", sa.Float(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_asset_items_code", "asset_items", ["code"])
    op.create_index("ix_asset_items_batch_id", "asset_items", ["batch_id"])
    op.create_index("ix_asset_items_source_kind", "asset_items", ["source_kind"])
    # 查重主索引：跨批次「这条链接是不是有人传过」
    op.create_index("ix_asset_items_source_url_norm", "asset_items", ["source_url_norm"])
    op.create_index("ix_asset_items_platform", "asset_items", ["platform"])
    op.create_index("ix_asset_items_project_id", "asset_items", ["project_id"])
    op.create_index("ix_asset_items_episode_id", "asset_items", ["episode_id"])
    op.create_index("ix_asset_items_prompt_task_id", "asset_items", ["prompt_task_id"])
    op.create_index("ix_asset_items_status", "asset_items", ["status"])
    op.create_index("ix_asset_items_created_by", "asset_items", ["created_by"])

    op.create_table(
        "asset_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("style_tag", sa.String(20), nullable=True),
        sa.Column("formula_tag", sa.String(60), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consistency_ok", sa.Boolean(), nullable=True),
        sa.Column("consistency_note", sa.String(300), nullable=True),
        sa.Column("risk_hit", sa.String(500), nullable=True),
        sa.Column("audit_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reject_reason", sa.String(500), nullable=True),
        # 改后通过的原文留痕（配合 AuditLog，admin 抽检）
        sa.Column("text_before_edit", sa.Text(), nullable=True),
        sa.Column("source_prompt_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("asset_id", "seq", name="uq_asset_summary_seq"),
    )
    op.create_index("ix_asset_summaries_asset_id", "asset_summaries", ["asset_id"])
    op.create_index("ix_asset_summaries_audit_status", "asset_summaries", ["audit_status"])
    op.create_index("ix_asset_summaries_reviewed_by", "asset_summaries", ["reviewed_by"])

    op.create_table(
        "asset_productions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "summary_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_summaries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        # 五位钩子编号：11-02 版权威「三处必须带编号」（段头 / 推荐标题尾部 / 产出清单）
        sa.Column("hook_code", sa.String(10), nullable=True),
        # 废弃列：11-02 版「1020 起项目标题行已取消」，保留只为不丢历史
        sa.Column("project_title", sa.String(300), nullable=True),
        # 只含可投给模型的正文；改名/并行等投放要求另存 dispatch_note
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("dispatch_note", sa.Text(), nullable=True),
        # 过审文案快照：完成时与实际用词比对，不一致标 drift（审的≠生产的不能静默）
        sa.Column("prompt_snapshot", sa.Text(), nullable=True),
        sa.Column("video_titles", sa.JSON(), nullable=True),
        sa.Column("variant_basis", sa.String(120), nullable=True),
        sa.Column("drift", sa.Boolean(), nullable=False, server_default=sa.false()),
        # 漂移成因（A3-3）：一个 bool 不足以让一线判断要不要重投
        sa.Column("drift_reason", sa.String(500), nullable=True),
        # 意图字段：后台板没有时长开关，成片恒 10.08s / 720×1280
        sa.Column("duration", sa.Integer(), nullable=True),
        # wework_aivideo（素材库默认）/ doubao_rpa（deprecated）/ seedance_api
        sa.Column("channel", sa.String(20), nullable=True),
        # 保留列、P0 起不接受前端传：接口通道由后台派号，不存在端口/固定号
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("browser_port", sa.Integer(), nullable=True),
        # ── 企微后台 AI 视频任务板对账字段 ──
        # 板上 total＝同一 prompt 出几版（1..20），与「N 份差异化」是两个量，混用会白烧 N×N
        sa.Column("board_total", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("board_tag", sa.String(60), nullable=True),
        # 建任务时由后端生成的完整时间戳：只写日期会导致「succ 但按任何日期都查不到」
        sa.Column("board_date", sa.DateTime(), nullable=True),
        # 板上 name＝推荐视频标题第 1 条（剥非法字符、≤60 码点），也是回收改名依据
        sa.Column("board_name", sa.String(200), nullable=True),
        sa.Column("board_tid", sa.String(60), nullable=True),
        sa.Column("board_rgid", sa.String(60), nullable=True),
        # 角色卡（自有桶 key）→ 板上 picDatas 来源，数组顺序＝上传顺序
        sa.Column("character_card_key", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="order_ready"),
        sa.Column("provider_task_id", sa.String(100), nullable=True),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("summary_id", "seq", name="uq_asset_production_seq"),
        sa.UniqueConstraint("idempotency_key", name="uq_asset_production_idem"),
    )
    op.create_index("ix_asset_productions_asset_id", "asset_productions", ["asset_id"])
    op.create_index("ix_asset_productions_summary_id", "asset_productions", ["summary_id"])
    op.create_index("ix_asset_productions_batch_id", "asset_productions", ["batch_id"])
    op.create_index("ix_asset_productions_status", "asset_productions", ["status"])
    op.create_index("ix_asset_productions_account_id", "asset_productions", ["account_id"])
    op.create_index("ix_asset_productions_created_by", "asset_productions", ["created_by"])
    # 板上回读三条主键：按天捞任务、按 tid 去重、按 tag 认拥有者（无主任务按天筛不到）
    op.create_index("ix_asset_productions_board_date", "asset_productions", ["board_date"])
    op.create_index("ix_asset_productions_board_tid", "asset_productions", ["board_tid"])
    op.create_index("ix_asset_productions_board_tag", "asset_productions", ["board_tag"])

    op.create_table(
        "asset_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_productions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False, server_default="doubao_raw"),
        sa.Column("file_key", sa.String(500), nullable=True),
        sa.Column("bucket", sa.String(50), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("resolution", sa.String(50), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        # 后台板回读的 outUrl（GET /data<outUrl> 下载路径）
        sa.Column("board_out_url", sa.String(500), nullable=True),
        sa.Column("hook_production_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("qc_status", sa.String(20), nullable=True),
        sa.Column("qc_result", sa.JSON(), nullable=True),
        sa.Column("qc_note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
    )
    op.create_index("ix_asset_outputs_production_id", "asset_outputs", ["production_id"])
    op.create_index("ix_asset_outputs_asset_id", "asset_outputs", ["asset_id"])
    op.create_index("ix_asset_outputs_kind", "asset_outputs", ["kind"])
    op.create_index(
        "ix_asset_outputs_hook_production_id", "asset_outputs", ["hook_production_id"]
    )


def downgrade() -> None:
    # 逆序删除；素材库是新模块，回滚不触碰既有表
    op.drop_table("asset_outputs")
    op.drop_table("asset_productions")
    op.drop_table("asset_summaries")
    op.drop_table("asset_items")
    op.drop_table("asset_batches")
