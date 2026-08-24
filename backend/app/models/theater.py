"""剧场域 ORM 模型（Theater）。

从需求「剧目直接挂剧场 + 视频号列表页剧场管理」新增：
- `theaters` 剧场主数据（id / name 唯一 / remark / operator_id 号主 / 审计字段）。

剧场是「上架账号」这一业务概念在系统内的实体化（原导入表里的「上架账号」
列如“海漫剧场”本质是剧场名）。归属关系：
- `dramas.theater_id`（FK → theaters）   剧目直接挂剧场（一剧一场，可空）
- `channel_accounts.theater_id`           视频号台账挂剧场（用于视频号列表按剧场筛选）
- `video_accounts.theater_id`             发布账号库挂剧场（与台账口径一致）

沿用既有约定：UUID 主键、created_by=操作人 / operator_id=号主、
RBAC data_scope 过滤、审计可溯源。
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Theater(Base):
    """剧场主数据。

    `name` 为唯一去重核心：导入剧目出现「剧场」列时按名称查找或自动创建。
    """
    __tablename__ = "theaters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 剧场名称（如“海漫剧场”），唯一
    name = Column(String(100), unique=True, nullable=False, index=True)
    # 备注
    remark = Column(String(500), nullable=True)
    # 归属（R17 actor/operator 分离）
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    operator_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 该剧场下的剧目（dramas.theater_id 反查）
    dramas = relationship("Drama", back_populates="theater")

    def __repr__(self) -> str:
        return f"<Theater(id={self.id}, name={self.name})>"
