"""监控/告警/风控域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：WorkerNode / AlertRule / AlertEvent / RiskEvent。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Text,
    Float,
    ForeignKey,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class WorkerNode(Base):
    """Worker 节点注册信息."""
    __tablename__ = "worker_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(String(100), unique=True, nullable=False, index=True)
    hostname = Column(String(255), nullable=True)
    ip = Column(String(50), nullable=True)
    os = Column(String(50), nullable=True)
    arch = Column(String(50), nullable=True)
    ffmpeg_version = Column(String(100), nullable=True)
    tags = Column(JSON, default=list)
    max_concurrent = Column(Integer, default=2)
    # 节点是否启用：管理员可在界面选择是否开启节点（停用后 Worker 不再领取新任务）
    enabled = Column(Boolean, default=True)
    # 节点 CPU 资源分配比例（%，默认 50）：切片时限制 ffmpeg 线程数
    cpu_percent = Column(Integer, default=50)
    status = Column(String(50), default="online")
    current_tasks = Column(Integer, default=0)
    total_tasks_completed = Column(Integer, default=0)
    total_tasks_failed = Column(Integer, default=0)
    # 节点硬件编码能力（JSON 数组，如 ["h264_nvenc","hevc_nvenc"]）
    # 预留 GPU 节点自动分派接口：供未来后端按节点能力分派硬件编码任务；当前仅作上报/展示
    encoder_capabilities = Column(JSON, default=list)
    last_heartbeat = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<WorkerNode(id={self.node_id}, status={self.status})>"


class AlertRule(Base):
    """告警规则（三期监控告警系统）。

    定义指标、比较符、阈值、级别与启用状态。
    """
    __tablename__ = "alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    # 监控指标：worker_offline / task_failed / disk_usage / redis_memory / queue_backlog / cookie_expiring / ecpm_low
    metric = Column(String(100), nullable=False, index=True)
    operator = Column(String(10), default=">", nullable=False)   # > / < / >= / <= / ==
    threshold = Column(Float, nullable=False, default=0)
    level = Column(String(20), default="warning", nullable=False)  # warning / critical
    enabled = Column(Boolean, default=True)
    description = Column(String(500), nullable=True)
    # 覆盖系统默认钉钉 Webhook；为空则使用系统全局 DINGTALK_WEBHOOK
    webhook_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<AlertRule(id={self.id}, metric={self.metric}, threshold={self.threshold})>"


class AlertEvent(Base):
    """告警事件（三期监控告警系统）。

    记录每次告警触发的时间、级别、内容与通知状态。
    """
    __tablename__ = "alert_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True, index=True)
    rule_name = Column(String(200), nullable=True)
    metric = Column(String(100), nullable=True)
    level = Column(String(20), default="warning")
    message = Column(Text, nullable=True)
    current_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    notified = Column(Boolean, default=False)
    notify_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AlertEvent(id={self.id}, rule={self.rule_name}, level={self.level})>"


class RiskEvent(Base):
    """风控事件（方案 5.4 / 主题 8，驱动毕业统计）。

    记录每次风控受限的类型、处置与关联账号，供「毕业阈值（7 日 ≥2 次风控）」
    等统计与告警使用。
    """
    __tablename__ = "risk_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    actor_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    risk_type = Column(String(100), nullable=False, index=True)   # login_restricted / publish_limited / captcha / ban / upload_limited / env_risk
    level = Column(String(20), default="warning")                 # warning / critical
    message = Column(String(1000), nullable=True)
    disposition = Column(String(200), nullable=True)   # 处置：tier_up / re_login / manual_review
    source_ip = Column(String(45), nullable=True)
    request_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<RiskEvent(id={self.id}, type={self.risk_type}, account={self.account_id})>"
