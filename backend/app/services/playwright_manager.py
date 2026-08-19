"""Playwright 生命周期统一管理器（C3 / Codex 审查报告 #5）。

背景：发布（publish_service）、豆包（doubao_service）、登录扫码（login_qr_service）、
预览层（preview_client）四处**各自管理** Playwright 实例的生命周期：
- publish_service 有一个模块级 `_get_playwright()` 单例，但浏览器 CDP 连接按 Publisher 独立管理；
- doubao_service 每次 `_connect()` 都 `async_playwright().start()`，`_close()` 里 `stop()`；
- login_qr_service 的抽码/心跳/续活三处各自 `async with async_playwright() as p:`；
- preview_client 也自持一个 `_playwright` start/stop。

这种"各管各"的模式在任务并发/异常中断时容易造成 Playwright 驱动或浏览器句柄堆积泄漏。

本模块把生命周期收敛为**进程级单例 + 引用计数 + 空闲回收**的统一管理器：

- 进程内只启动 **一个** `async_playwright()` 驱动（懒启动，`_pw` 单例）；
- 任何一处要用驱动，先 `get_playwright()`（+1 引用），用完必须 `release()`（-1）；
- 引用计数归零且无 pin 时**不立即销毁**，而是进入空闲期；空闲超过
  `PLAYWRIGHT_IDLE_TIMEOUT` 秒仍无新获取，才真正 `stop()` 驱动并复位（空闲回收）；
  空闲期内有新的获取则重置空闲计时——避免频繁启动/停止，也避免驱动长期空挂；
- 长驻浏览器句柄（如待确认发布 tab 持有的 browser/page 代理）通过
  `pin()` / `unpin()` 阻止空闲回收：只要还有 pin，驱动就绝不回收，防止 driver 被
  stop 后其持有的 browser/page 代理失效。
"""

import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# 空闲回收默认超时（秒）：引用归零且无 pin 后，超过该时长无新获取才 stop 驱动。
# 可经 settings.PLAYWRIGHT_IDLE_TIMEOUT 覆盖；None/<=0 表示关闭空闲回收（保持常驻）。
DEFAULT_IDLE_TIMEOUT = 300


