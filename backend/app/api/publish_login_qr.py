"""publish API 子域：登录态自服务扫码（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持 `/publish/login/*` 不变。

流程（方案 4.1 步骤②③）：
  admin 触发「申请扫码」→ CDP 从 profile 抽真实登录 QR PNG → Fernet 加密存 MinIO
  → 签发带 operator_id、单次、TTL 90s 的领取 token；
  operator 用领取 token 取二维码链接 → 微信扫码确认 → 回调置心跳 ready。
前置：QR 渲染 Spike（R7）验证 headless Chromium 二维码渲染可行性。
"""
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import PublishProfile, User
from app.api.publish_common import _require_admin

router = APIRouter()

# 图片代理 router：不带全局鉴权依赖。qr_key 为随机 UUID 能力令牌，
# 安全模型与原 MinIO presigned URL 等价（只有拿到 claim 链接的 operator 才知道路径），
# 且前端 <img> 无法携带 JWT，必须同源免鉴权返回 PNG。
img_router = APIRouter()


class LoginQrApply(BaseModel):
    """申请登录扫码请求体。"""
    account_id: str


class LoginScanCallback(BaseModel):
    """扫码结果回调请求体（operator 微信确认后调用）。"""
    account_id: str
    operator_id: Optional[str] = None
    scanner_name: Optional[str] = None
    result: Optional[str] = "success"   # success / failed / expired
    message: Optional[str] = None


async def _resolve_profile_port(db: AsyncSession, account_id) -> tuple:
    """解析账号对应的 profile 端口（优先路由表，回退 PublishProfile.chrome_debug_port）。

    返回 (port, host, profile_dir, operator_id) 元组。
    """
    from app.services import multi_operator
    from app.models.models import VideoAccount

    port = await multi_operator.resolve_port(account_id)
    operator_id = None
    host = settings.CHROME_DEBUG_HOST  # 默认 cdp 探活 host（跨容器时由配置覆盖）
    profile_dir = None

    # 从 VideoAccount 找关联 profile
    acc = await db.scalar(select(VideoAccount).where(VideoAccount.id == uuid.UUID(account_id)))
    if acc:
        operator_id = acc.operator_id
    if port is None:
        # 回退：读 PublishProfile.chrome_debug_port（零侵入旧链路）
        route = await multi_operator.get_route(account_id)
        if route:
            port = int(route.get("port") or 0)
            profile_dir = route.get("profile_dir")
            host = route.get("chrome_debug_host") or host
            operator_id = route.get("operator_id") or operator_id
        if not port:
            prof = await db.scalar(
                select(PublishProfile).where(PublishProfile.operator_id == operator_id)
                if operator_id else select(PublishProfile).limit(1)
            )
            if prof:
                port = prof.chrome_debug_port
                host = prof.chrome_debug_host or host
    return port, host, profile_dir, operator_id


