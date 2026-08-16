"""短片制作域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：ShortdramaPrompt / WatermarkTask / WatermarkVideo。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    BigInteger,
    Text,
    ForeignKey,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ShortdramaPrompt(Base):
    """短片制作（v6）：Seedance 提示词生成记录。

    保存每次「文案 → Seedance 提示词」的生成历史，
    支持关联成片视频（Seedance 生成结果），可一键导入去水印流程，
    与去水印任务共同构成「短片制作」工作流（提示词生成 → 去水印出片）。
    """
    __tablename__ = "shortdrama_prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 用户输入的短剧文案（对白/旁白原文）
    source_text = Column(Text, nullable=False)
    # 时长：10 / 15 秒或自定义秒数
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
    # 提示词三版本：长 / 短（固定模板）+ AI（Seedance 生成）
    prompt_long = Column(Text, nullable=True)
    prompt_short = Column(Text, nullable=True)
    # 关联的成片视频（Seedance 生成结果，可一键导入去水印流程）
    video_file_name = Column(String(500), nullable=True)
    video_file_key = Column(String(500), nullable=True)
    video_bucket = Column(String(50), nullable=True)
    video_file_size = Column(BigInteger, nullable=True)
    video_status = Column(String(50), nullable=True)  # uploaded / pending / running / completed / failed
    video_error_message = Column(Text, nullable=True)
    video_uploaded_at = Column(DateTime, nullable=True)
    # ── 一键豆包生成（RPA）任务字段 ──
    # 任务状态机：none / need_login(等待扫码) / running(生成中) / awaiting_rewrite(等待确认改写稿)
    #            / completed(已完成) / failed(失败) / cancelled(已取消)
    doubao_status = Column(String(50), nullable=True)
    # 生成时使用的豆包账户类型（free=免费 / pro=包月会员），决定时长上限
    doubao_account_type = Column(String(20), nullable=True)
    # 当前登录的豆包账户昵称（生成时从豆包网页端提取，供前端展示“当前登录豆包账户”）
    doubao_account = Column(String(100), nullable=True)
    # 登录二维码 SVG（need_login 状态时推给前端展示，扫码后自动继续）
    doubao_qrcode = Column(Text, nullable=True)
    # 当前豆包对话窗口截图（running 时由 Celery 任务周期截图，前端可查看制作过程）
    doubao_screenshot = Column(Text, nullable=True)
    doubao_task_id = Column(String(100), nullable=True)
    # 进度/消息（running 时由 Celery 任务实时更新）
    doubao_message = Column(Text, nullable=True)
    # 进度百分比 0~100（由 Celery 任务通过 progress_cb 实时更新，前端展示进度条）
    doubao_progress = Column(Integer, nullable=True, default=0)
    doubao_error_message = Column(Text, nullable=True)
    # 最终通过豆包审核并实际用于生成的提示词（改写确认闭环落库留档）
    doubao_approved_prompt = Column(Text, nullable=True)
    # 每轮改写历史（JSON：[{round, original, rewritten, reason, created_at}]）
    doubao_rewrite_history = Column(JSON, nullable=True)
    # 改写确认回调用的一次性凭证（避免跨用户误确认）
    doubao_confirm_token = Column(String(64), nullable=True)
    # ── Seedance 官方 API 直连出片（火山方舟）任务字段 ──
    # 与豆包 RPA 字段完全独立、互不干扰；成片仍写回 video_* 字段，下游零感知。
    # 任务状态机：none / pending / running / completed / failed / cancelled
    seedance_status = Column(String(50), nullable=True)
    # 火山方舟任务 id（cgt-xxx）
    seedance_task_id = Column(String(100), nullable=True)
    # 实时进度/消息
    seedance_message = Column(Text, nullable=True)
    seedance_error_message = Column(Text, nullable=True)
    # 本次生成分辨率
    seedance_resolution = Column(String(20), nullable=True)
    # 成片来源通道：doubao_rpa / seedance_api（便于追溯）
    gen_channel = Column(String(20), nullable=True)
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
    # 来源提示词记录（短片制作：提示词 → 去水印 → 发布 任务关联）
    prompt_record_id = Column(UUID(as_uuid=True), nullable=True)
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
