import enum
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
    Date,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    """用户角色枚举."""
    admin = "admin"
    operator = "operator"
    publisher = "publisher"
    material = "material"


ROLE_DISPLAY_NAMES: dict[UserRole, str] = {
    UserRole.admin: "管理员",
    UserRole.operator: "运营专员",
    UserRole.publisher: "发布专员",
    UserRole.material: "素材专员",
}


class User(Base):
    """系统用户."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)
    role = Column(String(20), default=UserRole.operator.value, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="draft")
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    episodes = relationship("Episode", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name})>"


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=True)
    episode_no = Column(Integer, nullable=True)
    source_file_key = Column(String(500), nullable=True)
    duration = Column(Float, nullable=True)
    resolution = Column(String(50), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    status = Column(String(50), default="uploaded")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="episodes")
    clip_candidates = relationship("ClipCandidate", back_populates="episode", cascade="all, delete-orphan")
    detected_intervals = relationship("DetectedInterval", back_populates="episode", cascade="all, delete-orphan")
    slice_tasks = relationship("SliceTask", back_populates="episode", cascade="all, delete-orphan")
    autoclip_project = relationship("AutoClipProject", back_populates="episode", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Episode(id={self.id}, title={self.title})>"


class AutoClipProject(Base):
    __tablename__ = "autoclip_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, unique=True)
    autoclip_project_id = Column(String(100), unique=True, nullable=True)
    config = Column(JSON, nullable=True)
    pipeline_status = Column(String(50), nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    episode = relationship("Episode", back_populates="autoclip_project")

    def __repr__(self) -> str:
        return f"<AutoClipProject(id={self.id}, autoclip_project_id={self.autoclip_project_id})>"


class ClipCandidate(Base):
    __tablename__ = "clip_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
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
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
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
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    celery_task_id = Column(String(100), nullable=True)
    mode = Column(String(50), nullable=True)
    cutlist = Column(Text, nullable=True)
    intervals = Column(Text, nullable=True)
    dedupe_config = Column(JSON, nullable=True)
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
    task_id = Column(UUID(as_uuid=True), ForeignKey("slice_tasks.id", ondelete="CASCADE"), nullable=False)
    clip_id = Column(UUID(as_uuid=True), ForeignKey("clip_candidates.id"), nullable=True)
    file_key = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    duration = Column(Float, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    resolution = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("SliceTask", back_populates="outputs")
    clip_candidate = relationship("ClipCandidate", back_populates="slice_outputs")
    publications = relationship("Publication", back_populates="output", cascade="all, delete-orphan")
    publish_tasks = relationship("PublishTask", back_populates="output", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SliceOutput(id={self.id}, file_name={self.file_name})>"


class Publication(Base):
    __tablename__ = "publications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    output_id = Column(UUID(as_uuid=True), ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(50), nullable=True)
    publish_url = Column(String(500), nullable=True)
    publish_time = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=True)
    reject_reason = Column(Text, nullable=True)
    operator = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    output = relationship("SliceOutput", back_populates="publications")

    def __repr__(self) -> str:
        return f"<Publication(id={self.id}, platform={self.platform})>"


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key})>"


class PlatformProfile(Base):
    __tablename__ = "platform_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    platform = Column(String(50), nullable=True)
    dedupe_config = Column(JSON, nullable=True)
    target_resolution = Column(String(50), nullable=True)
    target_bitrate = Column(String(50), nullable=True)
    max_duration = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PlatformProfile(id={self.id}, name={self.name})>"


class PublishTask(Base):
    __tablename__ = "publish_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    output_id = Column(UUID(as_uuid=True), ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(50), nullable=True)
    account_name = Column(String(100), nullable=True)
    status = Column(String(50), nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    cover_file_key = Column(String(500), nullable=True)
    mini_program_link = Column(String(500), nullable=True)
    link_attached = Column(Boolean, default=False)
    published_url = Column(String(500), nullable=True)
    published_id = Column(String(200), nullable=True)
    published_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    require_manual_confirm = Column(Boolean, default=True)
    screenshot_key = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    output = relationship("SliceOutput", back_populates="publish_tasks")
    video_metrics = relationship("VideoMetric", back_populates="publish_task", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PublishTask(id={self.id}, platform={self.platform})>"


class PublishProfile(Base):
    __tablename__ = "publish_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=True)
    account_name = Column(String(100), nullable=True)
    chrome_debug_port = Column(Integer, default=9222)
    cookie_file = Column(String(500), nullable=True)
    title_template = Column(String(500), nullable=True)
    description_template = Column(Text, nullable=True)
    default_tags = Column(JSON, nullable=True)
    mini_program_link = Column(String(500), nullable=True)
    publish_mode = Column(String(50), default="immediate")
    require_manual_confirm = Column(Boolean, default=True)
    min_interval_seconds = Column(Integer, default=300)
    max_daily_publish = Column(Integer, default=20)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PublishProfile(id={self.id}, platform={self.platform})>"


class VideoMetric(Base):
    __tablename__ = "video_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publish_task_id = Column(UUID(as_uuid=True), ForeignKey("publish_tasks.id", ondelete="SET NULL"), nullable=True)
    video_id = Column(String(200), nullable=True)
    title = Column(String(500), nullable=True)
    publish_date = Column(Date, nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True)
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