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
from app.services.redis_stream import (
    get_worker_nodes_from_redis,
    set_node_enabled,
    is_node_enabled,
    set_node_cpu_percent,
    get_node_cpu_percent,
)

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
    # 节点是否启用（管理员可启停；停用后 Worker 不再领取新任务）
    enabled: bool = True
    status: str = "offline"
    current_tasks: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    last_heartbeat: Optional[str] = None
    started_at: Optional[str] = None
    created_at: str = ""
    # 该节点正在运行的任务平均进度（"工作时进度显示"）
    running_progress: float = 0.0
    # 该节点 CPU 资源分配比例（%，默认 50）
    cpu_percent: int = 50

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
        "enabled": node.enabled if node.enabled is not None else True,
        "status": node.status or "offline",
        "current_tasks": node.current_tasks or 0,
        "total_tasks_completed": node.total_tasks_completed or 0,
        "total_tasks_failed": node.total_tasks_failed or 0,
        "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
        "started_at": node.started_at.isoformat() if node.started_at else None,
        "created_at": node.created_at.isoformat() if node.created_at else "",
        "running_progress": getattr(node, "running_progress", 0.0) or 0.0,
        "cpu_percent": getattr(node, "cpu_percent", 50) or 50,
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
                # 节点 CPU 分配比例：优先取 Redis 控制 key（运行时动态调整）
                if "cpu_percent" in rd:
                    node.cpu_percent = max(1, min(100, int(rd["cpu_percent"] or 50)))
                # 节点启停状态：优先取 Redis 控制 key（管理员在界面上可启停）
                if "enabled" in rd:
                    node.enabled = bool(rd["enabled"])
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

    # 数据库中无记录但 Redis 在线的节点（心跳在 sync 间隔内新注册）也返回
    for rd in redis_nodes:
        if rd["node_id"] not in {n.node_id for n in nodes}:
            nodes.append(WorkerNode(
                node_id=rd["node_id"],
                hostname=rd.get("hostname"),
                ip=rd.get("ip"),
                os=rd.get("os"),
                arch=rd.get("arch"),
                ffmpeg_version=rd.get("ffmpeg_version"),
                tags=rd.get("tags", []),
                max_concurrent=rd.get("max_concurrent", 2),
                enabled=bool(rd.get("enabled", True)),
                cpu_percent=max(1, min(100, int(rd.get("cpu_percent", 50) or 50))),
                status=rd.get("status", "online"),
                current_tasks=rd.get("current_tasks", 0),
                total_tasks_completed=rd.get("total_tasks_completed", 0),
                total_tasks_failed=rd.get("total_tasks_failed", 0),
                last_heartbeat=None,
                started_at=None,
                created_at=datetime.utcnow(),
            ))

    # 序列化时合并 Redis 中的实时进度（running_progress 非 DB 列，从 redis_map 取）
    result = []
    for n in nodes:
        d = _serialize_node(n)
        rd = redis_map.get(n.node_id)
        if rd:
            d["running_progress"] = rd.get("running_progress", 0.0) or 0.0
            d["cpu_percent"] = rd.get("cpu_percent", d.get("cpu_percent", 50)) or 50
        result.append(d)
    return result


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


@router.post("/workers/{node_id}/enable")
async def enable_worker_node(
    node_id: str,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """启用节点：允许该节点继续领取切片任务。"""
    # 更新数据库标记（若已存在记录）
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == node_id)
    )
    node = result.scalar_one_or_none()
    if node:
        node.enabled = True
        await db.flush()
    # 写入 Redis 控制 key，Worker 端每次取任务前读取
    await set_node_enabled(node_id, True)
    return {"ok": True, "node_id": node_id, "enabled": True, "message": f"节点 {node_id} 已启用"}


@router.post("/workers/{node_id}/disable")
async def disable_worker_node(
    node_id: str,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """停用节点：节点不再领取新的切片任务（正在执行的任务不受影响）。"""
    # 更新数据库标记（若已存在记录）
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == node_id)
    )
    node = result.scalar_one_or_none()
    if node:
        node.enabled = False
        await db.flush()
    # 写入 Redis 控制 key，Worker 端每次取任务前读取
    await set_node_enabled(node_id, False)
    return {"ok": True, "node_id": node_id, "enabled": False, "message": f"节点 {node_id} 已停用（正在执行的任务不受影响）"}


class SetNodeCpuPercentRequest(BaseModel):
    """调整节点 CPU 资源分配比例请求。"""
    cpu_percent: int = 50


@router.post("/workers/{node_id}/cpu-percent")
async def set_worker_cpu_percent(
    node_id: str,
    data: SetNodeCpuPercentRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """调整节点 CPU 资源分配比例（1~100，默认 50）。

    写入 Redis 控制 key 后，Worker 端在下次领取任务前会读取并应用，
    无需重启节点即可动态生效；同时同步更新数据库记录。
    """
    percent = max(1, min(100, int(data.cpu_percent)))

    # 更新数据库标记（若已存在记录）
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == node_id)
    )
    node = result.scalar_one_or_none()
    if node:
        node.cpu_percent = percent
        await db.flush()

    # 写入 Redis 控制 key，Worker 端每次取任务前读取并应用
    await set_node_cpu_percent(node_id, percent)
    return {
        "ok": True,
        "node_id": node_id,
        "cpu_percent": percent,
        "message": f"节点 {node_id} 的 CPU 分配已调整为 {percent}%",
    }


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
                # 节点 CPU 分配比例（管理员在界面上可调整）
                if "cpu_percent" in rd:
                    node.cpu_percent = max(1, min(100, int(rd["cpu_percent"] or 50)))
                # 节点启停状态（管理员在界面上可启停）
                if "enabled" in rd:
                    node.enabled = bool(rd["enabled"])
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
                    enabled=bool(rd.get("enabled", True)),
                    cpu_percent=max(1, min(100, int(rd.get("cpu_percent", 50) or 50))),
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