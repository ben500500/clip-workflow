"""add multi-operator audit tables (publish/login/cookie/risk)

Revision ID: 0028_multi_operator_audit
Revises: 0027_multi_operator_ownership
Create Date: 2026-08-14

视频号「多运营者」发布 P1（方案 v3.1，主题 8 / 5.4，问题10 审计+可观测）：
- publish_audits    发布审计：谁(actor_id)/对哪个号(operator_id/account_id)/发了什么
  (content_hash/cover_variant/copy_template)/从哪发(source_ip/egress_ip/ua_seed/port)/
  结果(action/result/risk_flag)，request_id 串联全链路。
- login_audits      登录态扫码审计：QR 领取人/扫码人/TTL/结果。
- cookie_access_logs Cookie 访问审计：读时间/者/用途，防越权读取。
- risk_events       风控事件：受限类型/处置，驱动毕业阈值统计。

全部为新增表，向后兼容；仅 superadmin/admin 可查（鉴权在 API 层）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0028_multi_operator_audit"
down_revision: Union[str, None] = "0027_multi_operator_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # ── publish_audits 发布审计 ──
    if "publish_audits" not in tables:
        op.create_table(
            "publish_audits",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("content_hash", sa.String(200), nullable=True),
            sa.Column("cover_variant", sa.String(200), nullable=True),
            sa.Column("copy_template", sa.String(500), nullable=True),
            sa.Column("source_ip", sa.String(45), nullable=True),
            sa.Column("egress_ip", sa.String(100), nullable=True),
            sa.Column("ua_seed", sa.String(200), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("result", sa.String(50), nullable=True),
            sa.Column("risk_flag", sa.Boolean(), nullable=True),
            sa.Column("risk_note", sa.String(500), nullable=True),
            sa.Column("request_id", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_publish_audits_task_id", "publish_audits", ["task_id"])
        op.create_index("ix_publish_audits_account_id", "publish_audits", ["account_id"])
        op.create_index("ix_publish_audits_operator_id", "publish_audits", ["operator_id"])
        op.create_index("ix_publish_audits_actor_id", "publish_audits", ["actor_id"])
        op.create_index("ix_publish_audits_action", "publish_audits", ["action"])
        op.create_index("ix_publish_audits_request_id", "publish_audits", ["request_id"])
        op.create_index("ix_publish_audits_created_at", "publish_audits", ["created_at"])

    # ── login_audits 登录态扫码审计 ──
    if "login_audits" not in tables:
        op.create_table(
            "login_audits",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("qr_key", sa.String(300), nullable=True),
            sa.Column("claim_token", sa.String(200), nullable=True),
            sa.Column("ttl_seconds", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("scanner_name", sa.String(100), nullable=True),
            sa.Column("source_ip", sa.String(45), nullable=True),
            sa.Column("result", sa.String(50), nullable=True),
            sa.Column("request_id", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_login_audits_account_id", "login_audits", ["account_id"])
        op.create_index("ix_login_audits_operator_id", "login_audits", ["operator_id"])
        op.create_index("ix_login_audits_actor_id", "login_audits", ["actor_id"])
        op.create_index("ix_login_audits_action", "login_audits", ["action"])
        op.create_index("ix_login_audits_request_id", "login_audits", ["request_id"])
        op.create_index("ix_login_audits_created_at", "login_audits", ["created_at"])

    # ── cookie_access_logs Cookie 访问审计 ──
    if "cookie_access_logs" not in tables:
        op.create_table(
            "cookie_access_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("purpose", sa.String(100), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("request_id", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_cookie_access_logs_profile_id", "cookie_access_logs", ["profile_id"])
        op.create_index("ix_cookie_access_logs_account_id", "cookie_access_logs", ["account_id"])
        op.create_index("ix_cookie_access_logs_actor_id", "cookie_access_logs", ["actor_id"])
        op.create_index("ix_cookie_access_logs_operator_id", "cookie_access_logs", ["operator_id"])
        op.create_index("ix_cookie_access_logs_request_id", "cookie_access_logs", ["request_id"])
        op.create_index("ix_cookie_access_logs_created_at", "cookie_access_logs", ["created_at"])

    # ── risk_events 风控事件 ──
    if "risk_events" not in tables:
        op.create_table(
            "risk_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("risk_type", sa.String(100), nullable=False),
            sa.Column("level", sa.String(20), nullable=True),
            sa.Column("message", sa.String(1000), nullable=True),
            sa.Column("disposition", sa.String(200), nullable=True),
            sa.Column("source_ip", sa.String(45), nullable=True),
            sa.Column("request_id", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_risk_events_account_id", "risk_events", ["account_id"])
        op.create_index("ix_risk_events_operator_id", "risk_events", ["operator_id"])
        op.create_index("ix_risk_events_actor_id", "risk_events", ["actor_id"])
        op.create_index("ix_risk_events_risk_type", "risk_events", ["risk_type"])
        op.create_index("ix_risk_events_request_id", "risk_events", ["request_id"])
        op.create_index("ix_risk_events_created_at", "risk_events", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    for table in ("publish_audits", "login_audits", "cookie_access_logs", "risk_events"):
        if table in tables:
            op.drop_table(table)
