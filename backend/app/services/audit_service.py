"""多运营者发布审计与可观测服务（方案 v3.1，主题 8 / 5.4，P1 问题10）。

提供四类审计日志的写入与查询：
- PublishAudit      发布审计：actor_id(操作人)/operator_id(号主)/account_id/内容哈希/来源/
  action/result/risk_flag，以 request_id(trace_id) 串联审核→确认→发布→风控回执。
- LoginAudit        登录态自服务扫码审计。
- CookieAccessLog   Cookie 访问审计（读时间/者/用途，防越权读取）。
- RiskEvent         风控事件（受限类型/处置，驱动毕业阈值统计）。

写路径同时被 publish API（有 session）与 celery worker（无 session）调用，
故提供「传入 session」与「自建 session」两种入口；查询路径由 API 传入 session。
"""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Optional, Union

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.models import (
    PublishAudit,
    LoginAudit,
    CookieAccessLog,
    RiskEvent,
)

logger = logging.getLogger(__name__)


def gen_trace_id() -> str:
    """生成全链路 trace_id（request_id）。"""
    return f"pub-{uuid.uuid4().hex[:16]}"


def content_hash(text: Optional[str]) -> Optional[str]:
    """对发布内容生成 sha256 前 32 位哈希（溯源用，不落明文）。"""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# ── 风控类型常量（PR②）──
# 收敛 risk_type 取值，避免自由字符串散落；RiskEvent.risk_type 为自由列，
# 新增取值零迁移。供发布失败分类与毕业阈值统计（7 日 ≥2 次）使用。
RISK_TYPE_LOGIN_RESTRICTED = "login_restricted"
RISK_TYPE_PUBLISH_LIMITED = "publish_limited"
RISK_TYPE_CAPTCHA = "captcha"
RISK_TYPE_BAN = "ban"
RISK_TYPE_UPLOAD_LIMITED = "upload_limited"   # 上传被平台拒发（300001/upload_params 类）
RISK_TYPE_ENV_RISK = "env_risk"               # 环境级风控（设备/环境异常）


async def _log_publish_audit(db: AsyncSession, *, task_id=None, account_id=None,
                             operator_id=None, actor_id=None, profile_id=None,
                             content_hash=None, cover_variant=None, copy_template=None,
                             source_ip=None, egress_ip=None, ua_seed=None, port=None,
                             action="publish", result=None, risk_flag=False,
                             risk_note=None, request_id=None) -> None:
    """写入一条发布审计（含 trace_id 兜底生成）。"""
    entry = PublishAudit(
        task_id=task_id,
        account_id=account_id,
        operator_id=operator_id,
        actor_id=actor_id,
        profile_id=profile_id,
        content_hash=content_hash,
        cover_variant=cover_variant,
        copy_template=copy_template,
        source_ip=source_ip,
        egress_ip=egress_ip,
        ua_seed=ua_seed,
        port=port,
        action=action,
        result=result,
        risk_flag=risk_flag,
        risk_note=risk_note,
        request_id=request_id or gen_trace_id(),
    )
    db.add(entry)
    try:
        await db.flush()
    except Exception as e:  # 审计写失败不影响主流程
        logger.warning("publish audit write failed: %s", e)


async def _log_login_audit(db: AsyncSession, *, account_id=None, operator_id=None,
                           actor_id=None, qr_key=None, claim_token=None,
                           ttl_seconds=90, action="claim", scanner_name=None,
                           source_ip=None, result=None, request_id=None) -> None:
    entry = LoginAudit(
        account_id=account_id, operator_id=operator_id, actor_id=actor_id,
        qr_key=qr_key, claim_token=claim_token, ttl_seconds=ttl_seconds,
        action=action, scanner_name=scanner_name, source_ip=source_ip,
        result=result, request_id=request_id or gen_trace_id(),
    )
    db.add(entry)
    try:
        await db.flush()
    except Exception as e:
        logger.warning("login audit write failed: %s", e)


async def _log_cookie_access(db: AsyncSession, *, profile_id=None, account_id=None,
                             actor_id=None, operator_id=None, purpose="publish",
                             ip_address=None, request_id=None) -> None:
    entry = CookieAccessLog(
        profile_id=profile_id, account_id=account_id, actor_id=actor_id,
        operator_id=operator_id, purpose=purpose, ip_address=ip_address,
        request_id=request_id or gen_trace_id(),
    )
    db.add(entry)
    try:
        await db.flush()
    except Exception as e:
        logger.warning("cookie access log write failed: %s", e)


