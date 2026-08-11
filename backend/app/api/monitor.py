"""监控告警 API（三期）。

- GET/POST /api/monitor/health      系统健康检查
- GET/POST /api/monitor/alerts/rules   告警规则 CRUD
- GET       /api/monitor/alerts/events 告警事件列表
- POST      /api/monitor/alerts/check  手动触发一轮告警检查
- GET       /api/monitor/metrics       采集各指标当前值
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_roles
from app.database import get_db
from app.models.models import AlertEvent, AlertRule, UserRole
from app.utils.helpers import utc_iso
from app.services.monitor_service import (
    METRIC_DESCRIPTIONS,
    collect_metrics,
    run_alert_checks,
    check_health,
)

router = APIRouter()


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────


class AlertRuleCreate(BaseModel):
    name: str
    metric: str
    operator: str = ">"
    threshold: float = 0
    level: str = "warning"
    enabled: bool = True
    description: Optional[str] = None
    webhook_url: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    metric: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    level: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    webhook_url: Optional[str] = None


class AlertRuleResponse(BaseModel):
    id: str
    name: str
    metric: str
    operator: str
    threshold: float
    level: str
    enabled: bool
    description: Optional[str] = None
    webhook_url: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class AlertEventResponse(BaseModel):
    id: str
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    metric: Optional[str] = None
    level: str
    message: Optional[str] = None
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    notified: bool
    notify_error: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class AlertCheckResponse(BaseModel):
    checked: int
    triggered: int
    notified: int
    errors: List[str] = []


def _serialize_rule(rule: AlertRule) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "metric": rule.metric,
        "operator": rule.operator,
        "threshold": rule.threshold,
        "level": rule.level,
        "enabled": rule.enabled if rule.enabled is not None else True,
        "description": rule.description,
        "webhook_url": rule.webhook_url,
        "created_at": utc_iso(rule.created_at) if rule.created_at else "",
        "updated_at": utc_iso(rule.updated_at) if rule.updated_at else "",
    }


def _serialize_event(event: AlertEvent) -> dict:
    return {
        "id": str(event.id),
        "rule_id": str(event.rule_id) if event.rule_id else None,
        "rule_name": event.rule_name,
        "metric": event.metric,
        "level": event.level,
        "message": event.message,
        "current_value": event.current_value,
        "threshold": event.threshold,
        "notified": event.notified if event.notified is not None else False,
        "notify_error": event.notify_error,
        "created_at": utc_iso(event.created_at) if event.created_at else "",
    }


# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────


@router.get("/monitor/health")
async def health_check():
    """系统健康检查（数据库/Redis/MinIO/磁盘）."""
    return await check_health()


@router.get("/monitor/metrics")
async def get_monitor_metrics():
    """采集各监控指标当前值."""
    return await collect_metrics()


@router.post("/monitor/alerts/check", response_model=AlertCheckResponse)
async def trigger_alert_check(
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
):
    """手动触发一轮告警检查."""
    return await run_alert_checks()


@router.get("/monitor/alerts/rules", response_model=List[AlertRuleResponse])
async def list_alert_rules(
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """获取所有告警规则."""
    result = await db.execute(select(AlertRule).order_by(AlertRule.created_at))
    rules = result.scalars().all()
    return [_serialize_rule(r) for r in rules]


@router.get("/monitor/alerts/rules/meta")
async def get_alert_rule_meta():
    """获取告警指标说明（用于前端下拉选择）."""
    return [{"metric": k, "description": v} for k, v in METRIC_DESCRIPTIONS.items()]


@router.post("/monitor/alerts/rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    data: AlertRuleCreate,
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """创建告警规则."""
    rule = AlertRule(**data.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return _serialize_rule(rule)


@router.put("/monitor/alerts/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: str,
    data: AlertRuleUpdate,
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """更新告警规则."""
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的规则 ID")

    result = await db.execute(select(AlertRule).where(AlertRule.id == rid))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    rule.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(rule)
    return _serialize_rule(rule)


@router.delete("/monitor/alerts/rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: str,
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """删除告警规则."""
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的规则 ID")

    result = await db.execute(select(AlertRule).where(AlertRule.id == rid))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")

    await db.delete(rule)
    await db.flush()
    return None


@router.get("/monitor/alerts/events", response_model=List[AlertEventResponse])
async def list_alert_events(
    current_user: Annotated[Any, Depends(require_roles(UserRole.admin))],
    level: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """获取告警事件列表."""
    query = select(AlertEvent)
    if level:
        query = query.where(AlertEvent.level == level)
    query = query.order_by(desc(AlertEvent.created_at)).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()
    return [_serialize_event(e) for e in events]
