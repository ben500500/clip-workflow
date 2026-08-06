"""Worker 节点管理 API。

提供 Worker 节点的注册、心跳、状态查询等管理接口，
以及从 Redis 同步 Worker 节点状态到数据库的机制。
"""

import logging
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_roles
from app.database import get_db
from app.models.models import User, UserRole, WorkerNode
from app.services.redis_stream import get_worker_nodes_from_redis

logger = logging.getLogger(__name__)

router = APIRouter()


class WorkerNodeResponse(BaseModel):
    id: str
    node_id: str
    hostname: Optional[str] = None
    ip: Optional[str] = None
    os: Optional[str] = None
    arch: Optional[str] = None
    ffmpeg_version: Optional[str] = None
    tags: list = []
    max_concurrent: int = 2
    status: str = "offline"
    current_tasks: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    last_heartbeat: Optional[str] = None
    started_at: Optional[str] = None
    created_at: str = ""

    model_config = {"from_attributes": True}


class WorkerHeartbeatRequest(BaseModel):
    node_id: str
    hostname: Optional[str] = None
    ip: Optional[str] = None
    os: Optional[str] = None
    arch: Optional[str] = None
    ffmpeg_version: Optional[str] = None
    tags: list = []
    max_concurrent: int = 2
    current_tasks: int = 0
    status: str = "online"


def _serialize_node(node: WorkerNode) -> dict:
    return {
        "id": str(node.id),
        "node_id": node.node_id,
        "hostname": node.hostname,
        "ip": node.ip,
        "os": node.os,
        "arch": node.arch,
        "ffmpeg_version": node.ffmpeg_version,
        "tags": node.tags or [],
        "max_concurrent": node.max_concurrent or 2,
        "status": node.status or "offline",
        "current_tasks": node.current_tasks or 0,
        "total_tasks_completed": node.total_tasks_completed or 0,
        "total_tasks_failed": node.total_tasks_failed or 0,
        "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
        "started_at": node.started_at.isoformat() if node.started_at else None,
        "created_at": node.created_at.isoformat() if node.created_at else "",
    }


