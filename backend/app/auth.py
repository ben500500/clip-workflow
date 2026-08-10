"""JWT 认证与权限依赖模块.

二期安全认证体系：
- 双 Token 机制：access_token（短期，30 分钟）+ refresh_token（长期，7 天）
- refresh_token 哈希后落库（user_sessions 表），支持主动登出/黑名单
- access_token 携带 jti，配合 UserSession 记录支持会话失效
- RBAC 三级权限：admin / operator / publisher / material
"""

import base64
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Optional

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import User, UserSession, UserRole

security = HTTPBearer(auto_error=False)
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
# JWT 工具（双 Token）
# ──────────────────────────────────────────────


def _create_jwt(payload: dict, expires_delta: timedelta) -> str:
    """通用 JWT 生成."""
    to_encode = payload.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


def create_access_token(data: dict, jti: Optional[str] = None) -> str:
    """生成 access_token（短期）.

    默认有效期 JWT_EXPIRE_MINUTES（30 分钟）；携带 jti 用于会话级失效。
    """
    to_encode = data.copy()
    to_encode["type"] = "access"
    if jti:
        to_encode["jti"] = jti
    return _create_jwt(to_encode, timedelta(minutes=settings.JWT_EXPIRE_MINUTES))


def create_refresh_token(data: dict) -> tuple[str, str, datetime]:
    """生成 refresh_token（长期，7 天）.

    Returns:
        (refresh_token, refresh_token_hash, expires_at)

    注意：refresh_token 必须携带随机 jti，否则同一用户同一秒内并发登录
    会生成完全相同的 JWT（payload 仅 sub/type/iat/exp，iat 秒级精度），
    SHA-256 哈希相同，撞 user_sessions.refresh_token_hash 唯一约束
    导致 500（UNIQUE constraint failed）。
    """
    to_encode = data.copy()
    to_encode["type"] = "refresh"
    # 随机 jti：保证并发登录/刷新产生的 token 唯一（会话可追溯）
    to_encode["jti"] = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    token = _create_jwt(to_encode, timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS))
    return token, _hash_token(token), expires_at


def _hash_token(token: str) -> str:
    """对 refresh_token 做 SHA-256 哈希（不存储明文 token）."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    """解析并校验 JWT，可选校验 token 类型（access/refresh）.

    Raises:
        HTTPException 401 当 token 无效/过期/类型不符
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if expected_type and payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 类型不正确",
        )
    return payload


# ──────────────────────────────────────────────
# 依赖注入
# ──────────────────────────────────────────────


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """从 Authorization header 解析 JWT 并返回当前用户对象.

    同时校验：
    - token 类型必须为 access
    - 若 token 携带 jti，则该 jti 对应的会话必须未被吊销
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_token(token, expected_type="access")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
        )
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
        )

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
        )

    # 会话级黑名单：token 携带 jti 时检查对应会话是否已吊销
    jti = payload.get("jti")
    if jti:
        sess_result = await db.execute(
            select(UserSession).where(UserSession.access_token_jti == jti)
        )
        session = sess_result.scalar_one_or_none()
        if session is None or session.is_revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="会话已失效，请重新登录",
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


async def create_user_session(
    db: AsyncSession,
    user: User,
    request: Request,
    access_jti: Optional[str] = None,
) -> UserSession:
    """创建用户登录会话并落库."""
    refresh_token, refresh_hash, expires_at = create_refresh_token({"sub": str(user.id)})
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        access_token_jti=access_jti,
        user_agent=request.headers.get("user-agent", "")[:500],
        ip_address=request.client.host if request.client else None,
        expires_at=expires_at,
        is_revoked=False,
    )
    db.add(session)
    await db.flush()
    # 通过 attribute 回传明文 refresh_token（仅本次响应使用，不落库）
    session._plain_refresh_token = refresh_token  # type: ignore[attr-defined]
    return session


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


# ──────────────────────────────────────────────
# Cookie AES-256 加密（RPA Cookie 安全存储）
# ──────────────────────────────────────────────


def _fernet_key_from_secret(secret: str) -> bytes:
    """从任意长度 secret 派生 Fernet 密钥（SHA-256 → base64 urlsafe）."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_cookie(plain_text: str) -> str:
    """使用 AES-256（Fernet 包装）加密 Cookie.

    密钥来自 settings.COOKIE_ENCRYPT_KEY（config.py 启动时已固化独立密钥，不再回退 JWT_SECRET）。
    """
    if not plain_text:
        return ""
    secret = settings.COOKIE_ENCRYPT_KEY or settings.JWT_SECRET
    f = Fernet(_fernet_key_from_secret(secret))
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_cookie(cipher_text: str) -> str:
    """解密 Cookie（加密密钥错误/格式非法时抛错，调用方处理）."""
    if not cipher_text:
        return ""
    secret = settings.COOKIE_ENCRYPT_KEY or settings.JWT_SECRET
    f = Fernet(_fernet_key_from_secret(secret))
    return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
