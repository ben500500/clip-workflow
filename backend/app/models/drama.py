"""剧目主数据域 ORM 模型。

按《剧目管理设计方案-20260818.md》落地，隶属 ISSUE #130「视频号自动发布」。
包含 4 张表：
- dramas           剧目主表（含运营可读唯一 ID `code` = DR-<8位HEX>、剧情简介、封面）
- drama_stills     剧照（一对多，MinIO object key）
- drama_accounts   剧目 ↔ 视频号（多对多，一剧多号）
- drama_materials  剧目 ↔ 发布素材（记录该剧生成过的发布素材）

沿用既有约定：UUID 主键、MinIO object key 存图（不落主表二进制）、
created_by=操作人 / operator_id=号主、RBAC data_scope 过滤、审计可溯源。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    ForeignKey,
    DateTime,
    Date,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


def gen_drama_code() -> str:
    """生成运营可读的唯一剧目 ID：DR-<8位大写HEX>（如 DR-0A3F9C2E）。

    基于 uuid4().hex 前 8 位取大写，入库前由服务层做唯一性冲突重抽。
    """
    return "DR-" + uuid.uuid4().hex[:8].upper()


class DramaTheater(Base):
    """剧目 ↔ 剧场（多对多，一剧多剧场）。

    ISSUE #142：同一剧目可出现在多个剧场（如「海漫剧场」与其它剧场同时上架）。
    兼容既有 `dramas.theater_id`（一剧一场时期遗留）：迁移时已把存量 theater_id
    回填进本表；此后以本关联表为权威。
    """
    __tablename__ = "drama_theaters"
    __table_args__ = (
        UniqueConstraint("drama_id", "theater_id", name="uq_drama_theater"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drama_id = Column(UUID(as_uuid=True), ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, index=True)
    theater_id = Column(UUID(as_uuid=True), ForeignKey("theaters.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    drama = relationship("Drama", back_populates="theater_links")
    theater = relationship("Theater")

    def __repr__(self) -> str:
        return f"<DramaTheater(drama={self.drama_id}, theater={self.theater_id})>"


class Drama(Base):
    """剧目主表。

    `name` 为去重核心（唯一索引）：再次导入同名称剧目即视为更新该条。
    `code` 为运营可读唯一 ID（DR-<8位HEX>），与 name 双唯一。
    """
    __tablename__ = "dramas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 运营可读唯一剧目 ID（DR-<8位HEX>）
    code = Column(String(20), unique=True, nullable=False, index=True, default=gen_drama_code)
    # 漫剧名称（去重核心）
    name = Column(String(200), unique=True, nullable=False, index=True)
    # 男频 / 女频
    frequency = Column(String(20), nullable=True, index=True)
    # 漫剧类型（AI真人剧 / 真人剧 / 动漫…）
    type = Column(String(30), nullable=True)
    # 题材多选标签（JSON 数组，如 ["都市","反击"]）
    tags = Column(JSON, nullable=True)
    # 发布话题标签（JSON 数组，如 ["#短剧", "#婆媳关系"]）
    # 剧目详情中按「话题大方向」选择自动带入并保存，发布时直接复用
    topics = Column(JSON, nullable=True)
    # 评级（新剧S+ / 新剧A+ / SS+ / 空）
    rating = Column(String(20), nullable=True)
    # 剧情简介（人工录入，也是发布素材生成的入参 story）
    synopsis = Column(Text, nullable=True)
    # 剧目封面（MinIO object key，图片类型）
    cover_file_key = Column(String(500), nullable=True)
    # 上架状态（草稿/待上架/已上架/已下架/归档）
    listing_status = Column(String(20), nullable=False, default="已上架", index=True)
    # 更新日期（表内）
    updated_date = Column(Date, nullable=True)
    # 上架日期（表内）
    listed_at = Column(DateTime, nullable=True)
    # 素材链接（百度网盘，去除密码后存主表）
    material_link = Column(String(1000), nullable=True)
    # 网盘提取码（密文存储，不进审计日志）
    material_link_pwd = Column(String(200), nullable=True)
    # 归属（R17 actor/operator 分离）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 兼容遗留列：一剧一场时期的主剧场（可空）。已迁移进 drama_theaters 关联表，
    # 后续以 drama_theaters 为权威；该列仅用于历史数据兼容/迁移标记。
    theater_id = Column(UUID(as_uuid=True), ForeignKey("theaters.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 所属剧场（一剧多剧场，多对多，ISSUE #142）
    theater_links = relationship("DramaTheater", back_populates="drama", cascade="all, delete-orphan")
    theaters = relationship("Theater", secondary="drama_theaters", viewonly=True)
    # 兼容遗留单关系（仅在 theater_id 仍存值时生效，用于旧逻辑过渡）
    theater = relationship("Theater", back_populates="dramas")
    # 剧照（一对多）
    stills = relationship(
        "DramaStill",
        back_populates="drama",
        cascade="all, delete-orphan",
        order_by="DramaStill.sort_order",
    )
    # 关联视频号（多对多）
    accounts = relationship("DramaAccount", back_populates="drama", cascade="all, delete-orphan")
    # 关联剧集（切片产线；Episode.drama_id 反查，用于剧目下「该剧已切片/待切片」聚合）
    episodes = relationship("Episode", back_populates="drama")

    def __repr__(self) -> str:
        return f"<Drama(id={self.id}, code={self.code}, name={self.name})>"


class DramaStill(Base):
    """剧照（一对多，MinIO object key，可拖拽排序）。"""
    __tablename__ = "drama_stills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drama_id = Column(UUID(as_uuid=True), ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, index=True)
    file_key = Column(String(500), nullable=False)
    sort_order = Column(Integer, default=0)

    drama = relationship("Drama", back_populates="stills")

    def __repr__(self) -> str:
        return f"<DramaStill(id={self.id}, file_key={self.file_key})>"


class DramaAccount(Base):
    """剧目 ↔ 视频号（多对多，一剧多号双向可查）。

    - 从「视频号详情选剧目」= 按 account_id 反查该号关联的剧目；
    - 从「剧目库看该剧在哪些号上架」= 按 drama_id 正查 accounts。
    """
    __tablename__ = "drama_accounts"
    __table_args__ = (
        UniqueConstraint("drama_id", "account_id", name="uq_drama_account"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drama_id = Column(UUID(as_uuid=True), ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("video_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    # 该账号上架时间线（可选）
    listed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    drama = relationship("Drama", back_populates="accounts")


class DramaMaterial(Base):
    """剧目 ↔ 发布素材（记录该剧生成过的发布素材，便于剧目库聚合展示）。

    PublishTask.material_id 直接指向 publish_materials（现有模型），本表仅记录
    「剧目↔素材」的独立对应关系。若按号分别生成则带 account_id（一剧多号一素材）。
    """
    __tablename__ = "drama_materials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drama_id = Column(UUID(as_uuid=True), ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(UUID(as_uuid=True), ForeignKey("publish_materials.id", ondelete="SET NULL"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
