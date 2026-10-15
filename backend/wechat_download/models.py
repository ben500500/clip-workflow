"""wechat_download 独立数据模型（4 张独立表）。

对应立项设计文档 §3.1「② 独立数据表」：
- wechat_download_tasks  下载任务表（URL 导入 → 解析 → 拉流 → 入库）
- wechat_source_auths    授权素材表（历史遗留，导入流程已不再强制绑定/校验）
- wechat_parse_records   解析结果表（各解析 provider 产物，可追溯、可重试）
- wechat_dl_prompt_tasks 视频反推提示词任务表（智令 doc/120 异步提交 + doc/119 轮询）

独立表 + 独立 Base，保证可剥离（随包走）；不改动主系统 episodes 核心结构，
仅通过 episodes.source_url 最小粘合字段（迁移脚本另行处理）。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from wechat_download.base import WechatDownloadBase


class WechatDownloadTask(WechatDownloadBase):
    """视频号素材下载任务（URL 导入 → 元宝解析 → 预览兜底 → 拉流入库）。"""

    __tablename__ = "wechat_download_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 操作人（发起导入的用户）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 原始分享链接
    source_url = Column(String(2000), nullable=False)
    # 状态机：pending → parsing → downloading → uploaded → completed / failed
    status = Column(String(50), nullable=False, default="pending", index=True)
    # 当前进度（0-100）
    progress = Column(Float, nullable=False, default=0.0)
    # 进度/阶段消息（供前端 WebSocket 实时展示）
    message = Column(Text, nullable=True)
    # 解析出的视频元数据（标题/封面/播放地址等，JSON）
    video_meta = Column(JSON, nullable=True)
    # 视频源类型标签（仅作审计字段，不再强制）：authorized / self_owned
    source_type = Column(String(50), nullable=False, default="self_owned")
    # 授权来源/备注文本（可选，仅作记录）
    source_authorize = Column(Text, nullable=True)
    # 授权绑定（wechat_source_auths.id，可空，保留兼容旧数据）
    auth_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 拉流成功后落库的 MinIO 文件 key（对应 episodes.source_file_key）
    file_key = Column(String(500), nullable=True)
    # 关联生成的 Episode id（入库后回填）
    episode_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 归属项目 id（入库时可选指定项目）
    project_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 解析/下载错误信息
    error_message = Column(Text, nullable=True)
    # Celery task id（用于取消/追踪）
    celery_task_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<WechatDownloadTask(id={self.id}, status={self.status})>"


class WechatSourceAuth(WechatDownloadBase):
    """授权材料记录（历史遗留表，当前导入流程已不再强制绑定/校验）。

    保留该表仅作历史数据兼容，不再参与导入拦截逻辑。
    """

    __tablename__ = "wechat_source_auths"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 操作人（登记授权材料的用户）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 授权主体（如「XX 版权方」/「XX 授权账号」）
    authorize_owner = Column(String(255), nullable=True)
    # 授权类型：copyright(版权授权) / channel_auth(账号授权) / other
    authorize_type = Column(String(50), nullable=False, default="other")
    # 授权范围描述（授权材料内容/范围）
    authorize_scope = Column(Text, nullable=True)
    # P0：文字备注（双通道之一，本期必填）
    authorize_note = Column(Text, nullable=True)
    # P1：授权书文件（MinIO key，双通道之二，P1 启用）
    authorize_file_key = Column(String(500), nullable=True)
    # 授权有效期（可空=长期）
    expires_at = Column(DateTime, nullable=True)
    # 是否有效（失效后关联链接拒绝导入）
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<WechatSourceAuth(id={self.id}, owner={self.authorize_owner})>"


# 反推提示词任务状态（与智令 doc/119 的 schedule 归一化后的本系统状态）
PT_PROCESSING = "processing"
PT_SUCCESS = "success"
PT_FAILED = "failed"


class WechatDlPromptTask(WechatDownloadBase):
    """视频反推提示词任务（智令 doc/120 提交 + doc/119 轮询结果）。

    链路：POST /api/video-inference/parse-video-url-time 拿到 provider_task_id，
    再按 3~5s 轮询 /api/video-inference/task-status 直至终态。
    计费约 0.00054 元/秒（按 max_duration 上限计），因此 max_duration 落库可追溯。
    """

    __tablename__ = "wechat_dl_prompt_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 发起人（列表可见口径与 wechat-dl 下载任务保持一致）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 用户提交的原始视频链接（分享链接或视频直链）
    source_url = Column(String(1000), nullable=False)
    # 智令侧任务 id（提交接口返回的 data 字段）
    provider_task_id = Column(String(100), nullable=True, index=True)
    # 状态：processing / success / failed
    status = Column(String(20), nullable=False, default=PT_PROCESSING, index=True)
    # 提示词正文（markdown，SUCCESS 时写入）
    content = Column(Text, nullable=True)
    # 失败原因（外部接口业务异常 / 网络错误，截断 500 字符）
    error = Column(String(500), nullable=True)
    # 计时上限（秒，默认 600，最大 600）：决定计费，落库便于对账
    max_duration = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<WechatDlPromptTask(id={self.id}, status={self.status})>"


class WechatParseRecord(WechatDownloadBase):
    """解析结果记录（元宝 / 预览层解析产物，可追溯、可重试）。"""

    __tablename__ = "wechat_parse_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("wechat_download_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    # 解析通道：yuanbao(元宝主链路) / preview(预览层兜底)
    channel = Column(String(50), nullable=False)
    # 请求的分享链接
    source_url = Column(String(2000), nullable=False)
    # 解析结果状态：success / failed
    status = Column(String(50), nullable=False)
    # 返回的播放地址（finder.video.qq.com 直链/分片入口）
    play_url = Column(String(2000), nullable=True)
    # 解析出的元数据（标题/封面/时长/分段等，JSON）
    result_meta = Column(JSON, nullable=True)
    # 原始响应（脱敏后，用于排障，可选）
    raw = Column(Text, nullable=True)
    # 错误信息（失败时）
    error_message = Column(Text, nullable=True)
    # 拉流耗时/状态
    download_bytes = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<WechatParseRecord(id={self.id}, channel={self.channel}, status={self.status})>"
