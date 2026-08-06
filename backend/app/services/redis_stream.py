"""Redis Stream 服务：发布切片任务到 Worker 节点的队列。"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# 优先级 Stream 名称
STREAM_HIGH = "slice:tasks:high"
STREAM_NORMAL = "slice:tasks:normal"
STREAM_LOW = "slice:tasks:low"

# Consumer Group 名称
CONSUMER_GROUP = "workers"

# Redis Hash 中任务状态 key 前缀
TASK_STATUS_PREFIX = "slice:task:"

# 任务回调 Token key 前缀
TASK_TOKEN_PREFIX = "slice:task:token:"

# 节点信息 Hash key 前缀（与 Go Worker 契约一致）
NODE_KEY_PREFIX = "slice:nodes:"

# 节点启停控制 key：值为 0/1（1 表示允许领取任务），Worker 端每次取任务前读取
NODE_ENABLED_PREFIX = "slice:node-enabled:"


def _get_stream(priority: str = "normal") -> str:
    """根据优先级返回对应的 Stream 名称。"""
    return {
        "high": STREAM_HIGH,
        "normal": STREAM_NORMAL,
        "low": STREAM_LOW,
    }.get(priority, STREAM_NORMAL)


async def get_redis() -> aioredis.Redis:
    """创建 Redis 连接。"""
    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )


async def publish_slice_task(task_data: dict, priority: str = "normal") -> Optional[str]:
    """将切片任务发布到 Redis Stream。

    Args:
        task_data: 任务数据（JSON 可序列化字典）
        priority: 优先级 (high/normal/low)

    Returns:
        消息 ID（成功时）或 None（失败时）
    """
    stream = _get_stream(priority)
    redis = None
    try:
        redis = await get_redis()
        # 确保 Consumer Group 存在
        try:
            await redis.xgroup_create(stream, CONSUMER_GROUP, mkstream=True)
        except aioredis.ResponseError as e:
            # BUSYGROUP 表示 group 已存在，可以忽略
            if "BUSYGROUP" not in str(e):
                raise

        # 发布消息，限制 Stream 长度避免无限堆积
        msg_id = await redis.xadd(
            stream,
            {"data": json.dumps(task_data)},
            maxlen=10000,
            approximate=True,
        )
        logger.info(
            "Published slice task %s to stream %s (msg_id=%s)",
            task_data.get("task_id", "?"),
            stream,
            msg_id,
        )
        return msg_id
    except Exception as e:
        logger.error(f"Failed to publish slice task to Redis Stream: {e}")
        return None
    finally:
        if redis:
            await redis.close()


async def store_task_callback_token(task_id: str, token: str, ttl_seconds: int = 86400) -> None:
    """保存任务回调/上传鉴权 Token（TTL 与任务超时一致，避免长期残留）。"""
    redis = None
    try:
        redis = await get_redis()
        await redis.setex(f"{TASK_TOKEN_PREFIX}{task_id}", ttl_seconds, token)
    except Exception as e:
        logger.error(f"Failed to store callback token for task {task_id}: {e}")
    finally:
        if redis:
            await redis.close()


async def get_task_callback_token(task_id: str) -> Optional[str]:
    """读取任务回调 Token。"""
    redis = None
    try:
        redis = await get_redis()
        return await redis.get(f"{TASK_TOKEN_PREFIX}{task_id}")
    except Exception as e:
        logger.error(f"Failed to get callback token for task {task_id}: {e}")
        return None
    finally:
        if redis:
            await redis.close()


async def mark_task_cancelled(task_id: str) -> None:
    """写入取消标记到任务 Hash，通知 Worker 端强杀任务。"""
    redis = None
    try:
        redis = await get_redis()
        await redis.hset(f"{TASK_STATUS_PREFIX}{task_id}", mapping={
            "status": "cancelled",
            "cancelled_at": int(datetime.utcnow().timestamp()),
        })
    except Exception as e:
        logger.error(f"Failed to mark task {task_id} as cancelled: {e}")
    finally:
        if redis:
            await redis.close()


async def get_task_redis_status(task_id: str) -> Optional[dict]:
    """从 Redis 查询 Worker 上报的任务状态。

    Worker 会在 Redis Hash `slice:task:{task_id}` 中存储实时状态。

    Returns:
        包含 status, progress, node_id, error 等字段的字典，或 None
    """
    redis = None
    try:
        redis = await get_redis()
        data = await redis.hgetall(f"{TASK_STATUS_PREFIX}{task_id}")
        if not data:
            return None
        return {
            "status": data.get("status"),
            "progress": float(data.get("progress", 0)),
            "node_id": data.get("node_id"),
            "error": data.get("error"),
            "started_at": data.get("started_at"),
            "completed_at": data.get("completed_at"),
        }
    except Exception as e:
        logger.error(f"Failed to get task status from Redis: {e}")
        return None
    finally:
        if redis:
            await redis.close()


async def set_node_enabled(node_id: str, enabled: bool) -> None:
    """设置节点是否启用（管理员在界面上启停节点）。

    值为 0/1 的 Redis String，TTL 设为较长（7 天），Worker 端每次取任务前
    读取该 key 判断是否允许领取新任务；节点保持心跳时也可随时查询。
    """
    redis = None
    try:
        redis = await get_redis()
        await redis.set(
            f"{NODE_ENABLED_PREFIX}{node_id}",
            "1" if enabled else "0",
            ex=7 * 24 * 3600,
        )
    except Exception as e:
        logger.error(f"Failed to set node enabled state for {node_id}: {e}")
    finally:
        if redis:
            await redis.close()


async def is_node_enabled(node_id: str) -> bool:
    """查询节点是否启用（默认启用）。"""
    redis = None
    try:
        redis = await get_redis()
        val = await redis.get(f"{NODE_ENABLED_PREFIX}{node_id}")
        if val is None:
            return True
        return str(val) not in ("0", "false", "False")
    except Exception:
        return True
    finally:
        if redis:
            await redis.close()


async def get_worker_nodes_from_redis(offline_after_seconds: int = 60) -> list[dict]:
    """从 Redis 获取所有 Worker 节点信息（含在线与离线判定）。

    数据契约与 Go Worker 一致：
    - 节点信息写入 Hash `slice:nodes:{node_id}`（含 tags JSON 数组、total_tasks_completed/failed）
    - 节点 Hash 带 TTL（默认 3 倍心跳间隔），TTL 过期后即视为离线
    - 节点正在执行的任务进度从 `slice:task:{task_id}` 的 node_id/progress 字段汇总

    Args:
        offline_after_seconds: 超过该秒数无心跳视为离线
    """
    redis = None
    try:
        redis = await get_redis()
        online_nodes = await redis.smembers("slice:nodes:online")
        now = datetime.utcnow()

        # 汇总每个节点正在运行的任务进度（供 Worker 节点界面展示"工作时进度"）
        node_running: dict[str, list[dict]] = {}
        try:
            async for key in redis.scan_iter(match=f"{TASK_STATUS_PREFIX}*", count=200):
                task_data = await redis.hgetall(key)
                if not task_data:
                    continue
                status = task_data.get("status", "")
                if status not in ("running", "pending"):
                    continue
                nid = task_data.get("node_id", "")
                if not nid:
                    continue
                try:
                    progress = float(task_data.get("progress", 0) or 0)
                except (TypeError, ValueError):
                    progress = 0.0
                node_running.setdefault(nid, []).append({
                    "task_id": key.rsplit(":", 1)[-1],
                    "status": status,
                    "progress": progress,
                })
        except Exception as e:
            logger.warning(f"Failed to scan running tasks from Redis: {e}")

        nodes = []
        for node_id in online_nodes:
            node_data = await redis.hgetall(f"{NODE_KEY_PREFIX}{node_id}")
            if not node_data:
                continue

            # 解析心跳时间，判定在线/离线
            last_hb = node_data.get("last_heartbeat", "")
            status = "online"
            try:
                last_hb_ts = int(last_hb)
                if (now - datetime.utcfromtimestamp(last_hb_ts)) > timedelta(seconds=offline_after_seconds):
                    status = "offline"
            except (ValueError, TypeError, OSError):
                status = "offline"

            try:
                tags = json.loads(node_data.get("tags", "[]"))
            except (ValueError, TypeError):
                tags = []

            # 节点是否启用：管理员在界面上可启停，停用后 Worker 不再领取新任务
            enabled = True
            try:
                enabled_val = await redis.get(f"{NODE_ENABLED_PREFIX}{node_id}")
                if enabled_val is not None:
                    enabled = str(enabled_val) not in ("0", "false", "False")
            except Exception:
                pass

            # 该节点正在运行的任务与平均进度
            running = node_running.get(node_id, [])
            running_progress = 0.0
            if running:
                running_progress = round(
                    sum(t["progress"] for t in running) / len(running), 1
                )

            nodes.append({
                "node_id": node_id,
                "hostname": node_data.get("hostname", ""),
                "ip": node_data.get("ip", ""),
                "os": node_data.get("os", ""),
                "arch": node_data.get("arch", ""),
                "ffmpeg_version": node_data.get("ffmpeg_version", ""),
                "tags": tags,
                "max_concurrent": int(node_data.get("max_concurrent", 2) or 2),
                "current_tasks": int(node_data.get("current_tasks", 0) or 0),
                "total_tasks_completed": int(node_data.get("total_tasks_completed", 0) or 0),
                "total_tasks_failed": int(node_data.get("total_tasks_failed", 0) or 0),
                "status": status,
                "last_heartbeat": node_data.get("last_heartbeat", ""),
                "started_at": node_data.get("started_at", ""),
                "enabled": enabled,
                # 该节点正在运行的任务列表与平均进度（"工作时进度显示"）
                "running_tasks": running,
                "running_progress": running_progress,
            })
        return nodes
    except Exception as e:
        logger.error(f"Failed to get worker nodes from Redis: {e}")
        return []
    finally:
        if redis:
            await redis.close()
