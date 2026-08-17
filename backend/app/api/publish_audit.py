"""publish API 子域：多运营者审计与可观测（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持
`/publish/multi-operator/*` 与 `/publish/audit*` 不变。
本模块负责端口矩阵看板 / 运营者配额 / 发布·登录·风控审计查询与链路溯源。
"""
from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import User
from app.api.publish_common import _require_admin
from app.utils.helpers import utc_iso

router = APIRouter()


def _serialize_publish_audit(a) -> dict:
    return {
        "id": str(a.id),
        "task_id": str(a.task_id) if a.task_id else None,
        "account_id": str(a.account_id) if a.account_id else None,
        "operator_id": str(a.operator_id) if a.operator_id else None,
        "actor_id": str(a.actor_id) if a.actor_id else None,
        "profile_id": str(a.profile_id) if a.profile_id else None,
        "content_hash": a.content_hash,
        "cover_variant": a.cover_variant,
        "copy_template": a.copy_template,
        "source_ip": a.source_ip,
        "egress_ip": a.egress_ip,
        "ua_seed": a.ua_seed,
        "port": a.port,
        "action": a.action,
        "result": a.result,
        "risk_flag": a.risk_flag,
        "risk_note": a.risk_note,
        "request_id": a.request_id,
        "created_at": utc_iso(a.created_at) if a.created_at else None,
    }


def _serialize_login_audit(a) -> dict:
    return {
        "id": str(a.id),
        "account_id": str(a.account_id) if a.account_id else None,
        "operator_id": str(a.operator_id) if a.operator_id else None,
        "actor_id": str(a.actor_id) if a.actor_id else None,
        "qr_key": a.qr_key,
        "ttl_seconds": a.ttl_seconds,
        "action": a.action,
        "scanner_name": a.scanner_name,
        "source_ip": a.source_ip,
        "result": a.result,
        "request_id": a.request_id,
        "created_at": utc_iso(a.created_at) if a.created_at else None,
    }


def _serialize_risk_event(a) -> dict:
    return {
        "id": str(a.id),
        "account_id": str(a.account_id) if a.account_id else None,
        "operator_id": str(a.operator_id) if a.operator_id else None,
        "actor_id": str(a.actor_id) if a.actor_id else None,
        "risk_type": a.risk_type,
        "level": a.level,
        "message": a.message,
        "disposition": a.disposition,
        "source_ip": a.source_ip,
        "request_id": a.request_id,
        "created_at": utc_iso(a.created_at) if a.created_at else None,
    }


@router.get("/publish/multi-operator/matrix", response_model=List[dict])
async def get_multi_operator_matrix(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """运营者端口矩阵看板（读 Redis 路由表）：port/status/operator/限额消耗。

    开启多运营者（MULTI_OPERATOR_ENABLED=true）后返回路由矩阵；未开启返回空列表
    （前端可提示「多运营者未启用」）。
    """
    from app.services import multi_operator
    matrix = await multi_operator.get_route_matrix()
    return matrix


@router.get("/publish/multi-operator/operators", response_model=List[dict])
async def get_multi_operator_operators(
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """各运营者当日配额消耗 + inflight 快照（看板「限额消耗」）。"""
    from app.services import multi_operator
    return await multi_operator.get_operator_stats()


@router.get("/publish/audit", response_model=dict)
async def list_publish_audits(
    action: Optional[str] = Query(None, description="过滤动作：publish/confirm/fail/reauth"),
    account_id: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
    request_id: Optional[str] = Query(None, description="trace_id 溯源"),
    kind: Optional[str] = Query("publish", description="audit 类型：publish/login/risk"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """审计日志查询（仅 admin）。kind 区分 publish/login/risk 三类。"""
    _require_admin(current_user)
    from app.services import audit_service

    if kind == "login":
        items = await audit_service.list_login_audits(
            db, account_id=account_id, operator_id=operator_id, limit=limit
        )
        return {"kind": "login", "items": [_serialize_login_audit(x) for x in items]}
    if kind == "risk":
        items = await audit_service.list_risk_events(
            db, account_id=account_id, operator_id=operator_id, limit=limit
        )
        return {"kind": "risk", "items": [_serialize_risk_event(x) for x in items]}
    items = await audit_service.list_publish_audits(
        db, action=action, account_id=account_id,
        operator_id=operator_id, request_id=request_id, limit=limit,
    )
    return {"kind": "publish", "items": [_serialize_publish_audit(x) for x in items]}


@router.get("/publish/audit/trace/{request_id}", response_model=dict)
async def trace_publish_audit(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """按 request_id(trace_id) 溯源完整链路：operator/actor/IP/hash（方案 5.4 DoD）。"""
    _require_admin(current_user)
    from app.services import audit_service

    trace = await audit_service.trace_by_request_id(db, request_id)
    return {
        "request_id": request_id,
        "publish": [_serialize_publish_audit(x) for x in trace["publish"]],
        "login": [_serialize_login_audit(x) for x in trace["login"]],
        "cookie": [
            {
                "id": str(x.id),
                "profile_id": str(x.profile_id) if x.profile_id else None,
                "account_id": str(x.account_id) if x.account_id else None,
                "actor_id": str(x.actor_id) if x.actor_id else None,
                "operator_id": str(x.operator_id) if x.operator_id else None,
                "purpose": x.purpose,
                "ip_address": x.ip_address,
                "request_id": x.request_id,
                "created_at": utc_iso(x.created_at) if x.created_at else None,
            }
            for x in trace["cookie"]
        ],
        "risk": [_serialize_risk_event(x) for x in trace["risk"]],
    }


@router.get("/publish/multi-operator/verification", response_model=dict)
async def get_multi_operator_verification(
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """多运营者验证向导的实时状态报告（引导逐步验收）。

    返回灰度开关 / 路由表 / 幂等待确认 / 配额 / 风控 / 登录态审计等检查点状态。
    仅 admin 可查（验证向导属运维/验收视图）。
    """
    _require_admin(current_user)
    from app.services import multi_operator
    return await multi_operator.get_verification_status()


@router.post("/publish/multi-operator/verification/flag", response_model=dict)
async def set_multi_operator_flag(
    enabled: bool = Body(..., embed=True, description="灰度开关 MULTI_OPERATOR_ENABLED"),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """开启 / 关闭多运营者灰度开关（Redis 热更，主题7；零侵入回滚）。仅 admin。"""
    _require_admin(current_user)
    from app.services import multi_operator
    await multi_operator.set_flag(enabled)
    return {"flag_on": enabled, "message": "灰度开关已" + ("开启" if enabled else "关闭")}