async def _log_risk_event(db: AsyncSession, *, account_id=None, operator_id=None,
                          actor_id=None, risk_type="publish_limited", level="warning",
                          message=None, disposition=None, source_ip=None,
                          request_id=None) -> None:
    entry = RiskEvent(
        account_id=account_id, operator_id=operator_id, actor_id=actor_id,
        risk_type=risk_type, level=level, message=message, disposition=disposition,
        source_ip=source_ip, request_id=request_id or gen_trace_id(),
    )
    db.add(entry)
    try:
        await db.flush()
    except Exception as e:
        logger.warning("risk event write failed: %s", e)


# ── 对外写入口（无 session 时自建，供 celery worker 调用） ──


async def log_publish_audit(**kwargs) -> str:
    """写发布审计，返回 request_id（供调用方贯穿后续步骤）。"""
    async with async_session_factory() as db:
        rid = kwargs.get("request_id") or gen_trace_id()
        kwargs.setdefault("request_id", rid)
        await _log_publish_audit(db, **kwargs)
        await db.commit()
    return kwargs["request_id"]


async def log_login_audit(**kwargs) -> str:
    async with async_session_factory() as db:
        rid = kwargs.get("request_id") or gen_trace_id()
        kwargs.setdefault("request_id", rid)
        await _log_login_audit(db, **kwargs)
        await db.commit()
    return kwargs["request_id"]


async def log_cookie_access(**kwargs) -> str:
    async with async_session_factory() as db:
        rid = kwargs.get("request_id") or gen_trace_id()
        kwargs.setdefault("request_id", rid)
        await _log_cookie_access(db, **kwargs)
        await db.commit()
    return kwargs["request_id"]


async def log_risk_event(**kwargs) -> str:
    async with async_session_factory() as db:
        rid = kwargs.get("request_id") or gen_trace_id()
        kwargs.setdefault("request_id", rid)
        await _log_risk_event(db, **kwargs)
        await db.commit()
    return kwargs["request_id"]


# ── 查询入口（API 传入 session） ──


async def list_publish_audits(db: AsyncSession, *, action: Optional[str] = None,
                              account_id: Optional[str] = None,
                              operator_id: Optional[str] = None,
                              request_id: Optional[str] = None,
                              limit: int = 100) -> list:
    query = select(PublishAudit).order_by(desc(PublishAudit.created_at))
    if action:
        query = query.where(PublishAudit.action == action)
    if account_id:
        query = query.where(PublishAudit.account_id == account_id)
    if operator_id:
        query = query.where(PublishAudit.operator_id == operator_id)
    if request_id:
        query = query.where(PublishAudit.request_id == request_id)
    result = await db.execute(query.limit(min(limit, 500)))
    return list(result.scalars().all())


async def list_login_audits(db: AsyncSession, *, account_id: Optional[str] = None,
                            operator_id: Optional[str] = None,
                            limit: int = 100) -> list:
    query = select(LoginAudit).order_by(desc(LoginAudit.created_at))
    if account_id:
        query = query.where(LoginAudit.account_id == account_id)
    if operator_id:
        query = query.where(LoginAudit.operator_id == operator_id)
    result = await db.execute(query.limit(min(limit, 500)))
    return list(result.scalars().all())


async def list_risk_events(db: AsyncSession, *, account_id: Optional[str] = None,
                           operator_id: Optional[str] = None,
                           limit: int = 100) -> list:
    query = select(RiskEvent).order_by(desc(RiskEvent.created_at))
    if account_id:
        query = query.where(RiskEvent.account_id == account_id)
    if operator_id:
        query = query.where(RiskEvent.operator_id == operator_id)
    result = await db.execute(query.limit(min(limit, 500)))
    return list(result.scalars().all())


async def trace_by_request_id(db: AsyncSession, request_id: str) -> dict:
    """按 request_id(trace_id) 拉取全链路审计，还原 operator/actor/IP/hash。"""
    audits = (
        await db.execute(
            select(PublishAudit)
            .where(PublishAudit.request_id == request_id)
            .order_by(desc(PublishAudit.created_at))
        )
    ).scalars().all()
    logins = (
        await db.execute(
            select(LoginAudit)
            .where(LoginAudit.request_id == request_id)
            .order_by(desc(LoginAudit.created_at))
        )
    ).scalars().all()
    cookies = (
        await db.execute(
            select(CookieAccessLog)
            .where(CookieAccessLog.request_id == request_id)
            .order_by(desc(CookieAccessLog.created_at))
        )
    ).scalars().all()
    risks = (
        await db.execute(
            select(RiskEvent)
            .where(RiskEvent.request_id == request_id)
            .order_by(desc(RiskEvent.created_at))
        )
    ).scalars().all()
    return {
        "request_id": request_id,
        "publish": audits,
        "login": logins,
        "cookie": cookies,
        "risk": risks,
    }
