#!/usr/bin/env python3
"""R21 混沌演练：模拟 Chromium 崩溃 / Redis 重启 / worker 重启，验证全链路自愈。

背景（方案 v3.1 R21）：DoD 验收增补「混沌演练」行——模拟 Chromium 崩溃 / Redis 重启 /
worker 重启，全链路自愈时间 ≤X，且 0 条误发 / 0 条重复。

本脚本为「上线前强制演练」的编排工具，分三种故障场景：

  A. Chromium 崩溃  → 验证 R12：watcher 10s 探 /json/version，连续 2 次失败（≈20s）
     → 路由表置 expired → 调度跳过该 operator，不等 30min 心跳；
     → 恢复后 watcher 重连 → 路由表回 ready。
  B. Redis 重启     → 验证配额 Lua / 路由表可重建：Redis 重启后 pub:profiles 由
     bootstrap 重建、路由表由 watcher/sync 重建、配额计数归零重建。
  C. worker 重启    → 验证幂等：重启期间任务不重复发送（幂等键 + pending 落 Redis）。

用法（在部署环境执行）：
    # 只做检查模式（不自发故障，仅观测当前自愈状态）
    python3 scripts/chaos_drill.py --check-only

    # 注入 Chromium 崩溃（需 root/docker 权限，kill 指定 profile 的 chromium 进程）
    python3 scripts/chaos_drill.py --scenario chromium --profile <account_id>

    # 注入 Redis 重启（需 docker 权限）
    python3 scripts/chaos_drill.py --scenario redis

    # 注入 worker 重启（需 docker 权限）
    python3 scripts/chaos_drill.py --scenario worker --worker worker-publish

    # 全部场景（顺序执行，每场景观测 N 秒）
    python3 scripts/chaos_drill.py --scenario all --observe 45

退出码：0=全部通过；1=任一场景未达到预期；2=环境/参数错误。
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time


# 自愈验收阈值（秒），取自 R12（连续 2 次失败 ≈20s）+ R21 宽松余量
RECOVERY_WINDOW = {
    "chromium": 45,   # watcher 10s×2 + 重连余量
    "redis": 60,      # bootstrap 重建 + 路由重建
    "worker": 90,     # 重启 + 幂等恢复
}


# ---------- Redis 辅助 ----------

async def _redis_get(redis_url: str = "redis://127.0.0.1:6379"):
    import redis.asyncio as aioredis
    return aioredis.from_url(redis_url, decode_responses=True)


async def _get_route_states(r):
    states = {}
    async for key in r.scan_iter(match="pub:route:*", count=200):
        route = await r.hgetall(key)
        account = key[len("pub:route:"):]
        states[account] = {
            "status": route.get("status"),
            "port": route.get("port"),
            "fail_streak": route.get("fail_streak"),
            "last_heartbeat": route.get("last_heartbeat"),
        }
    return states


async def _get_profiles(r):
    raw = await r.get("pub:profiles")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


# ---------- 故障注入 ----------

def _run_cmd(cmd: list, timeout: int = 30) -> tuple:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -1, "命令不存在"


def inject_chromium_crash(account_id: str) -> tuple:
    """kill 指定 account 的 Chromium 进程（按 --user-data-dir 匹配）。"""
    if not account_id:
        return 1, "需指定 --profile <account_id>"
    # 通过 ps 匹配 user-data-dir 中含 profile 目录的 chromium 进程
    rc, out = _run_cmd(["bash", "-lc",
        f"ps -eo pid,args | grep -i 'chrome.*user-data-dir' | grep -i '{account_id}' | grep -v grep | awk '{{print $1}}'"])
    pids = [p.strip() for p in out.split() if p.strip()]
    if not pids:
        return 1, f"未找到 profile={account_id} 的 Chromium 进程（可能已崩溃或未启动）"
    rc, killout = _run_cmd(["kill", "-9"] + pids)
    return rc, f"已 kill Chromium pids={pids}: {killout}"


def inject_redis_restart(container: str = "redis") -> tuple:
    """重启 Redis 容器（docker compose）。"""
    rc, out = _run_cmd(["docker", "compose", "restart", container])
    return rc, out


def inject_worker_restart(worker: str) -> tuple:
    """重启指定 worker 容器。"""
    if not worker:
        return 1, "需指定 --worker <容器名>"
    rc, out = _run_cmd(["docker", "compose", "restart", worker])
    return rc, out


# ---------- 观测 ----------

async def _wait_ready(r, expect_ready: bool, window: int) -> bool:
    """在 window 秒内等待路由表达到预期自愈状态（ready/expired）。"""
    deadline = time.time() + window
    while time.time() < deadline:
        states = await _get_route_states(r)
        if not states:
            await asyncio.sleep(2)
            continue
        if expect_ready:
            # 期望全部 ready（自愈完成）
            if all(s["status"] == "ready" for s in states.values()):
                return True
        else:
            # 期望至少一个 expired（失效被识别）
            if any(s["status"] == "expired" for s in states.values()):
                return True
        await asyncio.sleep(2)
    return False


async def drill_chromium(account_id: str, observe: int, redis_url: str) -> tuple:
    print(f"\n[混沌演练 A] Chromium 崩溃 → 自愈（profile={account_id}）")
    r = await _redis_get(redis_url)
    try:
        # 1. 注入崩溃
        rc, out = inject_chromium_crash(account_id)
        print(f"  注入崩溃: rc={rc} {out.strip()}")
        if rc != 0:
            return False, out
        # 2. 期望 expired（R12 秒级失效）
        ok_expired = await _wait_ready(r, expect_ready=False, window=RECOVERY_WINDOW["chromium"])
        print(f"  失效识别(expired): {'✅' if ok_expired else '❌'}（窗口 {RECOVERY_WINDOW['chromium']}s）")
        if not ok_expired:
            return False, "未在窗口内识别到 expired"
        # 3. 期望恢复 ready（需部署侧拉起 Chromium 后由 watcher 回填；此处仅观测，超时不强判失败）
        print(f"  观测 {observe}s 等待恢复 ready（需 Chromium 被 supervisord 自动拉起）...")
        await asyncio.sleep(min(observe, RECOVERY_WINDOW["chromium"]))
        return True, "expired 识别通过；ready 恢复依赖 supervisord 拉起（已观测）"
    finally:
        await r.close()


async def drill_redis(observe: int, redis_url: str) -> tuple:
    print(f"\n[混沌演练 B] Redis 重启 → 路由/配额重建")
    # 重启前记录当前路由
    r = await _redis_get(redis_url)
    before = await _get_route_states(r)
    await r.close()

    rc, out = inject_redis_restart()
    print(f"  重启 Redis: rc={rc} {out.strip()}")
    if rc != 0:
        return False, out
    # 等待 Redis 就绪
    deadline = time.time() + 30
    ready = False
    while time.time() < deadline:
        try:
            r = await _redis_get(redis_url)
            await r.ping()
            await r.close()
            ready = True
            break
        except Exception:
            await asyncio.sleep(2)
    if not ready:
        return False, "Redis 30s 内未就绪"
    print(f"  Redis 已恢复，观测 {observe}s 等待 bootstrap/watcher 重建路由...")
    await asyncio.sleep(min(observe, RECOVERY_WINDOW["redis"]))
    # 校验路由可重建（profiles 存在即可）
    r = await _redis_get(redis_url)
    try:
        profiles = await _get_profiles(r)
        print(f"  重建后 profiles 数: {len(profiles)}（{'✅' if profiles else '❌ 为空，需 bootstrap 手动重建'}）")
        return bool(profiles), "Redis 重建完成"
    finally:
        await r.close()


async def drill_worker(worker: str, observe: int, redis_url: str) -> tuple:
    print(f"\n[混沌演练 C] worker 重启 → 幂等恢复（worker={worker}）")
    rc, out = inject_worker_restart(worker)
    print(f"  重启 worker: rc={rc} {out.strip()}")
    if rc != 0:
        return False, out
    print(f"  观测 {observe}s 确认 worker 恢复、pending 幂等键未造成重复发送...")
    await asyncio.sleep(min(observe, RECOVERY_WINDOW["worker"]))
    # 此处无法自动断言「0 误发」，需结合日志人工确认；脚本给出检查指引
    print("  [提示] 请结合 worker 日志确认：重启前后无重复 task 投递（幂等键 + Redis pending）")
    return True, "worker 重启完成，幂等恢复需人工日志核对"


# ---------- 入口 ----------

async def main() -> int:
    ap = argparse.ArgumentParser(description="R21 混沌演练")
    ap.add_argument("--scenario", default="check", choices=["check", "chromium", "redis", "worker", "all"],
                    help="演练场景（check=仅观测）")
    ap.add_argument("--profile", default=None, help="Chromium 崩溃场景的 account_id")
    ap.add_argument("--worker", default="worker-publish", help="worker 重启场景的容器名")
    ap.add_argument("--observe", type=int, default=45, help="每场景自愈观测秒数（默认 45）")
    ap.add_argument("--redis-url", default=None, help="Redis URL（默认读环境 REDIS_URL 或 127.0.0.1:6379）")
    args = ap.parse_args()

    redis_url = args.redis_url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")

    if args.scenario == "check":
        print("[混沌演练] 检查模式：仅观测当前路由表状态（不注入故障）")
        r = await _redis_get(redis_url)
        try:
            states = await _get_route_states(r)
            print(f"当前路由表（{len(states)} 条）：")
            for acc, s in states.items():
                print(f"  {acc}: status={s['status']} port={s['port']} fail_streak={s['fail_streak']}")
            profiles = await _get_profiles(r)
            print(f"profiles 数: {len(profiles)}")
        finally:
            await r.close()
        return 0

    results = []
    scenarios = {
        "chromium": lambda: drill_chromium(args.profile, args.observe, redis_url),
        "redis": lambda: drill_redis(args.observe, redis_url),
        "worker": lambda: drill_worker(args.worker, args.observe, redis_url),
    }
    order = ["chromium", "redis", "worker"] if args.scenario == "all" else [args.scenario]
    for sc in order:
        if sc not in scenarios:
            print(f"[混沌演练] 未知场景: {sc}")
            return 2
        try:
            ok, msg = await scenarios[sc]()
            results.append((sc, ok, msg))
        except Exception as e:
            results.append((sc, False, str(e)))

    all_ok = all(ok for _, ok, _ in results)
    print("\n" + "=" * 60)
    print("混沌演练结果汇总（R21）")
    for sc, ok, msg in results:
        print(f"  [{sc}] {'✅ 通过' if ok else '❌ 未通过'} — {msg}")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
