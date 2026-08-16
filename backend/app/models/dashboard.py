"""看板/指标域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：VideoMetric / MiniProgramMetric / AdMetric / DramaMetric /
FunnelSnapshot / EcosystemMetric。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Date,
    DateTime,
    JSON,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class VideoMetric(Base):
    __tablename__ = "video_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publish_task_id = Column(UUID(as_uuid=True), ForeignKey("publish_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    video_id = Column(String(200), nullable=True)
    title = Column(String(500), nullable=True)
    publish_date = Column(Date, nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    # 平台显式标记：wechat_channel / douyin / kuaishou（短片分析按平台分 Tab）
    platform = Column(String(50), nullable=True)
    play_count = Column(Integer, default=0)
    finish_rate = Column(Float, default=0)
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    share_count = Column(Integer, default=0)
    favorite_count = Column(Integer, default=0)
    social_recommend_ratio = Column(Float, default=0)
    social_recommend_play = Column(Integer, default=0)
    friend_recommend_play = Column(Integer, default=0)
    jump_click_count = Column(Integer, default=0)
    jump_click_rate = Column(Float, default=0)
    attributed_uv = Column(Integer, default=0)
    attributed_revenue = Column(Float, default=0)
    content_type = Column(String(50), nullable=True)
    # 视频标签系统（二期）：多标签 JSON 数组，如 ["爆款", "虐恋", "高完播"]
    tags = Column(JSON, nullable=True)
    drama_id = Column(UUID(as_uuid=True), nullable=True)
    traffic_method = Column(String(50), nullable=True)
    publish_time_slot = Column(String(10), nullable=True)
    play_level = Column(String(10), nullable=True)
    production_cost = Column(Float, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    publish_task = relationship("PublishTask", back_populates="video_metrics")

    def __repr__(self) -> str:
        return f"<VideoMetric(id={self.id}, video_id={self.video_id})>"


class MiniProgramMetric(Base):
    __tablename__ = "mini_program_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    uv = Column(Integer, default=0)
    new_user_count = Column(Integer, default=0)
    drama_play_count = Column(Integer, default=0)
    avg_play_duration = Column(Float, default=0)
    drama_finish_rate = Column(Float, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<MiniProgramMetric(id={self.id}, date={self.date})>"


class AdMetric(Base):
    __tablename__ = "ad_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    impression_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    ctr = Column(Float, default=0)
    ecpm = Column(Float, default=0)
    revenue = Column(Float, default=0)
    reward_video_impression = Column(Integer, default=0)
    reward_video_revenue = Column(Float, default=0)
    interstitial_impression = Column(Integer, default=0)
    interstitial_revenue = Column(Float, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<AdMetric(id={self.id}, date={self.date})>"


class DramaMetric(Base):
    __tablename__ = "drama_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=True)
    drama_id = Column(UUID(as_uuid=True), nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    uv = Column(Integer, default=0)
    play_count = Column(Integer, default=0)
    finish_rate = Column(Float, default=0)
    ad_impression = Column(Integer, default=0)
    ad_revenue = Column(Float, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<DramaMetric(id={self.id}, drama_id={self.drama_id})>"


class FunnelSnapshot(Base):
    __tablename__ = "funnel_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    total_play = Column(Integer, nullable=True)
    jump_click = Column(Integer, nullable=True)
    jump_rate = Column(Float, nullable=True)
    mini_program_uv = Column(Integer, nullable=True)
    drama_play_uv = Column(Integer, nullable=True)
    play_rate = Column(Float, nullable=True)
    ad_exposure_uv = Column(Integer, nullable=True)
    exposure_rate = Column(Float, nullable=True)
    revenue = Column(Float, nullable=True)
    revenue_per_1000_play = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<FunnelSnapshot(id={self.id}, date={self.date})>"


class EcosystemMetric(Base):
    __tablename__ = "ecosystem_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    article_count = Column(Integer, default=0)
    article_read_count = Column(Integer, default=0)
    mini_program_uv_from_article = Column(Integer, default=0)
    wecom_new_friends = Column(Integer, default=0)
    wecom_total_friends = Column(Integer, default=0)
    wecom_source = Column(String(50), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<EcosystemMetric(id={self.id}, date={self.date})>"
