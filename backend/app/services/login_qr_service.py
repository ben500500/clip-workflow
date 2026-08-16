"""登录态自服务扫码服务（方案 v3.1：主题1 / 4.1 登录态生命周期）。

实现「运营者登录态自服务上架」P0 项的核心后端能力：
- CDP 从对应 profile 抓取真实登录二维码 → Fernet(AES-256) 加密 → 存 MinIO，
  生成带 operator_id、**单次使用、TTL 90s** 的领取链接（4.1 步骤②）。
- Lua 原子领取，防并发抢兑/重放。
- 扫码结果回调：operator 微信确认后置心跳 ready（4.1 步骤③）。
- 登录态心跳检查（30min 探创作中心），失效仅置 NEED_LOGIN 进独立扫码队列，
  **不阻塞**其他 operator（4.1 步骤④）；每日 ≥1 次静默续活（步骤⑤）。

前置：QR 渲染 Spike（R7）验证 headless Chromium 中微信登录二维码渲染可行性；
失败则退化「本机浏览器扫码 + cookie 注入回传」方案（本模块保留 fallback 入口）。
"""

import json
import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from app.auth import encrypt_cookie
from app.config import settings

logger = logging.getLogger(__name__)

# Redis key 前缀
CLAIM_PREFIX = "pub:qr_claim:"        # string(json)：<claim_token> -> 领取凭据（单次, TTL 90s）
QR_STATE_PREFIX = "pub:qr_state:"     # hash：<account_id> -> 扫码状态机

# 领取链接 TTL（方案 4.1 步骤②：TTL 90s）
CLAIM_TTL = 90
# 登录态心跳窗口（方案 4.1 步骤④：30min 探创作中心）
LOGIN_HEARTBEAT_TTL = 1800

# MinIO bucket（QR PNG 加密存储）
QR_BUCKET = "login-qr"


# Lua 原子领取：校验存在/未过期 → 删除（单次消费）→ 返回凭据（防并发抢兑/重放）
CLAIM_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then return nil end
local data = cjson.decode(raw)
if tonumber(data.exp) < tonumber(ARGV[1]) then
    redis.call('DEL', KEYS[1])
    return nil
