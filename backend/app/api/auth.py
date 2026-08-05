"""认证与用户管理路由."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    get_role_menus,
    require_roles,
    verify_password,
)
from app.database import get_db
from app.models.models import ROLE_DISPLAY_NAMES, User, UserRole

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# ──────────────────────────────────────────────
# Pydantic 请求/响应模型
# ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


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

# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """用户名密码登录，返回 JWT token 和用户信息."""
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该用户已被禁用",
        )

    token = create_access_token({"sub": str(user.id)})
    return LoginResponse(
        access_token=token,
        user=_user_to_response(user),
    )


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

    user.role = req.role
    await db.flush()
    await db.refresh(user)
    return _user_to_response(user)