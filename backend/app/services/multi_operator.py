"""多运营者发布服务（方案 v3.1：路由表 + Lua 原子配额 + 端口池 + 幂等 pending）。

实现 Part 2「主题 2/3/4」与 Part 3 的落地点：
- Redis 路由表 `pub:route:<account_id>`：port/profile_dir/operator_id/status/daily_used/
  last_post_at/last_heartbeat/ua_seed/proxy/egress_ip（R12 秒级失效闭环字段）。
- 端口池 `pub:ports`：Lua SADD 原子分配 + 记 owner，基址 9223，重启不漂移（R15）。
- Lua 原子配额双闸门：整号上限 AND 运营者上限 + inflight 并发信号量（nil 兜底 R8，
  inflight 绑定任务自然释放 R22）。
- `_PENDING_TABS` 外移：`pub:pending:<task_id>` 结构化 payload，TTL 30min，幂等重填（R13/R18）。
- 灰度开关 `MULTI_OPERATOR_ENABLED`：false 时 resolve 直取原端口、零侵入旧链路（主题7）。
- cdp_proxy token 注入链路（R19）：app 层签发短期 token，随 payload 下发。

本模块为纯后端基础能力，被 publish API / celery worker 调用；不引入浏览器层改动。
"""

import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# ---- Redis key 前缀 ----
ROUTE_PREFIX = "pub:route:"            # hash：<account_id> -> 路由详情
PORTS_KEY = "pub:ports"                # set：已分配端口池
PENDING_PREFIX = "pub:pending:"        # string(json)：<task_id> -> 结构化 payload
QUOTA_ACCT_PREFIX = "pub:acct_used:"   # hash：<acct_id> -> daily_used
QUOTA_OP_PREFIX = "pub:op_used:"       # string：<operator_id> -> daily_used
INFLIGHT_OP_PREFIX = "pub:op_inflight:"  # string：<operator_id> -> 进行中计数
INFLIGHT_GLOBAL = "pub:global_inflight"  # string：全局进行中计数
ROUTE_LOCK_PREFIX = "pub:lock:"        # 分布式锁：端口分配/路由写

# 端口池基址（对齐 start_chromium.sh 现状 9223）
PORT_BASE = 9223
# 心跳窗口：watcher 10s 探测 /json/version，连续 2 次失败置 expired（R12）
HEARTBEAT_TIMEOUT = 20

# 灰度开关 key（Redis 热更，主题7）
FLAG_KEY = "MULTI_OPERATOR_ENABLED"


# ---- Lua 原子配额脚本（主题2，含 nil 兜底 R8；inflight 跨日语义 R22） ----
# KEYS[1]=acct, KEYS[2]=op_used, KEYS[3]=op_inflight, KEYS[4]=global_inflight
# ARGV[1]=acct_limit, ARGV[2]=op_limit, ARGV[3]=op_inflight_limit,
# ARGV[4]=global_inflight_limit, ARGV[5]=acct_ttl, ARGV[6]=inflight_ttl
QUOTA_LUA = """
local acct_used = tonumber(redis.call('HGET', KEYS[1], 'daily_used')) or 0
local op_used   = tonumber(redis.call('GET',  KEYS[2])) or 0
local op_inf    = tonumber(redis.call('GET',  KEYS[3])) or 0
local g_inf     = tonumber(redis.call('GET',  KEYS[4])) or 0
if (acct_used + 1 > tonumber(ARGV[1])) then return 0 end
if (op_used   + 1 > tonumber(ARGV[2])) then return 0 end
if (op_inf    + 1 > tonumber(ARGV[3])) then return 0 end
if (g_inf     + 1 > tonumber(ARGV[4])) then return 0 end
redis.call('HINCRBY', KEYS[1], 'daily_used', 1)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
redis.call('INCR', KEYS[3]); redis.call('EXPIRE', KEYS[3], tonumber(ARGV[6]))
redis.call('INCR', KEYS[4]); redis.call('EXPIRE', KEYS[4], tonumber(ARGV[6]))
return 1
"""

