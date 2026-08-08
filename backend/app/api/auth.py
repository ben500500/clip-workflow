"""认证与用户管理路由.

二期安全认证体系：
- 登录返回 access_token + refresh_token（refresh_token 通过 HttpOnly Cookie 下发）
- POST /auth/refresh 使用 refresh_token 无感刷新 access_token
- POST /auth/logout 吊销会话（refresh_token 黑名单）
- RBAC 三级权限：admin / operator / publisher / material
- 审计日志：登录/登出/角色变更等关键操作落库
"""

from typing import Annotated

import uuid
from datetime import datetime as _dt, timezone as _tz
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_user_session,
    decode_token,
    get_current_user,
    get_password_hash,
    get_role_menus,
    require_roles,
    verify_password,
)
from app.database import get_db
from app.models.models import ROLE_DISPLAY_NAMES, AuditLog, User, UserSession, UserRole

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# refresh_token 的 HttpOnly Cookie 名称
REFRESH_COOKIE_NAME = "refresh_token"

# ──────────────────────────────────────────────
# Pydantic 请求/响应模型
# ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: "UserResponse"


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogoutResponse(BaseModel):
    ok: bool = True
    message: str = "已退出登录"


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str | None
    role: str
    role_display: str
    is_active: bool
    menus: list[str] = []
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str | None = None
    role: str = UserRole.operator.value


class UpdateRoleRequest(BaseModel):
    role: str


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None
    old_password: str | None = None
    new_password: str | None = None


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


def _user_to_response(user: User) -> UserResponse:
    """将 User ORM 对象转为响应模型."""
    return UserResponse(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        role_display=ROLE_DISPLAY_NAMES.get(UserRole(user.role), user.role),
        is_active=user.is_active,
        menus=get_role_menus(user.role),
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


def _set_refresh_cookie(response: Response, token: str | None):
    """将 refresh_token 写入 HttpOnly Cookie（支持清除）."""
    if token:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=token,
            max_age=7 * 24 * 3600,  # 7 天
            httponly=True,
            secure=False,  # 生产环境建议通过 Nginx 启用 HTTPS 后改为 True
            samesite="lax",
            path="/api/auth",
        )
    else:
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth")


async def _write_audit(
    db: AsyncSession,
    action: str,
    operator: User | None,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
):
    """写入审计日志."""
    try:
        log = AuditLog(
            operator_id=operator.id if operator else None,
            operator_name=operator.username if operator else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            ip_address=request.client.host if request and request.client else None,
        )
        db.add(log)
        await db.flush()
    except Exception:
        # 审计日志失败不应影响主流程
        pass


async def _revoke_session_by_refresh_token(db: AsyncSession, refresh_token: str):
    """根据 refresh_token 吊销对应会话."""
    from app.auth import _hash_token

    token_hash = _hash_token(refresh_token)
    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session and not session.is_revoked:
        session.is_revoked = True
        session.revoked_at = _dt.utcnow()
        await db.flush()
    return session


# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """用户名密码登录，返回 access_token 并下发 refresh_token Cookie."""
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.password_hash):
        await _write_audit(db, "auth.login.failed", None, "user", req.username, request=request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该用户已被禁用",
        )

    # 双 Token：access_token 短期，refresh_token 长期落库
    jti = str(uuid.uuid4())
    access_token = create_access_token({"sub": str(user.id)}, jti=jti)
    session = await create_user_session(db, user, request, access_jti=jti)
    refresh_token = getattr(session, "_plain_refresh_token", None)

    _set_refresh_cookie(response, refresh_token)
    await _write_audit(db, "auth.login", user, "user", str(user.id), request=request)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_to_response(user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """使用 refresh_token 无感刷新 access_token.

    refresh_token 从 HttpOnly Cookie 读取（或从 JSON body 兜底），
    校验通过后吊销旧 refresh_token 并签发新的 refresh_token（轮换）。
    """

    # 优先从 Cookie 读取
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        try:
            body = await request.json()
            refresh_token = body.get("refresh_token")
        except Exception:
            refresh_token = None

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 refresh_token",
        )

    # 校验 refresh_token 有效性
    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="无效的 refresh_token")

    from app.auth import _hash_token
    token_hash = _hash_token(refresh_token)
    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session is None or session.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token 已失效，请重新登录",
        )
    # expires_at 列是 TIMESTAMPTZ，asyncpg 读出为 aware UTC；
    # 本地 _dt.utcnow() 为 naive，直接比较会抛 TypeError（offset-naive vs aware）。
    # 统一转 aware UTC 再比较。
    if session.expires_at and session.expires_at < _dt.utcnow().replace(tzinfo=_tz.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
        )

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
        )

    # 会话复用（不吊销旧会话、不轮换 refresh_token）：
    # 无感刷新本质是“用同一个长期 refresh_token 换取新的 access_token”。
    # 若每次刷新都吊销旧会话并轮换 refresh_token，会带来两个“被踢”问题：
    #   1) 并发刷新竞态：两个请求同时携带同一 refresh_token，前一个吊销会话后，
    #      后一个必然 401 → 前端清 token 跳登录页；
    #   2) 多标签页/后台轮询（切片、去水印、Worker 状态等每 3~15s 拉一次）：
    #      任一标签页刷新成功后，其余标签页持有的旧 refresh_token 立即失效 → 被踢。
    # 因此这里保持会话不变，仅签发新的 access_token；会话到期由 expires_at 统一处理。
    # （需要主动登出时仍可通过 /auth/logout 吊销会话，安全语义不受影响。）
    #
    # 会话的 access_token_jti 全程固定（首次登录时生成）：刷新时复用同一 jti，
    # 保证该会话签发过的所有 access_token 都能通过 get_current_user 的会话级校验，
    # 已下发的旧 access_token 也不会被后续刷新“作废”（仍有效至 30 分钟过期）。
    session_jti = session.access_token_jti or str(uuid.uuid4())
    if not session.access_token_jti:
        session.access_token_jti = session_jti  # 兼容旧数据：补记会话 jti
        await db.flush()

    new_access = create_access_token({"sub": str(user.id)}, jti=session_jti)

    # 刷新后保持 refresh Cookie 不变（无需重新下发）；
    # 不重新下发即可避免 set-cookie 覆盖，多标签页共用同一会话互不影响。
    return RefreshResponse(access_token=new_access)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """退出登录：吊销 refresh_token 会话（Token 黑名单）."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        await _revoke_session_by_refresh_token(db, refresh_token)
    _set_refresh_cookie(response, None)
    await _write_audit(db, "auth.logout", current_user, "user", str(current_user.id), request=request)
    return LogoutResponse()


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """获取当前登录用户的信息."""
    return _user_to_response(current_user)


@router.post("/register", response_model=UserResponse)
async def register(
    req: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    """注册新用户（仅管理员可调用）."""
    # 校验角色值
    try:
        UserRole(req.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的角色: {req.role}，有效值为: {[r.value for r in UserRole]}",
        )

    # 检查用户名是否已存在
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    user = User(
        username=req.username,
        password_hash=get_password_hash(req.password),
        display_name=req.display_name or req.username,
        role=req.role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await _write_audit(
        db, "user.create", current_user, "user", str(user.id),
        after={"username": user.username, "role": user.role},
    )
    await db.refresh(user)
    return _user_to_response(user)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    """获取用户列表（仅管理员可调用）."""
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [_user_to_response(u) for u in users]


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    req: UpdateRoleRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    """修改用户角色（仅管理员可调用）."""
    # 校验角色值
    try:
        UserRole(req.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的角色: {req.role}，有效值为: {[r.value for r in UserRole]}",
        )

    from uuid import UUID
    result = await db.execute(
        select(User).where(User.id == UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    before = {"role": user.role}
    user.role = req.role
    await db.flush()
    await _write_audit(
        db, "user.role.update", current_user, "user", str(user.id),
        before=before, after={"role": user.role},
    )
    await db.refresh(user)
    return _user_to_response(user)


@router.put("/users/{user_id}/toggle", response_model=UserResponse)
async def toggle_user_active(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    """启用/停用用户（仅管理员可调用）."""
    from uuid import UUID
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    if current_user.id == uid:
        raise HTTPException(status_code=400, detail="不能停用当前登录用户")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    before = {"is_active": user.is_active}
    user.is_active = not user.is_active
    await db.flush()
    await _write_audit(
        db, "user.active.toggle", current_user, "user", str(user.id),
        before=before, after={"is_active": user.is_active},
    )
    await db.refresh(user)
    return _user_to_response(user)


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    req: UpdateProfileRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """修改个人资料（昵称 / 密码）."""
    if req.display_name is not None:
        current_user.display_name = req.display_name

    if req.old_password and req.new_password:
        if not verify_password(req.old_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="原密码错误")
        if len(req.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")
        current_user.password_hash = get_password_hash(req.new_password)

    await db.flush()
    await _write_audit(db, "user.profile.update", current_user, "user", str(current_user.id))
    await db.refresh(current_user)
    return _user_to_response(current_user)
