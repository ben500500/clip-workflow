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

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class UserSession(Base):
    """用户登录会话（JWT refresh token 管理）.

    二期安全认证体系：双 Token 机制。access_token 短期（30 分钟），
    refresh_token 长期（7 天）并落库，支持主动登出/失效（token 黑名单）。
    """
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_hash = Column(String(255), nullable=False, unique=True)
    access_token_jti = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(45), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<UserSession(id={self.id}, user_id={self.user_id}, revoked={self.is_revoked})>"


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
    # 实际执行该任务的 Worker 节点 ID（Worker 回调时写入，用于切片任务列表展示"由哪个节点完成"）
    node_id = Column(String(100), nullable=True)
    mode = Column(String(50), nullable=True)
    cutlist = Column(Text, nullable=True)
    intervals = Column(Text, nullable=True)
    dedupe_config = Column(JSON, nullable=True)
    # 源视频所在桶（普通切片 raw-footage；成品重新剪辑 sliced），重试时用于还原源
    source_bucket = Column(String(50), nullable=True)
    # 实际使用的源视频 file_key（重试时优先于剧集素材使用）
    source_file_key = Column(String(500), nullable=True)
    # 自定义文字水印配置（开启时透传给引擎，重试时保留）
    watermark_config = Column(JSON, nullable=True)
    # 竖屏转横屏预处理配置（可选，切片前把竖屏素材转成横屏；重试时保留）
    vert2horiz_config = Column(JSON, nullable=True)
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


class AuditLog(Base):
    """审计日志（V3）：操作人、操作时间、操作类型、目标对象、变更前后值。

    用于安全合规与运维追溯，仅 superadmin/admin 可查看。
    """
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_name = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False, index=True)   # 操作类型，如 project.create / user.role.update
    target_type = Column(String(100), nullable=True)
    target_id = Column(String(100), nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, operator={self.operator_name})>"


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
    last_heartbeat = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<WorkerNode(id={self.node_id}, status={self.status})>"


class ShortdramaPrompt(Base):
    """短片制作（v6）：Seedance 提示词生成记录。

    保存每次「文案 → Seedance 提示词」的生成历史，
    与去水印任务共同构成「短片制作」工作流（提示词生成 → 去水印出片）。
    """
    __tablename__ = "shortdrama_prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 用户输入的短剧文案（对白/旁白原文）
    source_text = Column(Text, nullable=False)
    # 时长：10 / 15 秒
    duration = Column(Integer, default=15, nullable=False)
    # 题材 / 基调 / 角色 / 补充要求（可选）
    theme = Column(String(200), nullable=True)
    tone = Column(String(200), nullable=True)
    characters = Column(Text, nullable=True)
    extra_requirements = Column(Text, nullable=True)
    # 实际使用的模型名（取自 autoclip 配置）
    model = Column(String(100), nullable=True)
    # 生成的 Seedance 提示词正文
    prompt_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ShortdramaPrompt(id={self.id}, duration={self.duration})>"


class WatermarkTask(Base):
    """去水印任务（一次批量提交 = 一个任务，内含多条视频）。

    用户上传若干视频并选择去水印引擎（remove_ai_watermarks / seedance）后
    提交，任务异步执行并保存历史，支持进度展示、下载与删除。
    """
    __tablename__ = "watermark_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 去水印引擎：remove_ai / seedance
    engine = Column(String(50), nullable=False)
    # 引擎选项（JSON）：mark / backend / region / use_lama 等
    options = Column(JSON, default=dict)
    name = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")  # pending/running/completed/failed/cancelled
    progress = Column(Float, default=0.0)
    total_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    videos = relationship("WatermarkVideo", back_populates="task", cascade="all, delete-orphan", order_by="WatermarkVideo.created_at")

    def __repr__(self) -> str:
        return f"<WatermarkTask(id={self.id}, engine={self.engine}, status={self.status})>"


class WatermarkVideo(Base):
    """去水印任务下的单条视频。"""
    __tablename__ = "watermark_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("watermark_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(500), nullable=False)
    # MinIO 对象 key（raw-footage 桶，源视频）
    source_file_key = Column(String(500), nullable=False)
    source_bucket = Column(String(50), default="raw-footage")
    file_size = Column(BigInteger, nullable=True)
    # 输出文件对象 key（watermark-output 桶）
    output_file_key = Column(String(500), nullable=True)
    output_bucket = Column(String(50), nullable=True)
    output_file_size = Column(BigInteger, nullable=True)
    status = Column(String(50), default="pending")  # pending/running/completed/failed/cancelled
    progress = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("WatermarkTask", back_populates="videos")

    def __repr__(self) -> str:
        return f"<WatermarkVideo(id={self.id}, file_name={self.file_name}, status={self.status})>"