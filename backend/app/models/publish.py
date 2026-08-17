"""发布域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：VideoAccount / MiniProgram / PublishBatch / PublishTask /
PublishProfile / PublishMaterial。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Text,
    ForeignKey,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class VideoAccount(Base):
    """视频号/抖音/快手账号库（矩阵管理，一期）。

    管理各平台矩阵账号，关联发布配置（chrome 端口 + Cookie 绑定登录态），
    支持分组、备注、启用/停用、小程序挂载资质标记，供发布弹窗下拉选择。
    """
    __tablename__ = "video_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 账号归属（多运营者，R14）：created_by=操作人（仅审计），operator_id=号主（微信号主人）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 账号名称（如「主号-剧集A」），用户可读
    account_name = Column(String(100), nullable=False, index=True)
    # 平台：wechat_channel / douyin / kuaishou（矩阵跨平台复用）
    platform = Column(String(50), nullable=False, index=True)
    # 分组（剧集A/B、情感、爽文…），便于批量选号
    group_name = Column(String(100), nullable=True)
    # 平台侧账号唯一标识（视频号 ID / 抖音号等）
    wxid = Column(String(200), nullable=True)
    account_uid = Column(String(200), nullable=True)
    # 关联发布配置（chrome 端口 + Cookie 绑定登录态）
    profile_id = Column(UUID(as_uuid=True), nullable=True)
    # 视频号小程序挂载资质（平台强引导功能，有资质限制）
    mini_program_enabled = Column(Boolean, default=False)
    # 发布跳转配置（多选）：端原生对应「视频号剧集」、小程序对应「小程序短剧」
    # 值为 ['native'] / ['mini_program'] / ['native','mini_program']，发布时据此选择
    publish_jump = Column(JSON, nullable=True)
    remark = Column(String(500), nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<VideoAccount(id={self.id}, name={self.account_name}, platform={self.platform})>"


class MiniProgram(Base):
    """小程序链接库（一期）。

    视频号发布时可挂载的小程序链接，通常带渠道归因参数（jump_click 归因对齐），
    发布时下拉选择而非手填，保证参数规范统一。
    """
    __tablename__ = "mini_programs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    appid = Column(String(200), nullable=True)
    path = Column(String(500), nullable=True)
    # 完整链接（带渠道归因参数的落地链接模板）
    full_link = Column(String(1000), nullable=False)
    remark = Column(String(500), nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<MiniProgram(id={self.id}, name={self.name})>"


class PublishBatch(Base):
    """发布批次表（多运营者，R14）。

    一次 API 请求 = 1 个 batch；batch 下 N 个 task。
    均分/轮询/指定 是 batch 级分配逻辑，task 创建后 operator_id 不可变（不迁移）。
    """
    __tablename__ = "publish_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 操作人（发起的 user，含 publisher 代发 operator 号场景，R17）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 策略：even(均分) / round_robin(轮询) / assigned(指定)
    strategy = Column(String(50), nullable=True)
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    total_items = Column(Integer, default=0)
    status = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PublishBatch(id={self.id}, strategy={self.strategy})>"


class PublishTask(Base):
    __tablename__ = "publish_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    output_id = Column(UUID(as_uuid=True), ForeignKey("slice_outputs.id", ondelete="CASCADE"), nullable=False, index=True)
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
    # ── 一期：账号矩阵 / 小程序库 / 短片来源关联（冗余快照 + 外键并行，兼容历史数据） ──
    video_account_id = Column(UUID(as_uuid=True), nullable=True)
    # 发布跳转配置快照（从关联 VideoAccount 带入）：['native'] / ['mini_program'] / 两者
    publish_jump = Column(JSON, nullable=True)
    # ── 多运营者（R14/R17）：批次外键 + 号主 operator_id（创建后不可变，不迁移） ──
    batch_id = Column(UUID(as_uuid=True), ForeignKey("publish_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    mini_program_id = Column(UUID(as_uuid=True), nullable=True)
    # 短片来源：提示词记录（带去文案/时长/题材/基调）+ 发布素材记录（带去话题标签）
    prompt_record_id = Column(UUID(as_uuid=True), nullable=True)
    material_id = Column(UUID(as_uuid=True), nullable=True)
    # ── 方向② 批量发布体验：重试计数 + 死信标记（失败不再静默丢失，可回溯重发） ──
    retry_count = Column(Integer, default=0, nullable=False)
    dead_letter = Column(Boolean, default=False, nullable=False)
    dead_letter_reason = Column(Text, nullable=True)
    # ── 定时发布（R99）：scheduled_at 非空=预约到点发布；为空=立即发布（保持历史行为） ──
    # 预约时 status=scheduled，到点由调度守护投递置为 pending 并触发 task_publish_video。
    scheduled_at = Column(DateTime, nullable=True, index=True)
    # 来源时间窗口快照（前端展示用）：如 07:00-08:00（预置）/ 自定义窗口名
    time_slot_label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    output = relationship("SliceOutput", back_populates="publish_tasks")
    video_metrics = relationship("VideoMetric", back_populates="publish_task", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PublishTask(id={self.id}, platform={self.platform})>"


class PublishProfile(Base):
    __tablename__ = "publish_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 账号归属（多运营者）：created_by=操作人，operator_id=号主（微信号主人）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 多运营者字段（Part 3 毕业 / 路由表）：tier、proxy、fingerprint、egress_ip、grad_status
    tier = Column(Integer, default=0)
    proxy_url = Column(String(500), nullable=True)
    fingerprint_profile = Column(JSON, nullable=True)
    egress_ip = Column(String(100), nullable=True)
    chrome_debug_host = Column(String(200), nullable=True)
    grad_status = Column(String(50), nullable=True)
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


class PublishTimeSlot(Base):
    """定时发布时间窗口配置（预置 + 自定义）。

    描述一天内的可发布窗口（每天循环），不含具体日期。
    - is_preset=True 为系统预置窗口（07:00-08:00、18:00-20:00），不可删除/改时段。
    - is_preset=False 为运营者自定义窗口，可增删改。
    创建发布任务时选择窗口，系统在 [start_time, end_time] 内随机选一个今天/明天的
    具体时间点作为 PublishTask.scheduled_at，实现窗口内错峰分散发布。
    """
    __tablename__ = "publish_time_slots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    # 每天窗口起止时间（HH:MM，24 小时制），如 "07:00" / "08:00"
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    enabled = Column(Boolean, default=True)
    is_preset = Column(Boolean, default=False, nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PublishTimeSlot(id={self.id}, name={self.name}, {self.start_time}-{self.end_time}, preset={self.is_preset})>"


class PublishMaterial(Base):
    """短片制作（v7）：短剧发布素材生成记录。

    保存每次「剧情梗概 → 发布素材」的生成历史：
    短标题 / 三款视频配文 / 成套话题标签 / 三条置顶互动神评。
    模型复用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME）。
    """
    __tablename__ = "publish_materials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 用户输入的短剧剧情梗概 / 已生成的 Seedance 提示词 / 短剧标题
    story = Column(Text, nullable=False)
    # 可选参数：标题 / 题材 / 基调 / 平台 / 补充要求
    title = Column(String(500), nullable=True)
    theme = Column(String(200), nullable=True)
    tone = Column(String(200), nullable=True)
    platform = Column(String(200), nullable=True)
    extra_requirements = Column(Text, nullable=True)
    # 实际使用的模型名（取自 autoclip 配置）
    model = Column(String(100), nullable=True)
    # 生成的发布素材（JSON：short_title / captions / tags / comments）
    material_json = Column(JSON, nullable=False)
    # 来源提示词记录（短片分析：发布素材 → 提示词 → 发布任务 链路关联）
    prompt_record_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PublishMaterial(id={self.id})>"