class PlaywrightManager:
    """进程级 Playwright 驱动管理器（引用计数 + 空闲回收）。"""

    def __init__(self, idle_timeout: Optional[float] = None) -> None:
        self._lock = threading.Lock()
        self._pw: Optional[object] = None          # 懒启动的 async_playwright 实例
        self._ref_count = 0                        # 活跃引用数（用驱动中）
        self._pin_count = 0                        # 长驻句柄 pin 数（阻止空闲回收）
        self._idle_task: Optional[asyncio.Task] = None  # 待执行的空闲回收任务
        # 空闲超时：None/<=0 表示禁用空闲回收（驱动常驻到进程结束）
        self._idle_timeout = idle_timeout

    # ────────────────────────── 引用管理 ──────────────────────────

    async def get_playwright(self) -> object:
        """获取进程级共享驱动，引用计数 +1。调用方必须在适当时候 `release()` 归还。"""
        async with self._mutex():
            await self._ensure_started_locked()
            self._ref_count += 1
            self._cancel_idle_task_locked()
            return self._pw

    def release(self) -> None:
        """归还一次驱动引用，引用计数 -1。归零且无 pin 时调度空闲回收。"""
        with self._lock:
            if self._ref_count > 0:
                self._ref_count -= 1
            if self._ref_count == 0 and self._pin_count == 0:
                self._schedule_idle_reclaim_locked()

    async def get_shared(self) -> object:
        """获取进程级共享驱动并**永久 pin**（进程生命周期内常驻持有者使用）。

        适用场景：publish worker 需要在任务之间复用待确认 tab 的 browser 代理，
        驱动不能空闲回收；调用一次后驱动保持启动，直到进程退出或显式 stop_now。
        返回的驱动不参与引用计数（引用计数专供短时 use-and-release 场景）。
        """
        async with self._mutex():
            await self._ensure_started_locked()
            self._pin_count += 1
            self._cancel_idle_task_locked()
            return self._pw

    def acquire(self) -> "_PlaywrightLease":
        """获取一个异步上下文管理器（租约）：进入时 get_playwright()，退出时 release()。

        用法：`async with get_playwright_manager().acquire() as p: ...`
        """
        return _PlaywrightLease(self)

    def pin(self) -> None:
        """pin +1：阻止空闲回收（长驻浏览器句柄持有者调用）。"""
        with self._lock:
            self._pin_count += 1
            self._cancel_idle_task_locked()

    def unpin(self) -> None:
        """pin -1：长驻句柄释放后调用；pin 归零且无引用时恢复空闲回收。"""
        with self._lock:
            if self._pin_count > 0:
                self._pin_count -= 1
            if self._ref_count == 0 and self._pin_count == 0:
                self._schedule_idle_reclaim_locked()

    # ────────────────────────── 强制回收 ──────────────────────────

    async def stop_now(self) -> None:
        """立即停止驱动并复位（忽略引用/pin，供进程退出或显式清理使用）。"""
        with self._lock:
            self._cancel_idle_task_locked()
            pw = self._pw
            self._pw = None
            self._ref_count = 0
            self._pin_count = 0
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                logger.warning("playwright_manager stop_now: stop 异常", exc_info=True)

    # ────────────────────────── 内部实现 ──────────────────────────

    def _mutex(self):
        """把 threading.Lock 转成可用的 async 互斥，保证 start 只在单线程事件循环内完成。"""
        return _ThreadLockToAsync(self._lock)

    async def _ensure_started_locked(self) -> None:
        if self._pw is None:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            logger.info("playwright_manager: 进程级 Playwright 驱动已启动")

    def _schedule_idle_reclaim_locked(self) -> None:
        """引用归零且无 pin 时，调度一个空闲回收任务；超时后无新获取则 stop 驱动。"""
        if self._idle_task is not None or self._pw is None:
            return
        timeout = self._idle_timeout
        if timeout is None or timeout <= 0:
            return  # 禁用空闲回收
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # 无运行中的事件循环（罕见），驱动交由进程生命周期管理
        self._idle_task = loop.create_task(self._idle_reclaim(timeout))

    def _cancel_idle_task_locked(self) -> None:
        task = self._idle_task
        if task is not None:
            task.cancel()
            self._idle_task = None

    async def _idle_reclaim(self, timeout: float) -> None:
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        # 空闲期结束，仍无新获取/无 pin → 真正回收驱动
        with self._lock:
            self._idle_task = None
            if self._ref_count > 0 or self._pin_count > 0:
                return  # 期间又被使用，放弃回收
            pw = self._pw
            self._pw = None
        if pw is not None:
            try:
                await pw.stop()
                logger.info("playwright_manager: 空闲回收 Playwright 驱动")
            except Exception:
                logger.warning("playwright_manager: 空闲回收 stop 异常", exc_info=True)


class _PlaywrightLease:
    """异步上下文管理器：进入时获取共享驱动（引用+1），退出时释放（引用-1）。"""

    def __init__(self, manager: "PlaywrightManager") -> None:
        self._manager = manager
        self._pw: Optional[object] = None

    async def __aenter__(self):
        self._pw = await self._manager.get_playwright()
        return self._pw

    async def __aexit__(self, *exc):
        self._manager.release()
        self._pw = None
        return False


class _ThreadLockToAsync:
    """把 threading.Lock 包装为 async 上下文管理器，避免 GIL 竞争驱动初始化。"""

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock

    async def __aenter__(self):
        await asyncio.to_thread(self._lock.acquire)
        return self

    async def __aexit__(self, *exc):
        self._lock.release()
        return False


# ────────────────────────── 进程级单例 ──────────────────────────

def _resolve_idle_timeout() -> Optional[float]:
    try:
        from app.config import settings
        val = getattr(settings, "PLAYWRIGHT_IDLE_TIMEOUT", None)
    except Exception:
        val = None
    return DEFAULT_IDLE_TIMEOUT if val is None else float(val)


_manager: Optional[PlaywrightManager] = None
_manager_lock = threading.Lock()


def get_playwright_manager() -> PlaywrightManager:
    """获取进程级 Playwright 管理器单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = PlaywrightManager(idle_timeout=_resolve_idle_timeout())
    return _manager


async def get_playwright() -> object:
    """便捷入口：获取进程级共享驱动（引用 +1）。用完请调用 release()。"""
    return await get_playwright_manager().get_playwright()


def release() -> None:
    """便捷入口：归还一次驱动引用。"""
    get_playwright_manager().release()
