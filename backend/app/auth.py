"""JWT 认证与权限依赖模块."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import User, UserRole

security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ──────────────────────────────────────────────
# 密码工具
# ──────────────────────────────────────────────


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希值是否匹配."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """对明文密码进行 bcrypt 哈希."""
    return pwd_context.hash(password)


# ──────────────────────────────────────────────
# JWT 工具
# ──────────────────────────────────────────────


def create_access_token(data: dict) -> str:
    """生成 JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


# ──────────────────────────────────────────────
# 依赖注入
# ──────────────────────────────────────────────


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """从 Authorization header 解析 JWT 并返回当前用户对象."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 token",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
        )
    return user


def require_roles(*roles: UserRole):
    """返回一个依赖，检查当前用户是否拥有指定的任一角色.

    用法::

        @router.get("/admin-only")
        async def admin_endpoint(
            current_user: User = Depends(require_roles(UserRole.admin)),
        ):
            ...

        @router.get("/multi-role")
        async def multi_endpoint(
            current_user: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
        ):
            ...
    """

    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in {r.value for r in roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user

    return role_checker


# ──────────────────────────────────────────────
# 菜单权限映射
# ──────────────────────────────────────────────

# 每个角色可访问的菜单标识符列表
# 实际前端可据此判断侧边栏显示哪些菜单项
ROLE_MENUS: dict[UserRole, list[str]] = {
    UserRole.admin: [
        "dashboard",
        "project-management",
        "publish-management",
        "data-board",
        "data-board:overview",
        "data-board:content-analysis",
        "data-board:data-entry",
        "data-board:video-metrics",
        "data-board:ad-metrics",
        "data-board:mini-program",
        "data-board:ecosystem",
        "system-config",
        "user-management",
    ],
    UserRole.operator: [
        "dashboard",
        "project-management",
        "data-board",
        "data-board:overview",
        "data-board:content-analysis",
        "data-board:data-entry",
        "data-board:video-metrics",
        "data-board:ad-metrics",
        "data-board:mini-program",
        "data-board:ecosystem",
    ],
    UserRole.publisher: [
        "dashboard",
        "publish-management",
        "data-board",
        "data-board:overview",
        "data-board:content-analysis",
        "data-board:data-entry",
    ],
    UserRole.material: [
        "dashboard",
        "project-management",
    ],
}


def get_role_menus(role: str) -> list[str]:
    """根据角色名获取可访问的菜单列表."""
    try:
        r = UserRole(role)
        return ROLE_MENUS.get(r, [])
    except ValueError:
        return []