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
    UniqueConstraint,
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