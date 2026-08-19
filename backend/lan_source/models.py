"""lan_source 独立数据模型（1 张独立表）。

对应立项设计：`lan_source_imports` 导入任务表（剧目 → 集数 → 下载 → 入库 审计）。

独立表 + 独立 Base，保证可剥离（随包走）；不改动主系统 episodes 核心结构，
仅通过 episodes.source_url（来源直链）与 episodes.drama_id（归属剧目）最小粘合，
迁移脚本另行处理。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from lan_source.base import LanSourceBase


class LanSourceImport(LanSourceBase):
    """局域网剧集导入任务（剧目 → 逐集下载 → 入库 全流程审计）。"""

    __tablename__ = "lan_source_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 操作人（发起导入的用户）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 剧目名（去重核心，导入后落在 dramas.name）
    drama_name = Column(String(200), nullable=False, index=True)
    # 关联剧目 id（导入后回填 dramas.id）
    drama_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 归属切片项目 id（导入时指定或自动创建）
    project_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # 状态机：pending → discovering → downloading → importing → completed / failed
    status = Column(String(50), nullable=False, default="pending", index=True)
    # 当前进度（0-100）
    progress = Column(Float, nullable=False, default=0.0)
    # 进度/阶段消息（供前端实时展示）
    message = Column(Text, nullable=True)
    # 期望导入集数（可选；为空=整剧）
    total_episodes = Column(Integer, nullable=True)
    # 已成功入库集数
    imported_count = Column(Integer, nullable=False, default=0)
    # 失败集数
    failed_count = Column(Integer, nullable=False, default=0)
    # 每集明细：[{episode, title, url, status, episode_id, error, file_key}]
    episode_items = Column(JSON, nullable=True)
    # 错误信息
    error_message = Column(Text, nullable=True)
    # Celery task id（用于取消/追踪）
    celery_task_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<LanSourceImport(id={self.id}, drama={self.drama_name}, status={self.status})>"
