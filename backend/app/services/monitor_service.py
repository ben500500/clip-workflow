"""监控告警服务（三期）。

健康检查 + 告警规则 + 钉钉 Webhook 通知。

告警指标：
- worker_offline    Worker 节点离线（>60s 无心跳）
- task_failed       同一任务失败 >N 次
- disk_usage        磁盘使用率 >N%
- redis_memory      Redis 内存使用 >N% 最大内存
- queue_backlog     队列积压任务数 >N
- cookie_expiring   RPA Cookie 即将过期（剩余 <N 小时）
- ecpm_low          eCPM 低于阈值（看板业务告警）

规则存于 alert_rules 表，事件存于 alert_events 表，通知通过钉钉 Webhook 推送。
"""

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy import select, func, update

from app.config import settings
from app.database import async_session_factory
from app.models.models import AlertEvent, AlertRule, PublishTask, SliceTask, WorkerNode

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 告警指标说明
# ──────────────────────────────────────────────

METRIC_DESCRIPTIONS: dict[str, str] = {
    "worker_offline": "Worker 节点离线（超过 60 秒未收到心跳）",
    "task_failed": "同一任务失败次数超过阈值（需人工介入）",
    "disk_usage": "磁盘使用率超过阈值（%）",
    "redis_memory": "Redis 内存使用超过最大内存比例（%）",
    "queue_backlog": "切片队列积压任务数超过阈值",
    "cookie_expiring": "RPA Cookie 有效期剩余小时数低于阈值",
    "ecpm_low": "eCPM 低于阈值（元），提示检查广告填充率",
}

DEFAULT_RULES: list[dict] = [
    {"name": "Worker 节点离线", "metric": "worker_offline", "operator": ">", "threshold": 60, "level": "critical",
     "description": "Worker 超过 60 秒未收到心跳，视为离线"},
    {"name": "任务失败过多", "metric": "task_failed", "operator": ">", "threshold": 3, "level": "critical",
     "description": "同一任务失败超过 3 次，需要人工介入"},
    {"name": "磁盘使用率过高", "metric": "disk_usage", "operator": ">", "threshold": 80, "level": "warning",
     "description": "磁盘使用率超过 80%，建议清理临时文件或扩容"},
    {"name": "Redis 内存过高", "metric": "redis_memory", "operator": ">", "threshold": 80, "level": "warning",
     "description": "Redis 内存使用超过 80%，建议清理过期 key 或扩容"},
    {"name": "队列积压过多", "metric": "queue_backlog", "operator": ">", "threshold": 100, "level": "warning",
     "description": "待处理切片任务超过 100 个，建议增加 Worker 节点"},
    {"name": "Cookie 即将过期", "metric": "cookie_expiring", "operator": "<", "threshold": 24, "level": "warning",
     "description": "RPA Cookie 有效期剩余不足 24 小时，提醒运营重新扫码"},
    {"name": "eCPM 偏低", "metric": "ecpm_low", "operator": "<", "threshold": 10, "level": "warning",
     "description": "eCPM 低于 10 元，建议检查广告填充率"},
]


async def ensure_default_alert_rules() -> None:
    """确保默认告警规则已预置（幂等）."""
    async with async_session_factory() as session:
        for rule in DEFAULT_RULES:
            result = await session.execute(
                select(AlertRule).where(AlertRule.metric == rule["metric"])
            )
            if result.scalar_one_or_none():
                continue
            session.add(AlertRule(**rule))
        await session.commit()


# ──────────────────────────────────────────────
# 指标采集
# ──────────────────────────────────────────────


async def _get_redis() -> Any:
    """获取共享 Redis 连接（复用 redis_stream 的连接池，消除重复初始化）。"""
    from app.services.redis_stream import get_redis
    return await get_redis()


async def collect_metrics() -> dict[str, float]:
    """采集各监控指标的当前值（返回 metric → value 映射）."""
    metrics: dict[str, float] = {}

    # worker_offline：离线节点数（秒，DB 中 last_heartbeat 距今）
    # 取最久未心跳节点的秒数并取整，保证「当前值」为整数，避免出现小数秒
    async with async_session_factory() as session:
        nodes = (await session.execute(select(WorkerNode))).scalars().all()
        now = datetime.utcnow()
        offline_seconds = 0
        for node in nodes:
            if node.last_heartbeat:
                gap = (now - node.last_heartbeat).total_seconds()
                offline_seconds = max(offline_seconds, gap)
        metrics["worker_offline"] = int(round(offline_seconds))

        # task_failed：失败任务数（连续失败 >3 次的任务）
        failed_tasks = (
            await session.execute(
                select(func.count(SliceTask.id)).where(SliceTask.status == "failed")
            )
        ).scalar() or 0
        metrics["task_failed"] = float(failed_tasks)

        # cookie_expiring：最早过期的 PublishProfile cookie（无 cookie 则跳过）
        # PublishProfile 无 cookie 过期字段，此处简化为 0（跳过告警），由 RPA check_cookie_status 补充。
        metrics["cookie_expiring"] = 0.0

        # ecpm_low：最近一天平均 eCPM
        from app.models.models import AdMetric
        yesterday = (datetime.utcnow() - timedelta(days=1)).date()
        ecpm = (
            await session.execute(
                select(func.coalesce(func.avg(AdMetric.ecpm), -1)).where(AdMetric.date >= yesterday)
            )
        ).scalar() or -1
        metrics["ecpm_low"] = float(ecpm)
        # 事务内只读：显式结束事务
        await session.rollback()

    # disk_usage：根分区使用率
    try:
        usage = shutil.disk_usage("/")
        metrics["disk_usage"] = round((usage.used / usage.total) * 100, 1)
    except Exception:
        metrics["disk_usage"] = 0.0

    # redis_memory / queue_backlog
    redis = None
    try:
        redis = await _get_redis()
        info = await redis.info("memory")
        max_memory = info.get("maxmemory") or 0
        used_memory = info.get("used_memory") or 0
        metrics["redis_memory"] = round((used_memory / max_memory) * 100, 1) if max_memory else 0.0

        # 队列积压：三个优先级 Stream 的消息总数
        backlog = 0
        for stream in ("slice:tasks:high", "slice:tasks:normal", "slice:tasks:low"):
            try:
                length = await redis.xlen(stream)
                backlog += int(length)
            except Exception:
                pass
        metrics["queue_backlog"] = float(backlog)
    except Exception as e:
        logger.warning("Failed to collect Redis metrics: %s", e)
    return metrics


