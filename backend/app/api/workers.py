"""Worker 节点管理 API。

提供 Worker 节点的注册、心跳、状态查询等管理接口，
以及从 Redis 同步 Worker 节点状态到数据库的机制。
"""

import hashlib
import io
import json
import logging
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_roles
from app.config import settings
from app.database import get_db
from app.models.models import User, UserRole, WorkerNode
from app.utils.helpers import utc_iso
from app.services.redis_stream import (
    get_worker_nodes_from_redis,
    set_node_enabled,
    is_node_enabled,
    set_node_cpu_percent,
    get_node_cpu_percent,
    delete_worker_node,
    set_node_update_command,
    get_node_update_command,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 供 Go slice-worker 心跳上报的开放 router（main.py 单独挂载，不套用户 JWT 依赖）
internal_router = APIRouter()


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
    # 该节点正在运行的任务列表（含 task_id/阶段/模式/进度，供界面展示"当前在处理什么"）
    running_tasks: list = []
    # 该节点 CPU 资源分配比例（%，默认 50）
    cpu_percent: int = 50
    # 该节点当前引擎版本（心跳上报；供界面展示节点引擎是否与服务器一致）
    engine_version: Optional[str] = None
    # 该节点硬件编码能力（如 h264_nvenc/hevc_nvenc 等；预留 GPU 节点自动分派接口）
    encoder_capabilities: list = []

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
    # 累计完成/失败任务数（心跳同步到 DB，保证 Worker 节点界面有数据）
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    # 节点当前引擎版本（心跳上报，供界面判断是否需要推送更新）
    engine_version: Optional[str] = None
    # 节点硬件编码能力（如 h264_nvenc/hevc_nvenc 等；预留 GPU 节点自动分派接口）
    encoder_capabilities: list = []


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
        "last_heartbeat": utc_iso(node.last_heartbeat) if node.last_heartbeat else None,
        "started_at": utc_iso(node.started_at) if node.started_at else None,
        "created_at": utc_iso(node.created_at) if node.created_at else "",
        "running_progress": getattr(node, "running_progress", 0.0) or 0.0,
        "running_tasks": getattr(node, "running_tasks", []) or [],
        "cpu_percent": getattr(node, "cpu_percent", 50) or 50,
        "engine_version": getattr(node, "engine_version", None) or None,
        "encoder_capabilities": getattr(node, "encoder_capabilities", None) or [],
    }


