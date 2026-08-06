"""Redis Stream 服务：发布切片任务到 Worker 节点的队列。"""

import json
import logging
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


async def get_worker_nodes_from_redis() -> list[dict]:
    """从 Redis 获取所有在线 Worker 节点信息。"""
    redis = None
    try:
        redis = await get_redis()
        # 获取在线节点集合
        online_nodes = await redis.smembers("slice:nodes:online")
        nodes = []
        for node_id in online_nodes:
            node_data = await redis.hgetall(f"slice:nodes:{node_id}")
            if node_data:
                nodes.append({
                    "node_id": node_id,
                    "hostname": node_data.get("hostname", ""),
                    "ip": node_data.get("ip", ""),
                    "os": node_data.get("os", ""),
                    "arch": node_data.get("arch", ""),
                    "ffmpeg_version": node_data.get("ffmpeg_version", ""),
                    "tags": json.loads(node_data.get("tags", "[]")),
                    "max_concurrent": int(node_data.get("max_concurrent", 2)),
                    "current_tasks": int(node_data.get("current_tasks", 0)),
                    "status": node_data.get("status", "online"),
                    "last_heartbeat": node_data.get("last_heartbeat", ""),
                    "started_at": node_data.get("started_at", ""),
                })
        return nodes
    except Exception as e:
        logger.error(f"Failed to get worker nodes from Redis: {e}")
        return []
    finally:
        if redis:
            await redis.close()