# ──────────────────────────────────────────────
# 钉钉通知
# ──────────────────────────────────────────────


async def send_dingtalk_alert(webhook_url: str, level: str, message: str) -> tuple[bool, str]:
    """推送钉钉机器人告警消息.

    Returns:
        (success, error_message)
    """
    if not webhook_url:
        return False, "未配置钉钉 Webhook"
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"[{level}] Clip Workflow 告警",
            "text": f"### Clip Workflow 告警\\n\\n**级别**: `{level}`\\n\\n**内容**: {message}\\n\\n**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if data.get("errcode") == 0:
                return True, ""
            return False, str(data)
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────
# 规则评估与事件落库
# ──────────────────────────────────────────────


def _evaluate(operator: str, current: float, threshold: float) -> bool:
    try:
        if operator == ">":
            return current > threshold
        if operator == ">=":
            return current >= threshold
        if operator == "<":
            return current < threshold
        if operator == "<=":
            return current <= threshold
        if operator == "==":
            return current == threshold
    except Exception:
        return False
    return False


def _format_metric_value(value) -> str:
    """格式化指标值：整数不带小数（worker_offline 等），小数保留两位."""
    try:
        f = float(value)
        if f.is_integer():
            return str(int(f))
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(value)


async def run_alert_checks() -> dict:
    """执行一轮告警检查：采集指标 → 评估规则 → 落库事件 → 钉钉通知.

    Returns:
        {"checked": int, "triggered": int, "notified": int, "errors": [str]}
    """
    metrics = await collect_metrics()
    async with async_session_factory() as session:
        rules = (await session.execute(
            select(AlertRule).where(AlertRule.enabled.is_(True))
        )).scalars().all()

        checked = 0
        triggered = 0
        notified = 0
        errors: list[str] = []

        for rule in rules:
            checked += 1
            current = metrics.get(rule.metric)
            if current is None:
                continue
            # cookie_expiring 无数据时跳过（0 值不触发 <24h 告警）
            if rule.metric == "cookie_expiring" and current <= 0:
                continue

            if not _evaluate(rule.operator, current, rule.threshold):
                continue

            triggered += 1
            message = (
                f"【{rule.name}】当前值 {_format_metric_value(current)}，"
                f"阈值 {rule.operator} {_format_metric_value(rule.threshold)}"
            )

            # 落库事件
            event = AlertEvent(
                rule_id=rule.id,
                rule_name=rule.name,
                metric=rule.metric,
                level=rule.level,
                message=message,
                current_value=current,
                threshold=rule.threshold,
            )

            # 钉钉通知（规则级 webhook 优先，其次全局）
            webhook = rule.webhook_url or settings.DINGTALK_WEBHOOK
            if webhook:
                ok, err = await send_dingtalk_alert(webhook, rule.level, message)
                event.notified = ok
                event.notify_error = err if not ok else None
                if ok:
                    notified += 1
                else:
                    errors.append(f"{rule.name}: {err}")
            session.add(event)
            await session.flush()

        await session.commit()
        return {"checked": checked, "triggered": triggered, "notified": notified, "errors": errors}


# ──────────────────────────────────────────────
# 健康检查
# ──────────────────────────────────────────────


async def check_health() -> dict:
    """增强版健康检查：数据库 / Redis / MinIO / 磁盘 连接状态."""
    result: dict = {
        "status": "ok",
        "service": "clip-workflow-backend",
        "checks": {},
    }
    all_ok = True

    # 数据库
    try:
        async with async_session_factory() as session:
            await session.execute(select(func.count(WorkerNode.id)).limit(1))
            # 事务内只读：显式结束事务
            await session.rollback()
        result["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        all_ok = False
        result["checks"]["database"] = {"status": "error", "error": str(e)}

    # Redis
    redis = None
    try:
        redis = await _get_redis()
        await redis.ping()
        result["checks"]["redis"] = {"status": "ok"}
    except Exception as e:
        all_ok = False
        result["checks"]["redis"] = {"status": "error", "error": str(e)}
    # MinIO
    try:
        from app.services.minio_service import get_minio_client
        client = get_minio_client()
        await asyncio.get_event_loop().run_in_executor(None, client.bucket_exists, settings.MINIO_BUCKET_RAW)
        result["checks"]["minio"] = {"status": "ok"}
    except Exception as e:
        all_ok = False
        result["checks"]["minio"] = {"status": "error", "error": str(e)}

    # 磁盘
    try:
        usage = shutil.disk_usage("/")
        pct = round((usage.used / usage.total) * 100, 1)
        result["checks"]["disk"] = {"status": "ok", "usage_percent": pct}
        if pct > 90:
            all_ok = False
            result["checks"]["disk"]["status"] = "warning"
    except Exception as e:
        result["checks"]["disk"] = {"status": "error", "error": str(e)}

    result["status"] = "ok" if all_ok else "degraded"
    return result
