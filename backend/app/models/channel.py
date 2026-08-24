"""视频号台账域 ORM 模型（ChannelAccount / ChannelOperator）。

从需求「视频号列表」新增，用于登记视频号工商/合作信息台账：
- 视频号名称、微信号、实名类型（个人/企业）、实名人、注册日期
- 合作模式（IAA/IAP，JSON 数组支持多选共存）、合作公司
- 运营者身份（可添加多人：现有用户 FK + 外部手填姓名/电话双轨）

与发布域的 `VideoAccount` 解耦：
- `VideoAccount` 是「发布通道配置」语义（Chrome 端口/Cookie、小程序挂载资质），职责不变；
- `ChannelAccount` 是「登记台账」语义，仅通过 `video_account_id` 软关联到发布账号库。

数据隔离：`created_by` 记录操作人，列表查询沿用 `user_can_access_all_materials` RBAC。
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    JSON,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ChannelAccount(Base):
    """视频号台账（登记工商/合作信息，与发布通道解耦）。"""
    __tablename__ = "channel_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_name = Column(String(100), nullable=False, index=True)   # 视频号名称
    wechat_id = Column(String(200), nullable=True, index=True)       # 微信号
    verify_type = Column(String(20), nullable=True)                  # personal/enterprise
    verify_name = Column(String(100), nullable=True)                 # 实名人
    register_date = Column(Date, nullable=True)                      # 注册日期
    cooperation_modes = Column(JSON, nullable=True)                  # ["IAA","IAP"] 支持多选
    coop_company = Column(String(200), nullable=True)                # 合作公司
    # 软关联发布账号库（先登记后关联，可空）；不设物理 FK 约束，与 PublishTask 快照路线一致
    video_account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 所属剧场（直接挂剧场；可空，用于视频号列表按剧场筛选）
    theater_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    remark = Column(String(500), nullable=True)
    enabled = Column(Boolean, default=True)
    # 数据隔离（同 video_accounts）：操作人审计 + 列表 RBAC 过滤
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    operators = relationship(
        "ChannelOperator",
        back_populates="channel",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ChannelAccount(id={self.id}, name={self.channel_name})>"


class ChannelOperator(Base):
    """视频号运营者（多人运营：现有用户 FK + 外部手填双轨）。"""
    __tablename__ = "channel_operators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("channel_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 从系统选：软关联 users.id（可空）
    operator_user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 外部手填：姓名/电话（可空，双轨二选一）
    operator_name = Column(String(100), nullable=True)
    operator_phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    channel = relationship("ChannelAccount", back_populates="operators")

    # 数据库层兜底校验：系统用户 与 手填姓名 至少填一个
    __table_args__ = (
        CheckConstraint(
            "operator_user_id IS NOT NULL OR operator_name IS NOT NULL",
            name="ck_channel_operator_identity",
        ),
    )

    def __repr__(self) -> str:
        return f"<ChannelOperator(id={self.id}, account={self.channel_account_id})>"