# 释放 inflight（任务成功/失败/超时/死信均调用，R22）
RELEASE_INFLIGHT_LUA = """
local op_inf = tonumber(redis.call('GET', KEYS[1])) or 0
if op_inf > 0 then redis.call('DECR', KEYS[1]) end
local g_inf = tonumber(redis.call('GET', KEYS[2])) or 0
if g_inf > 0 then redis.call('DECR', KEYS[2]) end
return 1
"""

# 端口池原子分配：SADD 一个未占用的端口并记 owner（R15）
ALLOC_PORT_LUA = """
local port = tonumber(ARGV[1])
local owner = ARGV[2]
local ok = redis.call('SADD', KEYS[1], port)
if ok == 0 then return 0 end  -- 端口已占用
redis.call('HSET', KEYS[2], tostring(port), owner)
return port
"""


def _redis() -> aioredis.Redis:
    """创建 Redis 连接（解码为 str，便于 JSON 处理）。"""
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def multi_operator_enabled() -> bool:
    """读取灰度开关（Redis 热更；缺省 false 走旧链路，零侵入）。"""
    r = _redis()
    try:
        val = await r.get(FLAG_KEY)
        return val in ("1", "true", "True")
    finally:
        await r.close()


async def set_flag(enabled: bool) -> None:
    r = _redis()
    try:
        await r.set(FLAG_KEY, "1" if enabled else "0")
    finally:
        await r.close()


async def resolve_port(account_id) -> Optional[int]:
    """根据账号解析发布端口。

    灰度关闭（flag=false）时返回 None，调用方回退读取 PublishProfile.chrome_debug_port
    （零侵入旧链路）；开启时读 Redis 路由表 port。
    """
    if not await multi_operator_enabled():
        return None
    r = _redis()
    try:
        route = await r.hgetall(f"{ROUTE_PREFIX}{account_id}")
        if not route:
            return None
        port = int(route.get("port") or 0)
        status = route.get("status")
        # 非 ready 状态（expired/disabled/graduating）不参与调度
        if status != "ready":
            return None
        return port
    finally:
        await r.close()


async def get_route(account_id) -> Optional[dict]:
    r = _redis()
    try:
        raw = await r.hgetall(f"{ROUTE_PREFIX}{account_id}")
        return raw or None
    finally:
        await r.close()


async def register_route(account_id, port: int, profile_dir: str, operator_id,
                         ua_seed: Optional[str] = None, proxy: Optional[str] = None,
                         egress_ip: Optional[str] = None) -> None:
    """Profile enabled 即写路由（status=logging），端口/目录持久化（重启不漂移，R15）。"""
    r = _redis()
    try:
        key = f"{ROUTE_PREFIX}{account_id}"
        await r.hset(key, mapping={
            "port": port,
            "profile_dir": profile_dir,
            "operator_id": str(operator_id) if operator_id else "",
            "status": "logging",
            "daily_used": "0",
            "last_post_at": "",
            "last_heartbeat": str(int(time.time())),
            "ua_seed": ua_seed or "",
            "proxy": proxy or "",
            "egress_ip": egress_ip or "",
        })
    finally:
        await r.close()


async def alloc_port(profile_id) -> Optional[int]:
    """从端口池原子分配一个空闲端口（基址 9223+N），记 owner=profile_id。"""
    r = _redis()
    try:
        # 循环尝试 9223..9223+50
        for n in range(0, 51):
            port = PORT_BASE + n
            result = await r.eval(ALLOC_PORT_LUA, 2, PORTS_KEY, f"{ROUTE_LOCK_PREFIX}ports", port, str(profile_id))
            if result and int(result) > 0:
                return port
        return None
    finally:
        await r.close()


async def mark_heartbeat(account_id) -> None:
    """更新路由表 last_heartbeat（watcher 探活成功后调用，R12）。"""
    r = _redis()
    try:
        key = f"{ROUTE_PREFIX}{account_id}"
        if await r.exists(key):
            await r.hset(key, "last_heartbeat", str(int(time.time())))
    finally:
        await r.close()


async def mark_expired(account_id) -> None:
    """Chromium 探活失败置 expired（R12：调度跳过，不等 30min 心跳）。"""
    r = _redis()
    try:
        await r.hset(f"{ROUTE_PREFIX}{account_id}", "status", "expired")
    finally:
        await r.close()