@router.post("/publish/login/qr", response_model=dict, status_code=201)
async def apply_login_qr(
    body: LoginQrApply,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """申请登录扫码（admin）：CDP 抽 QR → 加密存 MinIO → 签发单次 TTL 90s 领取 token。

    前置 QR 渲染 Spike（R7）；若抽 QR 失败返回 502，前端可退化「本机扫码+cookie 注入」。
    """
    _require_admin(current_user)
    from app.services import login_qr_service
    from app.services import audit_service

    account_id = body.account_id
    port, host, profile_dir, operator_id = await _resolve_profile_port(db, account_id)
    if not port:
        raise HTTPException(status_code=404, detail="Account profile not found / no debug port")

    # 1. CDP 抽真实登录 QR PNG（R7 Spike 落地验证）
    png = await login_qr_service.capture_login_qr(
        account_id, port=port, profile_dir=profile_dir, host=host
    )
    if not png:
        raise HTTPException(
            status_code=502,
            detail="QR capture failed: 未能从 Chromium 定位登录二维码（QR Spike 未通过或微信改版），请退化为「本机浏览器扫码 + cookie 注入」",
        )

    # 2. Fernet 加密存 MinIO
    qr_key = await login_qr_service.store_qr(account_id, png)
    if not qr_key:
        raise HTTPException(status_code=502, detail="QR 加密存储到 MinIO 失败")

    # 3. 签发单次领取 token（TTL 90s）
    token = await login_qr_service.issue_claim(account_id, operator_id or current_user.id, qr_key)

    # 4. 写 login_audit（claim）
    await audit_service.log_login_audit(
        account_id=uuid.UUID(account_id), operator_id=operator_id,
        actor_id=current_user.id, qr_key=qr_key, claim_token=token,
        ttl_seconds=90, action="claim", source_ip=current_user.last_login_ip if hasattr(current_user, "last_login_ip") else None,
        result="issued",
    )


    await login_qr_service.set_login_state(account_id, "logging")

    return {
        "claim_token": token,
        "expires_in": 90,
        "qr_key": qr_key,
        "account_id": account_id,
        "operator_id": str(operator_id) if operator_id else None,
        "message": "登录二维码已加密入库，请在 90s 内领取并扫码",
    }


@router.get("/publish/login/qr/claim/{token}", response_model=dict)
async def claim_login_qr(
    token: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """领取登录二维码（operator 用单次 token，TTL 90s）。返回同源图片代理链接。"""
    from app.services import login_qr_service

    claim = await login_qr_service.verify_claim_token(token)
    if not claim:
        raise HTTPException(status_code=410, detail="领取链接已失效/已使用（TTL 90s 单次）")
    # 返回同源代理路径，避免浏览器直连内网 MinIO presigned（图裂）
    qr_url = f"/api/publish/login/qr/image/{claim['qr_key']}"
    return {
        "qr_url": qr_url,
        "account_id": claim["account_id"],
        "operator_id": claim["operator_id"],
        "expires_in": 60,
    }


@img_router.get("/publish/login/qr/image/{qr_key:path}")
async def serve_login_qr_image(qr_key: str):
    """同源返回登录二维码 PNG（解密 MinIO 加密文件）。

    前端 <img src="/api/publish/login/qr/image/{qr_key}"> 同源加载，
    避免直连内网 MinIO presigned 地址导致图裂。qr_key 为随机 UUID 路径
    （实际形如 qr/{account_id}/{uuid}.png.enc，含斜杠，故用 :path 转换器），
    内容经 Fernet 加密（密钥仅后端持有），安全性与 presigned 同级。
    """
    from app.services import login_qr_service
    from app.services.minio_service import download_file

    enc = await download_file(login_qr_service.QR_BUCKET, qr_key)
    if not enc:
        raise HTTPException(status_code=404, detail="QR not found")
    try:
        png = login_qr_service.decrypt_cookie_bytes(enc)
    except Exception:
        raise HTTPException(status_code=500, detail="QR decrypt failed")
    return Response(content=png, media_type="image/png")


@router.post("/publish/login/scan/callback", response_model=dict)
async def login_scan_callback(
    body: LoginScanCallback,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """扫码结果回调（operator 微信确认后调用）：置登录态心跳 ready / need_login。"""
    from app.services import login_qr_service
    from app.services import audit_service

    account_id = body.account_id
    success = body.result != "failed"
    if success:
        await login_qr_service.set_login_state(account_id, "ready")
    else:
        await login_qr_service.set_login_state(account_id, "need_login", {"reason": body.message or "scan_failed"})

    await audit_service.log_login_audit(
        account_id=uuid.UUID(account_id), operator_id=body.operator_id,
        actor_id=current_user.id if current_user else None,
        action="scanned", scanner_name=body.scanner_name,
        source_ip=current_user.last_login_ip if (current_user and hasattr(current_user, "last_login_ip")) else None,
        result=body.result,
    )
    return {"account_id": account_id, "state": "ready" if success else "need_login"}


@router.get("/publish/login/status/{account_id}", response_model=dict)
async def get_login_status(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """查询登录态（30min 心跳级别状态机：logging / ready / need_login / expired）。"""
    from app.services import login_qr_service

    state = await login_qr_service.get_login_state(account_id)
    if not state:
        return {"account_id": account_id, "state": "unknown"}
    return {"account_id": account_id, **state}


@router.post("/publish/login/heartbeat/{account_id}", response_model=dict)
async def login_heartbeat(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """登录态心跳检查（30min 探创作中心，对应 4.1 步骤④）。

    失效仅置 NEED_LOGIN 进独立扫码队列，不阻塞其他 operator。
    """
    from app.services import login_qr_service
    from app.services import audit_service

    port, host, profile_dir, operator_id = await _resolve_profile_port(db, account_id)
    if not port:
        raise HTTPException(status_code=404, detail="Account profile not found / no debug port")

    status = await login_qr_service.check_login_status_via_cdp(account_id, port, host)
    cur = await login_qr_service.get_login_state(account_id)
    cur_state = (cur or {}).get("state")
    if status == "valid":
        await login_qr_service.set_login_state(account_id, "ready")
        await audit_service.log_cookie_access(
            account_id=uuid.UUID(account_id), operator_id=operator_id,
            actor_id=current_user.id if current_user else None,
            purpose="login_check",
            ip_address=current_user.last_login_ip if (current_user and hasattr(current_user, "last_login_ip")) else None,
        )
    elif status == "need_login":
        # 仅当原本已 ready（已登录会话 30min 心跳失效）才降级 need_login + 告警；
        # logging（等待用户扫码中）检测到登录页二维码属正常，不落库不告警，
        # 避免前端轮询心跳时刷风险日志、覆盖等待扫码状态。
        if cur_state == "ready":
            await login_qr_service.set_login_state(account_id, "need_login", {"reason": "30min 心跳：登录态失效"})
            await audit_service.log_risk_event(
                account_id=uuid.UUID(account_id), operator_id=operator_id,
                actor_id=current_user.id if current_user else None,
                risk_type="login_restricted", level="warning",
                message="登录态心跳检查失效（30min）",
                disposition="re_login",
            )
    # status == "error"（连接失败）不误判 valid，保持现状
    return {"account_id": account_id, "status": status}