end
redis.call('DEL', KEYS[1])
return raw
"""


async def _redis() -> aioredis.Redis:
    """获取共享 Redis 连接（复用 redis_stream 连接池）。"""
    from app.services.redis_stream import get_redis
    return await get_redis()


async def issue_claim(account_id, operator_id, qr_key: str, ttl: int = CLAIM_TTL) -> str:
    """签发单次领取 token 并存 Redis（TTL 90s）。返回 token。"""
    token = secrets.token_urlsafe(32)
    payload = {
        "token": token,
        "account_id": str(account_id),
        "operator_id": str(operator_id),
        "qr_key": qr_key,
        "exp": int(time.time()) + ttl,
        "issued_at": int(time.time()),
    }
    r = await _redis()
    await r.setex(f"{CLAIM_PREFIX}{token}", ttl, json.dumps(payload))
    return token


async def verify_claim_token(token: str) -> Optional[dict]:
    """原子领取：校验 token 有效（未过期）并单次消费，返回凭据（防重放）。"""
    r = await _redis()
    raw = await r.eval(CLAIM_LUA, 1, f"{CLAIM_PREFIX}{token}", int(time.time()))
    if not raw:
        return None
    return json.loads(raw)


async def capture_login_qr(account_id, port: int, profile_dir: Optional[str] = None,
                           host: Optional[str] = None) -> Optional[bytes]:
    """QR Spike（R7）：通过 CDP 从 profile 浏览器抓取登录页二维码 PNG。

    通过 playwright 连到目标 profile 的调试口，导航到视频号创作中心，
    定位登录二维码元素并截图返回 PNG bytes。
    失败（页面无二维码 / 渲染依赖 GPU / 连接失败）时返回 None，由调用方退化。

    注意：本函数需在已安装 playwright 且能访问 127.0.0.1:<port> 的环境执行
    （rpa_worker / backend 均可），供 QR Spike 验证与扫码申请端点调用。
    """
    host = host or "127.0.0.1"
    try:
        from playwright.async_api import async_playwright
    except Exception as e:  # pragma: no cover
        logger.warning("playwright 未安装，无法抽 QR：%s", e)
        return None

    # 创作中心登录页（视频号创作者平台）
    CREATOR_LOGIN = "https://channels.weixin.qq.com/"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://{host}:{port}")
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()
            await page.goto(CREATOR_LOGIN, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            # 定位二维码：常见选择器（微信登录二维码元素），集中管理可版本化（R18）
            qr_selectors = [
                "img.qrcode",
                "canvas",
                "[class*='qrcode'] img",
                "[class*='login'] img",
                "[class*='qrcode']",
            ]
            qr_img = None
            for sel in qr_selectors:
                el = await page.query_selector(sel)
                if el:
                    try:
                        qr_img = await el.screenshot()
                        if qr_img and len(qr_img) > 500:
                            break
                        qr_img = None
                    except Exception:
                        qr_img = None
            await page.close()
            if not qr_img:
                logger.warning("[qr_spike] 未在 profile(%s) 页面定位到二维码元素", account_id)
                return None
            logger.info("[qr_spike] profile(%s) 成功抽取登录二维码 %d bytes", account_id, len(qr_img))
            return qr_img
    except Exception as e:
        logger.warning("[qr_spike] profile(%s) 抽 QR 失败：%s", account_id, e)
        return None


async def store_qr(account_id, png_bytes: bytes) -> Optional[str]:
    """Fernet(AES-256) 加密 QR PNG 并存入 MinIO，返回 object key。"""
    from app.services.minio_service import upload_file

    if not png_bytes:
        return None
    try:
        # Fernet 加密二进制
        cipher = encrypt_cookie_bytes(png_bytes)
    except Exception as e:
        logger.error("QR PNG 加密失败：%s", e)
        return None
    key = f"qr/{account_id}/{uuid.uuid4().hex}.png.enc"
    ok = await upload_file(QR_BUCKET, key, cipher, content_type="application/octet-stream")
    if not ok:
        return None
    return key


def encrypt_cookie_bytes(data: bytes) -> bytes:
    """Fernet(AES-256) 加密 bytes（复用 cookie 加密密钥，与登录态同源安全）。"""
    from cryptography.fernet import Fernet
    from app.auth import _fernet_key_from_secret
    secret = settings.COOKIE_ENCRYPT_KEY or settings.JWT_SECRET
    f = Fernet(_fernet_key_from_secret(secret))
    return f.encrypt(data)


def decrypt_cookie_bytes(data: bytes) -> bytes:
    """解密 Fernet 加密 bytes（QR 领取时回显/前端扫码用）。"""
    from cryptography.fernet import Fernet
    from app.auth import _fernet_key_from_secret
    secret = settings.COOKIE_ENCRYPT_KEY or settings.JWT_SECRET
    f = Fernet(_fernet_key_from_secret(secret))
    return f.decrypt(data)


async def get_qr_presigned_url(qr_key: str, expires: int = 300) -> Optional[str]:
    """生成 QR PNG 的临时访问链接（MinIO presigned，TTL 短，配合 90s 领取窗口）。"""
    from app.services.minio_service import get_presigned_url
    return await get_presigned_url(QR_BUCKET, qr_key, expires_seconds=expires)


async def set_login_state(account_id, state: str, extra: Optional[dict] = None) -> None:
    """写登录态状态机：logging / ready / need_login / expired（统一小写枚举）。

    失效仅置 NEED_LOGIN（进独立扫码队列），不阻塞其他 operator（主题1 ④）。
    """
    r = await _redis()
    key = f"{QR_STATE_PREFIX}{account_id}"
    mapping = {"state": state, "updated_at": str(int(time.time()))}
    if extra:
        mapping.update({k: str(v) for k, v in extra.items()})
    await r.hset(key, mapping=mapping)
    await r.expire(key, LOGIN_HEARTBEAT_TTL * 3)  # 状态保留 90min


async def get_login_state(account_id) -> Optional[dict]:
    r = await _redis()
    raw = await r.hgetall(f"{QR_STATE_PREFIX}{account_id}")
    return raw or None


async def check_login_status_via_cdp(account_id, port: int, host: Optional[str] = None) -> str:
    """30min 登录态心跳：通过 CDP 访问创作中心检测是否仍登录。

    返回 "valid" / "need_login" / "error"（连接失败视为需人工复核，不误判 valid）。
    检测逻辑：访问创作中心首页，若出现登录引导/二维码元素则判定失效；
    否则视为已登录（配合关键 cookie 有效性检查，见 publish_service._need_login）。
    """
    host = host or "127.0.0.1"
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://{host}:{port}")
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()
            await page.goto("https://channels.weixin.qq.com/", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            login_selectors = [
                "img.qrcode", "canvas",
                "[class*='login']", "[class*='qrcode']", "[class*='login-guide']",
            ]
            need_login = False
            for sel in login_selectors:
                el = await page.query_selector(sel)
                if el:
                    need_login = True
                    break
            await page.close()
            return "need_login" if need_login else "valid"
    except Exception as e:
        logger.warning("[login_heartbeat] profile(%s) 心跳检查失败：%s", account_id, e)
        return "error"


async def silent_keepalive(account_id, port: int, host: Optional[str] = None) -> bool:
    """每日 ≥1 次静默访问续活（主题1 ⑤）：访问创作中心，维持登录态不被后台回收。"""
    host = host or "127.0.0.1"
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://{host}:{port}")
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()
            await page.goto("https://channels.weixin.qq.com/post/create",
                            wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            await page.close()
            return True
    except Exception as e:
        logger.warning("[keepalive] profile(%s) 静默续活失败：%s", account_id, e)
        return False