async def set_ready(account_id) -> None:
    r = _redis()
    try:
        await r.hset(f"{ROUTE_PREFIX}{account_id}", "status", "ready")
    finally:
        await r.close()


def _seconds_until_midnight() -> int:
    now = datetime.utcnow()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


async def acquire_quota(account_id, operator_id, acct_limit: int, op_limit: int,
                        op_inflight_limit: int = 1, global_inflight_limit: int = 4,
                        inflight_ttl: int = 1800) -> bool:
    """Lua 原子 check+扣减 配额双闸门 + inflight 信号量。

    先抢 op 再抢 global，释放逆序（R22：inflight 绑定任务，随任务结束自然释放）。
    返回 True 表示取得配额并已占用一个并发 slot；调用方须在任务结束时调用 release_inflight。
    """
    r = _redis()
    try:
        acct_key = f"{QUOTA_ACCT_PREFIX}{account_id}"
        op_key = f"{QUOTA_OP_PREFIX}{operator_id}"
        op_inf_key = f"{INFLIGHT_OP_PREFIX}{operator_id}"
        ttl = _seconds_until_midnight()
        ok = await r.eval(
            QUOTA_LUA,
            4,
            acct_key, op_key, op_inf_key, INFLIGHT_GLOBAL,
            acct_limit, op_limit, op_inflight_limit, global_inflight_limit,
            ttl, inflight_ttl,
        )
        return bool(ok)
    finally:
        await r.close()


async def release_inflight(operator_id) -> None:
    """任务结束释放 inflight slot（R22：成功/失败/超时/死信均调用，跨日不误顶）。"""
    r = _redis()
    try:
        op_inf_key = f"{INFLIGHT_OP_PREFIX}{operator_id}"
        await r.eval(RELEASE_INFLIGHT_LUA, 2, op_inf_key, INFLIGHT_GLOBAL)
    finally:
        await r.close()


async def get_daily_used(account_id) -> int:
    r = _redis()
    try:
        val = await r.hget(f"{QUOTA_ACCT_PREFIX}{account_id}", "daily_used")
        return int(val or 0)
    finally:
        await r.close()


# ---- 幂等 pending（主题4：_PENDING_TABS 外移 Redis，R13/R18） ----


async def save_pending(task_id, payload: dict, ttl: int = 1800) -> None:
    """保存结构化 payload（不含 page 对象），TTL 30min。"""
    r = _redis()
    try:
        await r.setex(f"{PENDING_PREFIX}{task_id}", ttl, json.dumps(payload))
    finally:
        await r.close()


async def get_pending(task_id) -> Optional[dict]:
    r = _redis()
    try:
        raw = await r.get(f"{PENDING_PREFIX}{task_id}")
        return json.loads(raw) if raw else None
    finally:
        await r.close()


async def delete_pending(task_id) -> None:
    r = _redis()
    try:
        await r.delete(f"{PENDING_PREFIX}{task_id}")
    finally:
        await r.close()


# ---- cdp_proxy token（R19：app 层签发短期 token，随 payload 下发） ----


async def issue_cdp_token(actor_id, account_id, ttl: int = 60) -> str:
    """签发短期 cdp_proxy 访问 token（actor+account+单次 scope，防重放）。"""
    token = secrets.token_urlsafe(24)
    payload = {
        "token": token,
        "actor_id": str(actor_id),
        "account_id": str(account_id),
        "issued_at": int(time.time()),
        "exp": int(time.time()) + ttl,
    }
    r = _redis()
    try:
        await r.setex(f"pub:cdp_token:{token}", ttl, json.dumps(payload))
    finally:
        await r.close()
    return token


async def verify_cdp_token(token: str, account_id) -> bool:
    """校验 cdp_proxy token：存在、未过期、account 匹配。校验即消费（单次）。"""
    r = _redis()
    try:
        key = f"pub:cdp_token:{token}"
        raw = await r.get(key)
        if not raw:
            return False
        data = json.loads(raw)
        if int(data.get("exp") or 0) < int(time.time()):
            await r.delete(key)
            return False
        if str(data.get("account_id")) != str(account_id):
            return False
        # 单次 scope：校验通过即删除，防重放（R19）
        await r.delete(key)
        return True
    finally:
        await r.close()