@router.post("/workers/heartbeat")
async def worker_heartbeat(
    data: WorkerHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Worker 节点心跳上报（由 Worker 定时调用）。"""
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == data.node_id)
    )
    node = result.scalar_one_or_none()

    now = datetime.utcnow()
    if node:
        node.hostname = data.hostname or node.hostname
        node.ip = data.ip or node.ip
        node.os = data.os or node.os
        node.arch = data.arch or node.arch
        node.ffmpeg_version = data.ffmpeg_version or node.ffmpeg_version
        node.tags = data.tags or node.tags
        node.max_concurrent = data.max_concurrent or node.max_concurrent
        node.current_tasks = data.current_tasks
        node.status = data.status
        node.last_heartbeat = now
    else:
        node = WorkerNode(
            node_id=data.node_id,
            hostname=data.hostname,
            ip=data.ip,
            os=data.os,
            arch=data.arch,
            ffmpeg_version=data.ffmpeg_version,
            tags=data.tags,
            max_concurrent=data.max_concurrent,
            current_tasks=data.current_tasks,
            status=data.status,
            last_heartbeat=now,
            started_at=now,
        )
        db.add(node)

    await db.flush()
    return {"ok": True, "node_id": data.node_id}


@router.get("/workers", response_model=List[WorkerNodeResponse])
async def list_workers(
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """获取所有 Worker 节点列表（数据库 + Redis 在线状态）。"""
    # 从数据库查询所有节点
    result = await db.execute(
        select(WorkerNode).order_by(WorkerNode.created_at.desc())
    )
    nodes = result.scalars().all()

    # 尝试从 Redis 获取节点信息补充（含在线/离线判定）
    try:
        redis_nodes = await get_worker_nodes_from_redis()
        redis_map = {n["node_id"]: n for n in redis_nodes}
        for node in nodes:
            if node.node_id in redis_map:
                rd = redis_map[node.node_id]
                node.current_tasks = rd.get("current_tasks", node.current_tasks)
                node.hostname = rd.get("hostname") or node.hostname
                node.ip = rd.get("ip") or node.ip
                node.os = rd.get("os") or node.os
                node.arch = rd.get("arch") or node.arch
                node.ffmpeg_version = rd.get("ffmpeg_version") or node.ffmpeg_version
                node.tags = rd.get("tags", node.tags or [])
                node.max_concurrent = rd.get("max_concurrent", node.max_concurrent or 2)
                node.total_tasks_completed = rd.get("total_tasks_completed", node.total_tasks_completed or 0)
                node.total_tasks_failed = rd.get("total_tasks_failed", node.total_tasks_failed or 0)
                node.status = rd.get("status", node.status or "offline")
                # 同步心跳时间
                last_hb = rd.get("last_heartbeat", "")
                if last_hb:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        node.last_heartbeat = _dt.fromtimestamp(int(last_hb), tz=_tz.utc)
                    except (ValueError, OSError, TypeError):
                        pass
    except Exception as e:
        logger.warning("Failed to sync workers from Redis: %s", e)
        redis_nodes = []
        redis_map = {}

    # 数据库中不存在于 Redis 的节点（心跳 Hash 已过期）标记为离线
    for node in nodes:
        if node.node_id not in redis_map:
            node.status = "offline"

    return [_serialize_node(n) for n in nodes]


@router.get("/workers/{node_id}", response_model=WorkerNodeResponse)
async def get_worker(
    node_id: str,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """获取单个 Worker 节点详情。"""
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Worker node not found")
    return _serialize_node(node)


@router.post("/workers/sync-redis")
async def sync_workers_from_redis(
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """从 Redis 同步 Worker 节点状态到数据库（手动触发）。"""
    try:
        redis_nodes = await get_worker_nodes_from_redis()
        now = datetime.utcnow()
        synced = 0
        for rd in redis_nodes:
            result = await db.execute(
                select(WorkerNode).where(WorkerNode.node_id == rd["node_id"])
            )
            node = result.scalar_one_or_none()
            if node:
                node.hostname = rd.get("hostname") or node.hostname
                node.ip = rd.get("ip") or node.ip
                node.os = rd.get("os") or node.os
                node.arch = rd.get("arch") or node.arch
                node.ffmpeg_version = rd.get("ffmpeg_version") or node.ffmpeg_version
                node.tags = rd.get("tags", node.tags or [])
                node.max_concurrent = rd.get("max_concurrent", node.max_concurrent or 2)
                node.current_tasks = rd.get("current_tasks", node.current_tasks)
                node.total_tasks_completed = rd.get("total_tasks_completed", node.total_tasks_completed or 0)
                node.total_tasks_failed = rd.get("total_tasks_failed", node.total_tasks_failed or 0)
                node.status = rd.get("status", "online")
                # 心跳时间优先使用 Redis 上报的时间戳
                last_hb = rd.get("last_heartbeat", "")
                if last_hb:
                    try:
                        node.last_heartbeat = datetime.utcfromtimestamp(int(last_hb))
                    except (ValueError, OSError, TypeError):
                        node.last_heartbeat = now
                else:
                    node.last_heartbeat = now
            else:
                node = WorkerNode(
                    node_id=rd["node_id"],
                    hostname=rd.get("hostname"),
                    ip=rd.get("ip"),
                    os=rd.get("os"),
                    arch=rd.get("arch"),
                    ffmpeg_version=rd.get("ffmpeg_version"),
                    tags=rd.get("tags", []),
                    max_concurrent=rd.get("max_concurrent", 2),
                    current_tasks=rd.get("current_tasks", 0),
                    total_tasks_completed=rd.get("total_tasks_completed", 0),
                    total_tasks_failed=rd.get("total_tasks_failed", 0),
                    status=rd.get("status", "online"),
                    last_heartbeat=now,
                    started_at=now,
                )
                db.add(node)
            synced += 1

        # 数据库中存在但不在 Redis 中的节点（心跳 Hash 已过期）标记为离线
        all_db_nodes = await db.execute(select(WorkerNode))
        db_nodes = all_db_nodes.scalars().all()
        redis_node_ids = {rd["node_id"] for rd in redis_nodes}
        for node in db_nodes:
            if node.node_id not in redis_node_ids:
                node.status = "offline"

        await db.flush()
        return {"synced": synced, "message": f"已同步 {synced} 个 Worker 节点"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"从 Redis 同步 Worker 节点失败: {e}",
        )