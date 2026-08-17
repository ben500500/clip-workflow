"""视频号登记台账域 ORM 模型。

新增「视频号列表」功能：登记视频号工商/合作信息台账，与现有发布账号矩阵
（VideoAccount，video_accounts 表）通过 video_account_id 关联打通。

- ChannelAccount     视频号登记台账（名称/微信号/实名/合作模式/合作公司等）
- ChannelOperator    运营者多对多（一个视频号可挂多名运营者，关联 users）
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Date,
    Boolean,
    Text,
    ForeignKey,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ChannelAccount(Base):
    """视频号登记台账。

    登记视频号的基本信息与商业合作信息，供运营管理侧掌握号池现状：
    - 实名类型：personal(个人) / enterprise(企业)
    - 合作模式：IAA(广告变现) / IAP(内购变现)，可空（尚未接入合作）
    - 运营者：多人（ChannelOperator 多对多子表）
    与现有发布账号矩阵（VideoAccount）通过 video_account_id 关联，
    打通「登记台账」与「发布/矩阵」流程。
    """
    __tablename__ = "channel_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 账号归属（操作人/号主，与现有账号库口径一致）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 视频号名称
    channel_name = Column(String(100), nullable=False, index=True)
    # 微信号（视频号绑定的微信）
    wechat_id = Column(String(200), nullable=True)
    # 实名类型：personal(个人) / enterprise(企业)
    verify_type = Column(String(20), nullable=True)
    # 实名人（个人=姓名，企业=企业全称）
    verify_name = Column(String(200), nullable=True)
    # 注册日期
    register_date = Column(Date, nullable=True)
    # 合作模式：IAA / IAP（可空=暂未接入）
    cooperation_mode = Column(String(20), nullable=True)
    # 合作公司
    coop_company = Column(String(200), nullable=True)
    # 关联现有发布账号矩阵（video_accounts.id），打通发布流程
    video_account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    remark = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    operators = relationship(
        "ChannelOperator",
        back_populates="channel_account",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ChannelAccount(id={self.id}, name={self.channel_name})>"


class ChannelOperator(Base):
    """视频号运营者（多对多）。

    一个视频号可登记多名运营者身份。operator_id 关联现有 users 表；
    若为外部人员（系统内无账号），operator_id 置空、operator_name 手填兜底。
    """
    __tablename__ = "channel_operators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("channel_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 关联系统用户（可选）
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 运营者姓名（operator_id 为空时手填外部人员姓名）
    operator_name = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    channel_account = relationship("ChannelAccount", back_populates="operators")

    def __repr__(self) -> str:
        return f"<ChannelOperator(id={self.id}, operator_id={self.operator_id})>"
