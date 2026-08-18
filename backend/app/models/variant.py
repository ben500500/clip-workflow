"""多视频号素材去重域 ORM 模型（圆桌定稿方案 Phase 0 数据层）。

包含：
- ClipVariant      素材变体（一个切片输出派生出的 N 套结构性差异版本，供多视频号分别上传）
- VideoFingerprint 视频指纹（画面 pHash + 音频声纹，跨版本比对撞车，L3/L4 盲区覆盖）

设计要点（对应圆桌定稿）：
- 变体与切片输出 1:N：基准切片输出 SliceOutput 通过 variant_group_id 聚合一组变体，
  每个 ClipVariant 绑定一个 SliceOutput（变体也是独立可发布的成片）。
- 一个变体只允许绑定一个发布账号：通过 unique(account_id) 硬约束 + 审计，防止同素材原样发多号。
- 指纹表覆盖 L3 音频 + L4 时域序列两个此前盲区：phash / audio_fp / segment_seq 三路指纹，
  pgvector 可用时走向量相似度，否则回退为字符串距离（见 fingerprint_service）。

护栏：
- variant_count=1 时完全等同现状（零侵入可回滚）。
- 撞车失败宁可降级人工处理，绝不把同一素材原样发多号。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    ForeignKey,
    DateTime,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ClipVariant(Base):
    """素材变体：一个切片输出的一个去重版本。

    变体是实际可发布的成片文件，绑定一个切片输出（file_key 指向变体文件）与一个账号。
    同一变体组（variant_group_id）内各变体应保持足够指纹距离，避免平台 L3/L4 撞车。
    """
    __tablename__ = "clip_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 基准切片输出（基准版 SliceOutput），变体由它派生
    output_id = Column(UUID(as_uuid=True), ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=False, index=True)
    # 变体组（与基准 SliceOutput 同组）；未开多版本时为 None（零侵入）
    variant_group_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 变体序号（1=基准，2..N=派生变体）
    variant_index = Column(Integer, default=1)
    # 变体文件（MinIO key）与展示信息
    file_key = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    duration = Column(Float, nullable=True)
    resolution = Column(String(50), nullable=True)
    # 去重/结构差异参数快照（dedupe_config + structural 差异项，便于追溯与重放）
    dedupe_config = Column(JSON, nullable=True)
    structural_diff = Column(JSON, nullable=True)
    # 生成状态：pending/running/completed/failed/collision/skipped
    status = Column(String(50), default="pending")
    # 指纹碰撞结果（去重风险量化，供前端矩阵看板）
    phash_distance = Column(Float, nullable=True)     # 与同组其它变体的最小画面距离（越大越安全）
    audio_distance = Column(Float, nullable=True)     # 与同组其它变体的最小音频距离
    seg_distance = Column(Float, nullable=True)       # 与同组其它变体的最小时域序列距离（L4）
    collision = Column(Boolean, default=False)        # 是否与同组/历史变体撞车
    collision_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    # 发布绑定：一个变体只允许绑一个账号（防同素材原样发多号）
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 创建人（数据隔离 + 审计）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    output = relationship("SliceOutput", back_populates="variants")

    __table_args__ = (
        # 硬约束：同一账号只能绑定一个变体（防同素材原样发多号，护栏核心）
        UniqueConstraint("account_id", name="uq_clip_variants_account_id"),
    )

    def __repr__(self) -> str:
        return f"<ClipVariant(id={self.id}, index={self.variant_index}, status={self.status})>"


class VideoFingerprint(Base):
    """视频指纹：覆盖 L3 音频 + L4 时域序列两个盲区。

    每个切片输出（含变体）生成一组指纹。多路指纹并行：
      - phash           画面感知哈希（十六进制字符串，可转向量）
      - audio_fp        音频声纹特征（字符串/JSON，用于音频指纹比对）
      - segment_seq     时域序列指纹（镜头切换序列 / 关键帧签名，用于 L4 序列比对）
    pgvector 可用时把 phash 解析为向量走相似度；否则回退字符串汉明距离。
    """
    __tablename__ = "video_fingerprints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 指纹主体：切片输出或变体
    output_id = Column(UUID(as_uuid=True), ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=True, index=True)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("clip_variants.id", ondelete="CASCADE"), nullable=True, index=True)
    # 视频文件（MinIO key）与版本，便于对同一文件重算
    file_key = Column(String(500), nullable=True)
    # 指纹算法版本（phash_v1 / audio_v2 / seq_v1），便于升级
    algorithm = Column(String(50), nullable=False, default="phash_v1")
    # 指纹内容（十六进制字符串 / JSON）
    hash_value = Column(Text, nullable=True)
    # 量化指纹向量（逗号分隔浮点，pgvector 可用时写入 vector 列）
    vector = Column(Text, nullable=True)
    # 视频时长 / 分辨率（辅助相似度加权）
    duration = Column(Float, nullable=True)
    resolution = Column(String(50), nullable=True)
    # 关联的变体组（便于按组比较）
    variant_group_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<VideoFingerprint(id={self.id}, algo={self.algorithm}, output={self.output_id})>"
