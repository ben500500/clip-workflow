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
# 字幕专用 Stream：仅「具备字幕烧录能力」的节点（163 Linux worker，ffmpeg 带 libass）
# 消费此流；Mac worker 只读默认的 high/normal/low 三个流，永远不会领取字幕任务，
# 从根本上避免 Mac ffmpeg 缺 libass 导致字幕烧录失败（退出码 1）。
STREAM_SUBTITLE = "slice:tasks:subtitle"

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

# 节点 CPU 分配比例控制 key：值为 1~100 的百分比，Worker 端每次取任务前读取
# （与 worker.json 中 cpu_percent 一致，优先取该 key 实现运行时动态调整）
NODE_CPU_PERCENT_PREFIX = "slice:node-cpu-percent:"

# 节点引擎更新指令 key：值为 JSON {target_version, requested_at}，
# 服务器推送更新时写入，Worker 端在心跳循环中检测到目标版本与本地不一致时
# 自动从后端拉取引擎更新包并替换本地 engines/ 目录（无需重新部署/重启）。
NODE_UPDATE_PREFIX = "slice:node-update:"


def _get_stream(priority: str = "normal") -> str:
    """根据优先级返回对应的 Stream 名称。

    priority="subtitle" 走独立的字幕专用流，仅具备字幕烧录能力的节点消费。
    """
    return {
        "high": STREAM_HIGH,
        "normal": STREAM_NORMAL,
        "low": STREAM_LOW,
        "subtitle": STREAM_SUBTITLE,
    }.get(priority, STREAM_NORMAL)


def _parse_str_list(raw: str) -> list:
    """解析节点能力等 JSON 字符串字段为列表（容错）。

    Go Worker 在 Redis Hash 中写入的是 JSON 数组字符串（如 `["h264_nvenc"]`），
    读取时统一用本函数解析；解析失败回退为空列表。
    """
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []


# 模块级共享 Redis 客户端（懒加载单例）。
# from_url 底层自带连接池，复用同一实例可避免每个函数反复建池/销毁，
# 消除高频路径（取任务状态 / 发布任务）的连接建立与释放开销。
_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """获取共享 Redis 连接（懒加载单例，复用连接池）。

    首次调用创建实例，后续复用；连接由进程生命周期统一管理，
    各调用方无需也不应主动 close（close 会关闭共享连接池）。
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_client


def reset_redis_client() -> None:
    """测试/重置用：清空共享客户端引用（仅在应用关闭或测试时调用）。"""
    global _redis_client
    _redis_client = None


async def publish_slice_task(task_data: dict, priority: str = "normal") -> Optional[str]:
    """将切片任务发布到 Redis Stream。

    Args:
        task_data: 任务数据（JSON 可序列化字典）
        priority: 优先级 (high/normal/low)

    Returns:
        消息 ID（成功时）或 None（失败时）
    """
    stream = _get_stream(priority)
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


async def store_task_callback_token(task_id: str, token: str, ttl_seconds: int = 86400) -> None:
    """保存任务回调/上传鉴权 Token（TTL 与任务超时一致，避免长期残留）。"""
    try:
        redis = await get_redis()
        await redis.setex(f"{TASK_TOKEN_PREFIX}{task_id}", ttl_seconds, token)
    except Exception as e:
        logger.error(f"Failed to store callback token for task {task_id}: {e}")


async def get_task_callback_token(task_id: str) -> Optional[str]:
    """读取任务回调 Token。"""
    try:
        redis = await get_redis()
        return await redis.get(f"{TASK_TOKEN_PREFIX}{task_id}")
    except Exception as e:
        logger.error(f"Failed to get callback token for task {task_id}: {e}")
        return None


async def mark_task_cancelled(task_id: str) -> None:
    """写入取消标记到任务 Hash，通知 Worker 端强杀任务。"""
    try:
        redis = await get_redis()
        key = f"{TASK_STATUS_PREFIX}{task_id}"
        await redis.hset(key, mapping={
            "status": "cancelled",
            "cancelled_at": int(datetime.utcnow().timestamp()),
        })
        # cancelled 也设置 TTL：排队中未认领就被取消的任务不会经过 Worker 终态
        # 处理（没有 ExpireTaskStatus），需在此兜底，避免 hash 永久残留
        await redis.expire(key, 7 * 24 * 3600)
    except Exception as e:
        logger.error(f"Failed to mark task {task_id} as cancelled: {e}")


async def remove_slice_task_from_streams(task_id: str) -> None:
    """从所有切片任务 Stream（含消费者组 PEL）中移除指定任务的残留消息。

    Worker 通过 Redis Stream 消费切片任务：任务消息发布到 high/normal/low/
    subtitle 四个流后，Worker 用 XReadGroup 读取进入消费者组 PEL（Pending
    Entries List），任务完成才 XAck 移除。若删除任务时不清理这些消息，残留
    消息会成为「队列炸弹」：Worker 读到已删除任务的 task_id 后再查 DB 会落空
    或反复重试，长期阻塞 Worker。本函数遍历所有流，把 payload 中 task_id
    匹配的消息同时从主 Stream 和消费者组 PEL 中移除。
    """
    try:
        redis = await get_redis()
        # task_id 在 JSON payload 中以带引号的字符串出现，精确匹配整串避免误删
        needle = f'"task_id": "{task_id}"'
        for stream in (STREAM_HIGH, STREAM_NORMAL, STREAM_LOW, STREAM_SUBTITLE):
            try:
                # 1) 分页扫描主 Stream，收集 payload 含该 task_id 的消息 ID
                ids_to_del: list[str] = []
                start = "-"
                while True:
                    batch = await redis.xrange(stream, min=start, max="+", count=200)
                    if not batch:
                        break
                    for mid, fields in batch:
                        data = fields.get("data", "")
                        if isinstance(data, str) and needle in data:
                            ids_to_del.append(mid)
                    last_id = batch[-1][0]
                    # 以「(上一批最后一条 ID」作为排他起点翻页
                    start = f"({last_id}"
                    if len(batch) < 200:
                        break

                if ids_to_del:
                    await redis.xdel(stream, *ids_to_del)
                    # 2) 同时从消费者组 PEL 中 XAck，避免 Worker 侧仍挂着残留
                    try:
                        group_infos = await redis.xinfo_groups(stream)
                        for gi in group_infos:
                            gname = gi.get("name")
                            if gname:
                                await redis.xack(stream, gname, *ids_to_del)
                    except Exception as e:
                        logger.debug("No consumer group to ack on %s: %s", stream, e)
                    logger.info(
                        "Removed %d pending stream message(s) for slice task %s from %s",
                        len(ids_to_del), task_id, stream,
                    )
            except Exception as e:
                logger.warning("Failed to clean stream %s for task %s: %s", stream, task_id, e)
    except Exception as e:
        logger.error(f"Failed to remove slice task {task_id} from Redis streams: {e}")


async def get_task_redis_status(task_id: str) -> Optional[dict]:
    """从 Redis 查询 Worker 上报的任务状态。

    Worker 会在 Redis Hash `slice:task:{task_id}` 中存储实时状态。

    Returns:
        包含 status, progress, node_id, error 等字段的字典，或 None
    """
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


async def set_node_enabled(node_id: str, enabled: bool) -> None:
    """设置节点是否启用（管理员在界面上启停节点）。

    值为 0/1 的 Redis String，TTL 设为较长（7 天），Worker 端每次取任务前
    读取该 key 判断是否允许领取新任务；节点保持心跳时也可随时查询。
    """
    try:
        redis = await get_redis()
        await redis.set(
            f"{NODE_ENABLED_PREFIX}{node_id}",
            "1" if enabled else "0",
            ex=7 * 24 * 3600,
        )
    except Exception as e:
        logger.error(f"Failed to set node enabled state for {node_id}: {e}")


async def is_node_enabled(node_id: str) -> bool:
    """查询节点是否启用（默认启用）。"""
    try:
        redis = await get_redis()
        val = await redis.get(f"{NODE_ENABLED_PREFIX}{node_id}")
        if val is None:
            return True
        return str(val) not in ("0", "false", "False")
    except Exception:
        return True


async def set_node_cpu_percent(node_id: str, percent: int) -> None:
    """设置节点 CPU 资源分配比例（1~100）。

    写入 Redis 控制 key（TTL 7 天），Worker 端每次领取任务前读取并应用，
    实现无需重启的运行时动态调整。
    """
    percent = max(1, min(100, int(percent)))
    try:
        redis = await get_redis()
        await redis.set(
            f"{NODE_CPU_PERCENT_PREFIX}{node_id}",
            str(percent),
            ex=7 * 24 * 3600,
        )
    except Exception as e:
        logger.error(f"Failed to set node cpu percent for {node_id}: {e}")


async def get_node_cpu_percent(node_id: str, default: int = 50) -> int:
    """查询节点 CPU 资源分配比例（默认 50）。"""
    try:
        redis = await get_redis()
        val = await redis.get(f"{NODE_CPU_PERCENT_PREFIX}{node_id}")
        if val is None:
            return default
        try:
            return max(1, min(100, int(val)))
        except (TypeError, ValueError):
            return default
    except Exception:
        return default


async def delete_worker_node(node_id: str) -> bool:
    """删除 Worker 节点（废弃节点清理）。

    清理该节点在 Redis 中的全部痕迹：
    - 节点信息 Hash `slice:nodes:{node_id}`
    - 在线集合 `slice:nodes:online` 中的成员
    - 该节点名下的标签集合 `slice:nodes:tag:{tag}`
    - 节点启停控制 key、CPU 控制 key
    - 该节点正在运行的任务状态 Hash（强制清理，避免悬挂）

    返回是否成功。
    """
    try:
        redis = await get_redis()
        # 读取节点 Hash 获取标签，用于清理标签集合
        node_data = await redis.hgetall(f"{NODE_KEY_PREFIX}{node_id}")
        try:
            tags = json.loads(node_data.get("tags", "[]"))
        except (ValueError, TypeError):
            tags = []

        pipe = redis.pipeline()
        # 删除节点信息 Hash
        pipe.delete(f"{NODE_KEY_PREFIX}{node_id}")
        # 从在线集合移除
        pipe.srem("slice:nodes:online", node_id)
        # 删除标签集合中的该节点
        for tag in tags:
            pipe.srem(f"slice:nodes:tag:{tag}", node_id)
        # 删除启停/CPU 控制 key
        pipe.delete(f"{NODE_ENABLED_PREFIX}{node_id}")
        pipe.delete(f"{NODE_CPU_PERCENT_PREFIX}{node_id}")
        # 清理该节点正在运行的任务状态 Hash
        async for key in redis.scan_iter(match=f"{TASK_STATUS_PREFIX}*", count=200):
            task_data = await redis.hgetall(key)
            if task_data.get("node_id", "") == node_id:
                pipe.delete(key)
        await pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Failed to delete worker node {node_id} from Redis: {e}")
        return False


async def get_worker_nodes_from_redis(offline_after_seconds: int = 60) -> list[dict]:
    """从 Redis 获取所有 Worker 节点信息（含在线与离线判定）。

    数据契约与 Go Worker 一致：
    - 节点信息写入 Hash `slice:nodes:{node_id}`（含 tags JSON 数组、total_tasks_completed/failed）
    - 节点 Hash 带 TTL（默认 3 倍心跳间隔），TTL 过期后即视为离线
    - 节点正在执行的任务进度从 `slice:task:{task_id}` 的 node_id/progress 字段汇总

    Args:
        offline_after_seconds: 超过该秒数无心跳视为离线
    """
    try:
        redis = await get_redis()
        online_nodes = await redis.smembers("slice:nodes:online")
        now = datetime.utcnow()

        # 汇总每个节点正在运行的任务进度（供 Worker 节点界面展示"工作时进度"）
        node_running: dict[str, list[dict]] = {}
        try:
            async for key in redis.scan_iter(match=f"{TASK_STATUS_PREFIX}*", count=200):
                # 同一前缀下还存在非任务状态的 key：回调 Token `slice:task:token:*`
                # 与 Worker 互斥租约 `slice:task:lease:*`（均为 string 类型）。
                # 对它们执行 HGETALL 会抛 WRONGTYPE 并中断整个扫描循环，导致
                # 「运行中任务」面板永远为空，这里显式跳过。
                if key.startswith(TASK_TOKEN_PREFIX) or key.startswith(f"{TASK_STATUS_PREFIX}lease:"):
                    continue
                try:
                    task_data = await redis.hgetall(key)
                except Exception:
                    # 单个 key 类型异常只跳过该 key，不中断整个扫描
                    continue
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
                # 阶段与任务模式（供 Worker 节点界面展示"当前在处理什么"）
                phase = task_data.get("phase", "") or ""
                mode = task_data.get("mode", "") or ""
                node_running.setdefault(nid, []).append({
                    "task_id": key.rsplit(":", 1)[-1],
                    "status": status,
                    "progress": progress,
                    "phase": phase,
                    "mode": mode,
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

            # 节点 CPU 资源分配比例：优先取控制 key（运行时动态调整），否则取配置默认
            cpu_percent = 50
            try:
                cpu_val = await redis.get(f"{NODE_CPU_PERCENT_PREFIX}{node_id}")
                if cpu_val is not None:
                    cpu_percent = max(1, min(100, int(cpu_val)))
                else:
                    node_cpu = node_data.get("cpu_percent", "")
                    if node_cpu:
                        cpu_percent = max(1, min(100, int(node_cpu)))
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
                # 该节点 CPU 资源分配比例（%）
                "cpu_percent": cpu_percent,
                # 该节点正在运行的任务列表与平均进度（"工作时进度显示"）
                "running_tasks": running,
                "running_progress": running_progress,
                # 该节点当前引擎版本（心跳上报；用于判断是否需要推送更新）
                "engine_version": node_data.get("engine_version", "") or "",
                # 该节点硬件编码能力（如 h264_nvenc/hevc_nvenc 等；预留 GPU 节点自动分派接口）
                "encoder_capabilities": _parse_str_list(node_data.get("encoder_capabilities", "")),
            })
        return nodes
    except Exception as e:
        logger.error(f"Failed to get worker nodes from Redis: {e}")
        return []


async def set_node_update_command(node_id: str, target_version: str) -> bool:
    """向指定节点下发引擎更新指令。

    写入 Redis 指令 key `slice:node-update:{node_id}`，值为
    `{target_version, requested_at}`。Worker 端在心跳循环中检测到目标版本
    与本地引擎版本不一致时，会从后端拉取引擎更新包并替换本地 engines/ 目录，
    实现无需重新部署的引擎更新推送。

    Args:
        node_id: 目标节点 ID。
        target_version: 服务器端当前引擎版本（由 /workers/engines/status 计算）。

    Returns:
        是否写入成功。
    """
    try:
        redis = await get_redis()
        payload = json.dumps({
            "target_version": target_version,
            "requested_at": datetime.utcnow().isoformat(),
        })
        await redis.set(
            f"{NODE_UPDATE_PREFIX}{node_id}",
            payload,
            ex=24 * 3600,  # 指令 TTL 1 天，节点离线过久则指令过期（在线后管理员可重推）
        )
        return True
    except Exception as e:
        logger.error(f"Failed to set node update command for {node_id}: {e}")
        return False


async def get_node_update_command(node_id: str) -> Optional[dict]:
    """读取节点当前的引擎更新指令（供界面展示推送状态/目标版本）。"""
    try:
        redis = await get_redis()
        val = await redis.get(f"{NODE_UPDATE_PREFIX}{node_id}")
        if not val:
            return None
        return json.loads(val)
    except Exception:
        return None


async def clear_node_update_command(node_id: str) -> None:
    """清除节点的引擎更新指令（Worker 成功应用更新后调用，避免重复拉取）。"""
    try:
        redis = await get_redis()
        await redis.delete(f"{NODE_UPDATE_PREFIX}{node_id}")
    except Exception:
        pass