@internal_router.post("/workers/heartbeat")
async def worker_heartbeat(
    data: WorkerHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Worker 节点心跳上报（由 Worker 定时调用）。

    响应带该节点 enabled 状态（供 Worker 判断是否暂停消费）；兼容旧 Worker：
    未读取 enabled 字段的旧版本行为不变（视为已启用）。
    """
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
        # 累计完成/失败数同步（Worker 心跳携带）
        node.total_tasks_completed = data.total_tasks_completed or 0
        node.total_tasks_failed = data.total_tasks_failed or 0
        # 硬件编码能力同步（预留 GPU 节点自动分派接口）
        if data.encoder_capabilities:
            node.encoder_capabilities = data.encoder_capabilities
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
            total_tasks_completed=data.total_tasks_completed or 0,
            total_tasks_failed=data.total_tasks_failed or 0,
            encoder_capabilities=data.encoder_capabilities,
            last_heartbeat=now,
            started_at=now,
        )
        db.add(node)

    await db.flush()

    # 读取该节点当前启停状态（管理员 PATCH 写入 Redis 控制 key），随心跳响应带回，
    # 供 Worker 判断是否暂停领取新任务。读不到（如 Redis 异常）时默认视为启用。
    enabled = await is_node_enabled(data.node_id)
    return {"ok": True, "node_id": data.node_id, "enabled": enabled}


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
                # 节点硬件编码能力：优先取 Redis 心跳上报（实时）
                if rd.get("encoder_capabilities"):
                    node.encoder_capabilities = rd.get("encoder_capabilities")
                # 节点启停状态：优先取 Redis 控制 key（管理员在界面上可启停）
                if "enabled" in rd:
                    node.enabled = bool(rd["enabled"])
                # 同步心跳时间
                last_hb = rd.get("last_heartbeat", "")
                if last_hb:
                    try:
                        # 统一用 naive UTC 时间，避免与 datetime.utcnow() 混用导致 asyncpg
                        # "can't subtract offset-naive and offset-aware datetimes" 批量更新报错
                        from datetime import datetime as _dt
                        node.last_heartbeat = _dt.utcfromtimestamp(int(last_hb))
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
                encoder_capabilities=rd.get("encoder_capabilities", []),
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
            # 该节点正在运行的任务详情（供界面展示"当前在处理什么"）
            d["running_tasks"] = rd.get("running_tasks", []) or []
            # 该节点当前引擎版本（心跳上报，用于判断是否需要推送更新）
            d["engine_version"] = rd.get("engine_version") or d.get("engine_version")
            # 该节点硬件编码能力（心跳上报；预留 GPU 自动分派接口）
            d["encoder_capabilities"] = rd.get("encoder_capabilities") or d.get("encoder_capabilities") or []
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


class _NodeEnabledPatch(BaseModel):
    """PATCH /workers/{node_id}/enabled 请求体：统一启停开关。"""
    enabled: bool = True


@router.patch("/workers/{node_id}/enabled")
async def set_worker_enabled(
    node_id: str,
    data: _NodeEnabledPatch,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """统一启停节点（RESTful PATCH）：body `{"enabled": bool}`。

    与 POST /enable 与 /disable 等价，提供更符合 REST 语义的单接口
    （P1 worker 节点功能开关）。停用后 Worker 暂停领取新任务（正在执行的
    任务跑完不受影响），启用以恢复消费。状态写入 Redis 控制 key，并在
    下一次心跳响应中带给节点。
    """
    # 更新数据库标记（若已存在记录）
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == node_id)
    )
    node = result.scalar_one_or_none()
    if node:
        node.enabled = data.enabled
        await db.flush()

    # 写入 Redis 控制 key，Worker 端取任务前读取；心跳响应也会回传该状态
    await set_node_enabled(node_id, data.enabled)
    action = "已启用" if data.enabled else "已停用（正在执行的任务不受影响）"
    return {"ok": True, "node_id": node_id, "enabled": data.enabled, "message": f"节点 {node_id} {action}"}


@router.delete("/workers/{node_id}")
async def delete_worker(
    node_id: str,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """删除废弃的 Worker 节点（数据库记录 + Redis 痕迹一并清理）。

    适用于不再使用、误注册或废弃的节点，删除后该节点将不再出现在
    Worker 节点管理列表中；若节点仍在运行并继续心跳，会重新自动注册。
    """
    # 删除数据库记录
    result = await db.execute(
        select(WorkerNode).where(WorkerNode.node_id == node_id)
    )
    node = result.scalar_one_or_none()
    if node:
        await db.delete(node)
        await db.flush()

    # 清理 Redis 痕迹（节点 Hash/在线集合/标签/控制 key/该节点运行中的任务 Hash）
    redis_deleted = await delete_worker_node(node_id)

    return {
        "ok": True,
        "node_id": node_id,
        "deleted": True,
        "message": f"节点 {node_id} 已删除"
        + ("（Redis 痕迹已清理）" if redis_deleted else "（Redis 清理失败，请稍后重试）"),
    }


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
                # 节点硬件编码能力（预留 GPU 自动分派接口；从 Redis 心跳同步）
                if rd.get("encoder_capabilities"):
                    node.encoder_capabilities = rd.get("encoder_capabilities")
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


# ==================== 节点引擎更新推送 ====================
#
# 背景：节点（slice-worker）本地会保存一份 engines/ 引擎脚本（slice.py、
# vert2horiz_crop.py 等）副本，docker 部署通过只读挂载，裸机部署复制到本地。
# 当服务器上这些引擎脚本被修改（bug 修复、能力增强）后，传统方式需要重新
# 构建镜像/重新部署节点，成本高。这里提供「推送更新」能力：管理员在界面点击
# 「推送更新」→ 后端把服务器端最新 engines/ 目录打包并下发指令 → 节点 Worker
# 在心跳循环中检测到目标版本与本地不一致时，自动从后端拉取更新包并替换本地
# engines/ 目录，无需重新部署/重启节点。

# 打包时需要排除的目录/文件（避免把缓存/编译产物/敏感文件下发给节点）
_ENGINE_EXCLUDE = (
    "__pycache__",
    ".pyc",
    ".pyo",
    ".git",
    ".DS_Store",
    ".gitignore",
    "README.md",
)


def _resolve_engines_dir() -> Path:
    """解析服务器端引擎目录绝对路径。"""
    p = Path(settings.ENGINES_DIR)
    if not p.is_absolute():
        p = Path(os.path.abspath(settings.ENGINES_DIR))
    return p


def _iter_engine_files(engines_dir: Path):
    """遍历引擎目录下应下发给节点的文件（排除缓存/编译产物）。"""
    if not engines_dir.exists():
        return
    for root, dirs, files in os.walk(engines_dir):
        dirs[:] = [d for d in dirs if d not in _ENGINE_EXCLUDE]
        for name in files:
            if name.endswith(_ENGINE_EXCLUDE):
                continue
            fp = Path(root) / name
            # 只下发普通文件（跳过软链接/特殊文件）
            if fp.is_file():
                yield fp


def _compute_engine_version(engines_dir: Path) -> str:
    """计算引擎目录版本：所有文件内容 SHA256 汇总，取前 12 位十六进制。

    任一文件内容/新增/删除都会导致版本变化，用于节点判断是否需要更新。
    """
    h = hashlib.sha256()
    files = sorted(_iter_engine_files(engines_dir), key=lambda p: str(p))
    for fp in files:
        rel = str(fp.relative_to(engines_dir))
        h.update(rel.encode("utf-8"))
        try:
            with open(fp, "rb") as f:
                h.update(f.read())
        except OSError:
            continue
    return h.hexdigest()[:12]


def _build_engine_archive(engines_dir: Path) -> bytes:
    """把引擎目录打包为 tar.gz 字节流（供节点拉取更新）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fp in sorted(_iter_engine_files(engines_dir), key=lambda p: str(p)):
            rel = str(fp.relative_to(engines_dir))
            tar.add(fp, arcname=rel)
    buf.seek(0)
    return buf.getvalue()


@router.get("/workers/engines/status")
async def get_engines_status(
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    """获取服务器端当前引擎版本与文件清单（用于判断/推送更新）。"""
    engines_dir = _resolve_engines_dir()
    if not engines_dir.exists():
        raise HTTPException(status_code=404, detail=f"引擎目录不存在: {engines_dir}")
    version = _compute_engine_version(engines_dir)
    files = [
        str(fp.relative_to(engines_dir))
        for fp in sorted(_iter_engine_files(engines_dir), key=lambda p: str(p))
    ]
    return {
        "engines_dir": str(engines_dir),
        "version": version,
        "file_count": len(files),
        "files": files,
    }


@internal_router.get("/workers/engines/package")
async def get_engines_package(
    node_id: str = "",
):
    """获取服务器端引擎更新包（tar.gz），供节点 Worker 拉取后替换本地 engines/ 目录。

    挂在 internal_router（无用户 JWT，与心跳接口一致）下，供 Go slice-worker 直接访问。
    节点 Worker 在检测到更新指令后调用此接口下载更新包。
    """
    engines_dir = _resolve_engines_dir()
    if not engines_dir.exists():
        raise HTTPException(status_code=404, detail=f"引擎目录不存在: {engines_dir}")
    version = _compute_engine_version(engines_dir)
    archive = _build_engine_archive(engines_dir)
    return StreamingResponse(
        io.BytesIO(archive),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="engines-{version}.tar.gz"',
            "X-Engine-Version": version,
        },
    )


@router.post("/workers/{node_id}/push-update")
async def push_worker_update(
    node_id: str,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    """向指定节点推送引擎更新。

    后端把服务器端最新引擎版本写入 Redis 更新指令，节点 Worker 在心跳循环中
    检测到目标版本与本地引擎版本不一致时，自动从后端拉取更新包并替换本地
    engines/ 目录，无需重新部署节点。
    """
    engines_dir = _resolve_engines_dir()
    if not engines_dir.exists():
        raise HTTPException(status_code=404, detail=f"引擎目录不存在: {engines_dir}")
    target_version = _compute_engine_version(engines_dir)

    # 校验节点是否在线（从 Redis 读取节点状态）
    try:
        redis_nodes = await get_worker_nodes_from_redis()
        online_ids = {n["node_id"] for n in redis_nodes if n.get("status") == "online"}
    except Exception:
        online_ids = set()

    offline = node_id not in online_ids

    ok = await set_node_update_command(node_id, target_version)
    if not ok:
        raise HTTPException(status_code=500, detail=f"写入节点 {node_id} 的更新指令失败")

    return {
        "ok": True,
        "node_id": node_id,
        "target_version": target_version,
        "message": f"已向节点 {node_id} 推送更新（目标版本 {target_version}）"
        + ("；节点当前离线，将在其重新上线后自动应用" if offline else ";节点将自动拉取并应用"),
    }