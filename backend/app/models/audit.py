"""审计域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：AuditLog / PublishAudit / LoginAudit / CookieAccessLog。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class AuditLog(Base):
    """审计日志（V3）：操作人、操作时间、操作类型、目标对象、变更前后值。

    用于安全合规与运维追溯，仅 superadmin/admin 可查看。
    """
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_name = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False, index=True)   # 操作类型，如 project.create / user.role.update
    target_type = Column(String(100), nullable=True)
    target_id = Column(String(100), nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, operator={self.operator_name})>"


class PublishAudit(Base):
    """多运营者发布审计（方案 5.4，P1 问题10）。

    记录每次发布的完整上下文：谁(actor_id)、对哪个号(operator_id/account_id)、
    发了什么(content_hash/cover_variant/copy_template)、从哪发(source_ip/egress_ip/
    ua_seed/port)、结果(action/result/risk_flag)，并以 request_id(trace_id) 串联
    审核→确认→发布→风控回执 全链路。仅 superadmin/admin 可查看。
    """
    __tablename__ = "publish_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)   # 号主
    actor_id = Column(UUID(as_uuid=True), nullable=True, index=True)     # 操作人（含 publisher 代发）
    profile_id = Column(UUID(as_uuid=True), nullable=True)
    content_hash = Column(String(200), nullable=True)
    cover_variant = Column(String(200), nullable=True)
    copy_template = Column(String(500), nullable=True)
    source_ip = Column(String(45), nullable=True)
    egress_ip = Column(String(100), nullable=True)
    ua_seed = Column(String(200), nullable=True)
    port = Column(Integer, nullable=True)
    # 动作：publish(发布触发) / confirm(确认发布) / fail(失败) / reauth(重新登录)
    action = Column(String(50), nullable=False, index=True)
    result = Column(String(50), nullable=True)         # success / pending_confirm / failed
    risk_flag = Column(Boolean, default=False)
    risk_note = Column(String(500), nullable=True)
    request_id = Column(String(100), nullable=True, index=True)  # 全链路 trace_id
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<PublishAudit(id={self.id}, action={self.action}, account={self.account_id})>"


class LoginAudit(Base):
    """登录态自服务扫码审计（方案 5.4 / 主题 8）。

    记录 QR 领取人、扫码人、TTL、结果，用于运营者登录态治理与安全追溯。
    """
    __tablename__ = "login_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    actor_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # 领取/发起人
    qr_key = Column(String(300), nullable=True)                       # 加密存 MinIO 的 QR PNG key
    claim_token = Column(String(200), nullable=True)                  # 单次领取 token
    ttl_seconds = Column(Integer, default=90)
    action = Column(String(50), nullable=False, index=True)   # claim(领取) / scanned(扫码) / expired / refreshed
    scanner_name = Column(String(100), nullable=True)          # 扫码人昵称
    source_ip = Column(String(45), nullable=True)
    result = Column(String(50), nullable=True)                 # success / expired / failed
    request_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<LoginAudit(id={self.id}, action={self.action}, account={self.account_id})>"


class CookieAccessLog(Base):
    """Cookie 访问审计（方案 5.4 / 主题 8）。

    记录每次对加密 Cookie 的解密/读取时间、操作者、用途，防止 cookie 被越权读取。
    """
    __tablename__ = "cookie_access_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    actor_id = Column(UUID(as_uuid=True), nullable=True, index=True)   # 读取者（worker 记系统/operator）
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # 号主
    purpose = Column(String(100), nullable=True)    # publish / login_check / manual
    ip_address = Column(String(45), nullable=True)
    request_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<CookieAccessLog(id={self.id}, profile={self.profile_id})>"
