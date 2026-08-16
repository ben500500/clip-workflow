"""用户/认证域 ORM 模型。

从原「上帝类」models.py 按业务域拆分而来（Phase 1 上帝类拆分）。
包含：用户角色枚举、数据隔离辅助函数、User / UserSession / UserPreference。
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    JSON,
    ForeignKey,
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


# 各角色默认数据可见范围（数据隔离，二期方案）
# - admin/material/publisher：默认可见全部素材
# - operator：默认仅可见自己账号创建的素材，管理员可通过「权限编辑」授予全部范围
DEFAULT_DATA_SCOPE: dict[UserRole, str] = {
    UserRole.admin: "all",
    UserRole.material: "all",
    UserRole.publisher: "all",
    UserRole.operator: "own",
}


def default_data_scope_for_role(role: str) -> str:
    """根据角色名返回默认数据范围（all=全部素材，own=仅自己创建）."""
    try:
        return DEFAULT_DATA_SCOPE.get(UserRole(role), "own")
    except ValueError:
        return "own"


def user_can_access_all_materials(user: "User") -> bool:
    """判断用户是否可访问全部素材（数据隔离）. """
    if user.role in (UserRole.admin.value, UserRole.material.value, UserRole.publisher.value):
        return True
    # 运营专员默认仅自己素材，但可通过权限编辑授予 all
    return getattr(user, "data_scope", "own") == "all"


class User(Base):
    """系统用户."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)
    role = Column(String(20), default=UserRole.operator.value, nullable=False)
    # 数据隔离：all=可见全部素材；own=仅可见自己创建的素材
    # 默认由角色决定（admin/material/publisher=all，operator=own），管理员可通过权限编辑授予
    data_scope = Column(String(20), default="own", nullable=False)
    # 豆包账户类型（短片制作「一键豆包生成」）：free=免费（时长上限 10s）；pro=包月会员（时长上限 30s）
    # 用户手动选择后即作为当前登录用户的默认值
    doubao_account_type = Column(String(20), default="free", nullable=False)
    # 提示词生成默认时长（秒）：用户选择时长后即作为当前登录用户的默认值（10/15/20/25/30 或自定义）
    prompt_default_duration = Column(Integer, nullable=True)
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


class UserPreference(Base):
    """用户个人偏好设置：按用户存储切片等个人配置，跨设备/浏览器持久化。

    每个用户一条记录，slice_config 存整个切片配置 JSON（同前端 SlicePreset 的配置字段）。
    """
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    slice_config = Column(JSON, nullable=True)   # 当前用户的切片配置（JSON，可整体覆盖）
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", backref="preferences")

    def __repr__(self) -> str:
        return f"<UserPreference(id={self.id}, user_id={self.user_id})>"
