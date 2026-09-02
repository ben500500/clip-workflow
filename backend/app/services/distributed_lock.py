"""分布式锁：基于 Redis SET NX EX + Lua 校验释放，防止同一资源被并发重复触发。

背景（2026-09-02 事故）：用户对同一剧集快速触发两次 AI 选点，两个 Celery 任务
并发执行，后收尾的僵尸任务把先收尾任务的候选片段清空、状态覆盖为 failed。
此类「后收尾覆盖先收尾」竞态的通用解法即资源维度互斥锁。

使用模式（入口拿锁 → 任务透传 token → 任务 finally 释放）：
    # API 入口
    lock_key = f"autoclip:lock:{episode_id}"
    lock_token = await acquire_lock(lock_key, ttl=1800)
    if not lock_token:
        raise HTTPException(status_code=409, detail="已有任务在运行中")
    some_task.delay(..., lock_token=lock_token)   # dispatch 失败需自行 release

    # Celery 任务体
    try:
        ...
    finally:
        if lock_token:
            await release_lock(lock_key, lock_token)

安全性：
- SET NX 保证同一时刻只有一个持有者；EX 兜底（持有方崩溃后锁自动过期，不会死锁）；
- 释放用 Lua compare-and-delete，只删自己的锁，防止误删他人锁（如自己的锁
  已过期被他人持有后，旧的延迟释放请求不会误删）。
"""

import uuid
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

# 仅当锁的值等于自己的 token 时才删除（防误删他人锁）
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_client: Optional[aioredis.Redis] = None


def _get_client() -> aioredis.Redis:
    """进程内共享连接池（与 redis_stream 一致：由进程生命周期统一管理）。"""
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def acquire_lock(key: str, ttl: int = 1800) -> Optional[str]:
    """尝试获取分布式锁。

    成功返回锁 token（调用方持有，用于释放）；已被占用返回 None。
    ttl 为锁自动过期秒数——必须覆盖任务最长执行时长，作为持有方崩溃时的兜底。
    """
    token = uuid.uuid4().hex
    ok = await _get_client().set(key, token, nx=True, ex=int(ttl))
    return token if ok else None


async def release_lock(key: str, token: str) -> bool:
    """释放锁：仅当值等于自己的 token 时删除。返回是否确实由本次释放。"""
    try:
        result = await _get_client().eval(_RELEASE_LUA, 1, key, token)
        return bool(result)
    except Exception:
        # 释放失败不影响主流程：锁最终由 EX 兜底过期
        return False
