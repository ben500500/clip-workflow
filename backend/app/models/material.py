"""素材/项目/切片域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：Project / Episode / AutoClipProject / AutoClipRun / ClipCandidate /
DetectedInterval / SliceTask / SliceOutput / Publication / SystemConfig /
PlatformProfile / ImportTemplate / ImportHistory / BatchSlice / BatchSliceItem。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    BigInteger,
    Boolean,
    Text,
    ForeignKey,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="draft")
    config = Column(JSON, default=dict)
    # 创建人（数据隔离：运营专员默认仅可见自己创建的素材）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    episodes = relationship("Episode", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name})>"


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    episode_no = Column(Integer, nullable=True)
    source_file_key = Column(String(500), nullable=True)
    # 视频号素材导入（wechat_download）：URL 导入的最小粘合字段（来源链接，便于溯源）
    source_url = Column(String(2000), nullable=True)
    # 剧集封面（作为切片首帧叠加，按剧集独立存储；为空时切片用源视频首帧）
    cover_image_key = Column(String(500), nullable=True)
    # 剧集维度打通切片产线：归属剧目（可空，关联 dramas 表；用于剧目下「该剧已切片/待切片」聚合）
    drama_id = Column(UUID(as_uuid=True), ForeignKey("dramas.id", ondelete="SET NULL"), nullable=True, index=True)
    duration = Column(Float, nullable=True)
    resolution = Column(String(50), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    status = Column(String(50), default="uploaded")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="episodes")
    drama = relationship("Drama", back_populates="episodes")
    clip_candidates = relationship("ClipCandidate", back_populates="episode", cascade="all, delete-orphan")
    detected_intervals = relationship("DetectedInterval", back_populates="episode", cascade="all, delete-orphan")
    slice_tasks = relationship("SliceTask", back_populates="episode", cascade="all, delete-orphan")
    autoclip_project = relationship("AutoClipProject", back_populates="episode", uselist=False, cascade="all, delete-orphan")
    autoclip_runs = relationship("AutoClipRun", back_populates="episode", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Episode(id={self.id}, title={self.title})>"


class AutoClipProject(Base):
    __tablename__ = "autoclip_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, unique=True)
    autoclip_project_id = Column(String(100), unique=True, nullable=True)
    config = Column(JSON, nullable=True)
    pipeline_status = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    episode = relationship("Episode", back_populates="autoclip_project")

    def __repr__(self) -> str:
        return f"<AutoClipProject(id={self.id}, autoclip_project_id={self.autoclip_project_id})>"


class AutoClipRun(Base):
    """AI 智能选点执行历史（多次运行均可保留）。

    每次「启动选点 / 重新选点」都会落库一条记录，供工作台历史展示。
    """
    __tablename__ = "autoclip_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True)
    autoclip_project_id = Column(String(100), nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    status = Column(String(50), default="pending")  # pending/running/completed/failed
    progress = Column(Float, default=0.0)
    message = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    episode = relationship("Episode", back_populates="autoclip_runs")

    def __repr__(self) -> str:
        return f"<AutoClipRun(id={self.id}, status={self.status})>"


class ClipCandidate(Base):
    __tablename__ = "clip_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True)
    clip_index = Column(Integer, nullable=True)
    start_time = Column(Float, nullable=True)
    end_time = Column(Float, nullable=True)
    duration = Column(Float, nullable=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)
    outline = Column(String(500), nullable=True)
    score = Column(Float, nullable=True)
    recommend_reason = Column(Text, nullable=True)
    status = Column(String(50), default="pending")
    adjusted_start = Column(Float, nullable=True)
    adjusted_end = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    episode = relationship("Episode", back_populates="clip_candidates")
    slice_outputs = relationship("SliceOutput", back_populates="clip_candidate", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ClipCandidate(id={self.id}, clip_index={self.clip_index})>"


class DetectedInterval(Base):
    __tablename__ = "detected_intervals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True)
    interval_type = Column(String(50), nullable=True)
    start_time = Column(Float, nullable=True)
    end_time = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    label = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)
    source = Column(String(50), default="auto")
    detection_config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    episode = relationship("Episode", back_populates="detected_intervals")

    def __repr__(self) -> str:
        return f"<DetectedInterval(id={self.id}, type={self.interval_type})>"


class SliceTask(Base):
    __tablename__ = "slice_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True)
    celery_task_id = Column(String(100), nullable=True)
    # 实际执行该任务的 Worker 节点 ID（Worker 回调时写入，用于切片任务列表展示"由哪个节点完成"）
    node_id = Column(String(100), nullable=True)
    mode = Column(String(50), nullable=True)
    cutlist = Column(Text, nullable=True)
    intervals = Column(Text, nullable=True)
    dedupe_config = Column(JSON, nullable=True)
    # 多视频号素材去重：需要生成的素材变体数（null/1=不生成，零侵入；>1=切片后自动派生 N 个去重版本）
    variant_count = Column(Integer, nullable=True)
    # 源视频所在桶（普通切片 raw-footage；成品重新剪辑 sliced），重试时用于还原源
    source_bucket = Column(String(50), nullable=True)
    # 实际使用的源视频 file_key（重试时优先于剧集素材使用）
    source_file_key = Column(String(500), nullable=True)
    # 自定义文字水印配置（开启时透传给引擎，重试时保留）
    watermark_config = Column(JSON, nullable=True)
    # 图片角标配置（可选，切片后在成品上叠加角标；重试时保留）
    badges_config = Column(JSON, nullable=True)
    # 角标默认尺寸（px，可选；0=保持原图尺寸，角标未单独设 width 时生效；重试时保留）
    badge_default_width = Column(Integer, nullable=True)
    # 竖屏转横屏预处理配置（可选，切片前把竖屏素材转成横屏；重试时保留）
    vert2horiz_config = Column(JSON, nullable=True)
    # 字幕烧录配置（可选，{"enabled": bool, "srt": str}；重试时保留，避免重复 ASR）
    subtitle_config = Column(JSON, nullable=True)
    # 字幕对齐源字幕打码区域开关（默认 True；重试时保留）
    subtitle_align_mask = Column(Boolean, default=True, nullable=False)
    # 源视频字幕打码配置（可选，{"enabled": bool, "style": str, ...}；重试时保留）
    subtitle_mask_config = Column(JSON, nullable=True)
    # 恒定水印/角标打码配置（可选，打掉片源固定水印；重试时保留）
    watermark_mask_config = Column(JSON, nullable=True)
    # 固定文字角标配置（可选，在成品上叠加固定文字；重试时保留）
    text_overlays_config = Column(JSON, nullable=True)
    # 视频封面（可选）：选择图片作为视频首帧；重试时保留
    cover_image_key = Column(String(500), nullable=True)
    # 输出档位（original/auto/1080p/720p/480p）：高分辨率/高 fps 素材降档提速；重试时保留
    output_tier = Column(String(20), nullable=True)
    status = Column(String(50), nullable=True)
    progress = Column(Float, default=0.0)
    output_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    episode = relationship("Episode", back_populates="slice_tasks")
    outputs = relationship("SliceOutput", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SliceTask(id={self.id}, mode={self.mode})>"


class SliceOutput(Base):
    __tablename__ = "slice_outputs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("slice_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    clip_id = Column(UUID(as_uuid=True), ForeignKey("clip_candidates.id"), nullable=True, index=True)
    file_key = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    duration = Column(Float, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    resolution = Column(String(50), nullable=True)
    # 多视频号素材去重：变体组（同一基准切片的 N 套去重版本聚合；未开多版本时为 None，零侵入）
    variant_group_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("SliceTask", back_populates="outputs")
    clip_candidate = relationship("ClipCandidate", back_populates="slice_outputs")
    publications = relationship("Publication", back_populates="output", cascade="all, delete-orphan")
    publish_tasks = relationship("PublishTask", back_populates="output", cascade="all, delete-orphan")
    variants = relationship("ClipVariant", back_populates="output", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SliceOutput(id={self.id}, file_name={self.file_name})>"


class Publication(Base):
    __tablename__ = "publications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    output_id = Column(UUID(as_uuid=True), ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(50), nullable=True)
    publish_url = Column(String(500), nullable=True)
    publish_time = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=True)
    reject_reason = Column(Text, nullable=True)
    operator = Column(String(100), nullable=True)
    # 多视频号素材去重：本次发布使用的素材变体（发布后回写，便于审计）
    variant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    output = relationship("SliceOutput", back_populates="publications")

    def __repr__(self) -> str:
        return f"<Publication(id={self.id}, platform={self.platform})>"


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)
    description = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key})>"


class PlatformProfile(Base):
    __tablename__ = "platform_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    platform = Column(String(50), nullable=True)
    description = Column(String(500), nullable=True)
    dedupe_config = Column(JSON, nullable=True)
    target_resolution = Column(String(50), nullable=True)
    target_bitrate = Column(String(50), nullable=True)
    max_duration = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PlatformProfile(id={self.id}, name={self.name})>"


class ImportTemplate(Base):
    __tablename__ = "import_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=True)
    platform = Column(String(100), nullable=True)
    mapping = Column(JSON, nullable=True)
    unit_conversions = Column(JSON, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ImportTemplate(id={self.id}, name={self.name})>"


class ImportHistory(Base):
    __tablename__ = "import_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String(500), nullable=True)
    platform = Column(String(100), nullable=True)
    import_mode = Column(String(50), nullable=True)
    target_table = Column(String(100), nullable=True)
    imported_count = Column(Integer, default=0)
    updated_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    errors = Column(JSON, nullable=True)
    operator = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ImportHistory(id={self.id}, file_name={self.file_name})>"


class BatchSlice(Base):
    """批量切片工作流（三期方案）。

    一次请求 = 一份 JSON（剧名 + 剧集地址列表）+ 一套一键切片配置。
    系统按剧名查找/创建 Project，再按列表顺序逐集完成「AI 选点 → 自动审核 → 一键切片 → 删除源视频」。
    """
    __tablename__ = "batch_slices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=True)
    # 目标项目（按剧名查找/创建），数据隔离归属以 project.created_by 为准
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    # 一键切片配置快照（整批统一生效）
    slice_config = Column(JSON, default=dict)
    status = Column(String(50), default="pending")  # pending/running/completed/partial_failed/failed/cancelled
    total = Column(Integer, default=0)
    done = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    output_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    # 创建批次的操作人（用于数据隔离校验）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("Project", backref="batch_slices")
    items = relationship("BatchSliceItem", back_populates="batch", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<BatchSlice(id={self.id}, name={self.name}, status={self.status})>"


class BatchSliceItem(Base):
    """批量切片批次项：列表中的一集。"""
    __tablename__ = "batch_slice_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("batch_slices.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)          # 列表顺序（1,2,3…严格按序）
    title = Column(String(255), nullable=True)     # 剧集标题/文件名
    source_path = Column(Text, nullable=True)      # 局域网/本地视频路径
    file_name = Column(String(500), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    episode_id = Column(UUID(as_uuid=True), nullable=True, index=True)   # 关联创建的 Episode
    slice_task_id = Column(UUID(as_uuid=True), nullable=True)            # 关联的 SliceTask
    autoclip_run_id = Column(UUID(as_uuid=True), nullable=True)          # 关联的 AutoClipRun
    detect_task_id = Column(UUID(as_uuid=True), nullable=True)           # 关联的区间检测 SliceTask（mode=detect_*）
    status = Column(String(50), default="pending")  # pending/uploading/autoclip/reviewing/detecting/slicing/completed/failed/cancelled/skipped
    phase = Column(String(50), nullable=True)       # 当前阶段：upload/autoclip/review/slice/delete/source_delete
    progress = Column(Float, default=0.0)
    output_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    batch = relationship("BatchSlice", back_populates="items")

    def __repr__(self) -> str:
        return f"<BatchSliceItem(id={self.id}, seq={self.seq}, status={self.status})>"
