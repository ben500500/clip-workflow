"""渠道台账 ORM 模型（视频号台账）。

视频号台账是「渠道侧（商务/运营）台账」，与「发布通道账号库」解耦：
- 台账侧重商务合作登记（视频号名称/微信号/认证类型/合作模式/合作公司…）；
- 发布通道账号库（VideoAccount，见 publish.py）侧重发布通道配置（profile_id /
  Cookie / 小程序资质）。

两者通过 `video_account_id` **软外键**关联（冗余快照 + 软外键路线，
与 `PublishTask.video_account_id` 一致）：先登记台账、后续再补绑发布通道账号，
避免物理 FK 阻塞将来关联账号库的回填/迁移。SQLAlchemy 层仅作外键语义声明，
不创建物理约束。

运营者采用「双轨」结构：有系统账号的外部人员填 `operator_user_id`（软外键→users，
可空），无系统账号的外部合作方填 `operator_name` + `operator_phone`。二者至少填一个
（服务层校验 + 数据库 CHECK 兜底），见 `ck_channel_operator_identity`。
"""
import uuid
from datetime import datetime, date

from sqlalchemy import (
    Column,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Date,
    JSON,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ChannelAccount(Base):
    """视频号台账（渠道侧商务登记）。

    video_account_id 为软外键，可空（先登记后关联）。created_by 用于数据隔离
    （RBAC 过滤），与发布账号库 VideoAccount 的 created_by 语义一致。
    """
    __tablename__ = "channel_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 视频号名称
    channel_name = Column(String(100), nullable=False, index=True)
    # 微信号
    wechat_id = Column(String(200), nullable=True, index=True)
    # 认证类型：personal / enterprise
    verify_type = Column(String(20), nullable=True)
    # 实名人
    verify_name = Column(String(100), nullable=True)
    # 注册日期
    register_date = Column(Date, nullable=True)
    # 合作模式（JSON 数组多选）：["IAA"] / ["IAP"] / ["IAA","IAP"]
    cooperation_modes = Column(JSON, nullable=True)
    # 合作公司
    coop_company = Column(String(200), nullable=True)
    # 软外键→发布通道账号库（video_accounts.id），可空，先登记后关联
    video_account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    remark = Column(String(500), nullable=True)
    enabled = Column(Boolean, default=True)
    # 数据隔离：操作人（仅审计用，访问过滤走 RBAC）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    operators = relationship(
        "ChannelOperator",
        back_populates="channel",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ChannelAccount(id={self.id}, channel_name={self.channel_name})>"


class ChannelOperator(Base):
    """台账运营者（多人运营：一条台账可挂多个运营者）。

    双轨结构：operator_user_id（软外键→users，可空）或 operator_name（外部手填）
    至少填一个，operator_phone 为外部人员联系兜底（本期加）。
    """
    __tablename__ = "channel_operators"
    __table_args__ = (
        CheckConstraint(
            "operator_user_id IS NOT NULL OR operator_name IS NOT NULL",
            name="ck_channel_operator_identity",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("channel_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 软外键→users，可空；有系统账号的运营者
    operator_user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 外部手填姓名（无系统账号时兜底）
    operator_name = Column(String(100), nullable=True)
    # 外部手填电话（本期加，联系兜底）
    operator_phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    channel = relationship("ChannelAccount", back_populates="operators")

    def __repr__(self) -> str:
        return f"<ChannelOperator(id={self.id}, name={self.operator_name})>"
