"""豆包视频生成 RPA 服务（短片制作「一键豆包生成」）。

通过 Playwright CDP 连接 rpa_worker 容器内的 Chromium（与发布链路同架构），
自动完成：

1. 打开豆包网页端 https://www.doubao.com/chat/
2. 检测登录态：未登录则捕获登录二维码（内嵌 SVG）推给前端扫码；
   已登录（Cookie 落盘持久化）则免扫码直接继续
3. 进入「视频生成」技能，设置时长等参数（按账户类型上限校正）
4. 贴入提示词并发送，轮询等待生成结果
5. 被拒/违规时让豆包在同会话内改写提示词 → 交用户确认 → 确认后重发；
   用户拒绝则让豆包再改一版（最多 5 轮）
6. 生成完成从 download_url 下载成片，上传到 MinIO 并回填提示词记录

注意：豆包网页端是动态 React 加载（按需 chunk），选择器不硬编码 class，
统一使用文本 / 角色定位（get_by_text / get_by_role），并加随机延迟降低风控。
"""

import asyncio
import base64
import logging
import os
import time
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 豆包网页端地址
DOUBAO_CHAT_URL = "https://www.doubao.com/chat/"
# 视频生成技能入口文本
VIDEO_GEN_ENTRY = "视频生成"

# 账户类型 → 时长上限（秒）。豆包为动态运营策略，可在 system_config
# 的 shortdrama_doubao_config 中覆盖：{"free_max_seconds": 10, "pro_max_seconds": 30}
DEFAULT_ACCOUNT_LIMITS = {
    "free": 10,
    "pro": 30,
}

# 登录拦截弹窗文本标记（semi-modal 居中弹窗内容）
LOGIN_MODAL_MARKERS = ["登录以解锁", "扫码登录", "请使用豆包 App", "手机扫码", "登录后"]


class NeedLoginError(RuntimeError):
    """豆包页面弹出登录拦截弹窗，需要用户扫码登录。"""


def get_account_limits(custom: Optional[dict] = None) -> dict:
    """返回账户类型时长上限（合并自定义配置覆盖）。"""
    limits = dict(DEFAULT_ACCOUNT_LIMITS)
    if custom and isinstance(custom, dict):
        for k in ("free", "pro"):
            v = custom.get(f"{k}_max_seconds")
            if isinstance(v, (int, float)) and v > 0:
                limits[k] = int(v)
    return limits


class DoubaoGenerator:
    """豆包视频生成器（Playwright RPA）。"""

    def __init__(self, chrome_port: int = 9222, chrome_host: str = "127.0.0.1"):
        self.chrome_port = chrome_port
        self.chrome_host = chrome_host
        self.browser = None
        self.page = None
        self._pw = None

    async def _connect(self):
        # C3：统一走 playwright_manager 进程级单例（引用计数 + 空闲回收），
        # 不再每次自建 async_playwright() 驱动（避免驱动/浏览器句柄堆积泄漏）。
        from app.services.playwright_manager import get_playwright_manager

        self._pw = await get_playwright_manager().get_playwright()
        self.browser = await self._pw.chromium.connect_over_cdp(
            f"http://{self.chrome_host}:{self.chrome_port}"
        )
        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("Chrome 没有打开的上下文，请检查 rpa_worker 容器状态")
        self.context = contexts[0]
        self.page = await self.context.new_page()

    async def _close(self):
        # C3：关闭本次新建的 page / CDP 浏览器句柄，并归还共享驱动引用；
        # 不再 stop 共享驱动（生命周期由 playwright_manager 空闲回收统一管理）。
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                from app.services.playwright_manager import get_playwright_manager
                get_playwright_manager().release()
        except Exception:
            pass
        self.browser = None
        self.page = None
        self._pw = None

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────

    async def _sleep(self, lo: float = 0.4, hi: float = 1.2):
        """随机延迟（降低风控）。"""
        await asyncio.sleep(lo + (hi - lo) * (time.time() % 1))

    async def _take_screenshot(self) -> Optional[str]:
        """截取当前豆包页面（对话窗口）为 PNG data URL，供前端展示制作过程。"""
        try:
            shot = await self.page.screenshot(type="png", full_page=False)
            return "data:image/png;base64," + base64.b64encode(shot).decode()
        except Exception:
            return None

    async def _extract_qrcode(self, full_page_fallback: bool = True) -> Optional[str]:
        """提取登录二维码：优先截取内嵌 SVG 节点，返回 PNG data URL。

        full_page_fallback=False 时找不到独立 SVG 节点则返回 None（避免把
        整页截图误当二维码推给用户），由调用方决定何时兜底。
        """
        try:
            svg = await self.page.query_selector("svg.qr-code, svg[class*='qrcode'], svg[class*='qr-code']")
            if not svg:
                svgs = await self.page.query_selector_all("svg")
                for s in svgs:
                    bbox = await s.bounding_box()
                    if bbox and bbox["width"] >= 120 and bbox["height"] >= 120:
                        svg = s
                        break
            if svg:
                shot = await svg.screenshot()
            elif full_page_fallback:
                # 二维码不是独立 SVG 节点时，直接整页截图（用户可自行放大定位二维码）
                shot = await self.page.screenshot(type="png")
            else:
                return None
            if not shot:
                return None
            return "data:image/png;base64," + base64.b64encode(shot).decode()
        except Exception:
            return None

    async def _click_login_button(self) -> bool:
        """点击右上角「登录」按钮触发二维码弹窗（未登录时）。

        若页面已有二维码弹窗则跳过，避免重复弹出。
        """
        try:
            if await self.page.query_selector(".semi-modal-wrap, [class*='qrcode'], [class*='login-modal']"):
                return True  # 弹窗已在，无需再点
            btn = await self.page.query_selector(
                "button:has-text('登录'), [class*='header'] button:has-text('登录'), "
                "[class*='nav'] button:has-text('登录')"
            )
            if not btn:
                return False
            text = (await btn.inner_text()).strip()
            if text != "登录":
                return False
            await btn.click(timeout=5000)
            await self._sleep(1.0, 1.5)
            return True
        except Exception:
            return False

    async def _detect_login_modal(self) -> bool:
        try:
            modal = await self.page.query_selector(".semi-modal-wrap, .semi-modal")
            if modal:
                text = await modal.inner_text()
                if any(m in text for m in LOGIN_MODAL_MARKERS):
                    return True
            return False
        except Exception:
            return False

    async def _dismiss_modal(self) -> bool:
        """尝试关闭非登录的 semi-modal 弹窗（引导/公告等），返回是否关闭成功。"""
        try:
            close_btn = await self.page.query_selector(
                ".semi-modal-close, .semi-modal-wrap .semi-icon-close, [class*='modal'] [class*='close']"
            )
            if close_btn:
                await close_btn.click(timeout=2000)
                await self._sleep(0.5, 0.8)
                return True
            await self.page.keyboard.press("Escape")
            await self._sleep(0.5, 0.8)
            return True
        except Exception:
            return False

    async def _has_login_button(self) -> bool:
        """检测页面右上角「登录」按钮（未登录的强信号）。

        豆包未登录时顶部导航必有「登录」按钮（正文/欢迎页也可能出现“登录”二字，
        因此只匹配按钮元素且文本恰为“登录”，避免误判）。
        """
        try:
            btn = await self.page.query_selector(
                "button:has-text('登录'), [class*='header'] button:has-text('登录'), "
                "[class*='nav'] button:has-text('登录'), [class*='topbar'] button"
            )
            if not btn:
                return False
            text = (await btn.inner_text()).strip()
            return text == "登录"
        except Exception:
            return False

    async def _login_status(self) -> str:
        """返回登录态：'valid'（已登录）/ 'need_login'（需要扫码）/ 'unknown'。

        判定优先级：
        1. 右上角「登录」按钮存在 → 未登录（强信号，未登录时欢迎页也有 textarea，
           仅靠输入框会误判 valid）
        2. 登录拦截弹窗（点击视频生成后触发）→ 未登录
        3. 否则检测输入框 → valid
        """
        try:
            await self.page.goto(DOUBAO_CHAT_URL, wait_until="domcontentloaded", timeout=45000)
            await self._sleep(1.0, 2.0)
            # 强信号：右上角登录按钮
            if await self._has_login_button():
                return "need_login"
            # 尝试进入视频生成技能，触发「登录以解锁」拦截弹窗（未登录时）
            try:
                await self.page.get_by_text(VIDEO_GEN_ENTRY, exact=False).first.click(timeout=5000)
                # 弹窗为异步出现，需多等几秒再检测
                await self._sleep(3.0, 4.0)
            except Exception:
                pass
            if (
                await self.page.query_selector(
                    "text=登录以解锁更多功能, [class*='login-guide'], [class*='qrcode'], [class*='login-modal']"
                )
                or await self._detect_login_modal()
            ):
                return "need_login"
            has_input = await self.page.query_selector(
                "textarea, [contenteditable='true'], [class*='chat-input']"
            )
            return "valid" if has_input else "need_login"
        except Exception:
            return "unknown"

    async def _extract_account(self) -> Optional[str]:
        """提取当前已登录豆包账户名（昵称），未登录/未知时返回 None。

        豆包网页端登录后顶部导航会展示头像与昵称，但 DOM 类名多为哈希值且随版本
        变动，因此不硬编码 class，统一用文本 / 头像节点启发式定位：
        - 优先取头像图标的 title/alt/aria-label 或相邻昵称文本
        - 其次取顶部导航内较短的昵称文本节点（长度 2~30，排除“登录”等关键词）
        该方法仅在确认已登录（右上角无「登录」按钮）后调用，绝不触碰登录弹窗逻辑。
        """
        try:
            await self._sleep(0.6, 1.2)
            # 1) 头像节点：title/alt/aria-label 常为昵称或“我的”，仅采纳长度合理者
            avatar = await self.page.query_selector(
                "[class*='avatar'] img, [class*='avatar'], [class*='header'] img"
            )
            for attr in ("title", "alt", "aria-label"):
                if avatar:
                    try:
                        val = (await avatar.get_attribute(attr) or "").strip()
                    except Exception:
                        val = ""
                    if val and 1 < len(val) <= 40 and "登录" not in val and "扫码" not in val:
                        return val

            # 2) 顶部导航 / 用户区文本节点（启发式：长度 2~30、排除功能关键词）
            excludes = ("登录", "扫码", "下载", "会员", "开通", "帮助", "反馈", "设置", "视频生成")
            for sel in (
                "[class*='header'] [class*='name'], [class*='header'] [class*='nickname'],"
                "[class*='header'] [class*='user-info'], [class*='topbar'] [class*='user']"
            ):
                try:
                    el = await self.page.query_selector(sel)
                except Exception:
                    continue
                if not el:
                    continue
                try:
                    t = (await el.inner_text() or "").strip()
                except Exception:
                    t = ""
                if t and 1 < len(t) <= 40 and not any(x in t for x in excludes):
                    return t
        except Exception:
            return None
        return None

    async def clear_login(self) -> bool:
        """清除豆包登录态（Cookie），用于「更换豆包账户」。

        连接 CDP 后清空当前浏览器上下文的 Cookie 与 localStorage，
        使下次生成时重新弹出扫码登录二维码，从而支持切换到另一个豆包账号。
        """
        try:
            await self._connect()
            try:
                await self.context.clear_cookies()
                for page in self.context.pages:
                    try:
                        await page.evaluate("localStorage.clear()")
                    except Exception:
                        pass
            finally:
                await self._close()
            return True
        except Exception as exc:
            logger.warning("[doubao] 清除登录态失败: %s", exc)
            return False

    # ──────────────────────────────────────────────
    # 主流程
    # ──────────────────────────────────────────────

    async def _is_cancelled(self, cancel_check) -> bool:
        """异步判断任务是否已取消（支持同步函数 / 协程 / None）。"""
        if cancel_check is None:
            return False
        try:
            res = cancel_check()
            if asyncio.iscoroutine(res):
                return bool(await res)
            return bool(res)
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        *,
        account_type: str = "free",
        duration: Optional[int] = None,
        limits: Optional[dict] = None,
        progress_cb=None,
        qrcode_cb=None,
        screenshot_cb=None,
        on_rewrite_available=None,
        on_login_success=None,
        on_account_cb=None,
        cancel_check=None,
    ) -> dict:
        """执行豆包视频生成主流程。

        Args:
            prompt: 要发送的提示词
            account_type: free / pro，决定时长上限
            duration: 用户想要的时长（秒）；超过账户上限自动校正
            limits: 账户时长上限映射（默认 free=10 / pro=30）
            progress_cb: async def cb(message: str, progress: float)
            qrcode_cb: async def cb(qr_data_url: str)（需要登录时推送二维码）
            screenshot_cb: async def cb(shot_data_url: str)
            on_rewrite_available: async def cb(payload: dict) -> str
                返回 'approved'（使用改写稿）或 'rejected'（让豆包再改一版）
            on_login_success: async def cb()（扫码登录成功、即将进入生成时回调，
                调用方应把任务状态从 need_login 拉回 running 并清空二维码）
            on_account_cb: async def cb(account: Optional[str])（提取到当前登录的
                豆包账户昵称后回调，供调用方展示「当前登录豆包账户」；未识别到传 None）
            cancel_check: callable -> bool（返回 True 表示任务已取消，中止）

        Returns:
            {"success": bool, "status": str, "message": str,
             "download_url": str, "approved_prompt": str,
             "rewrites": [...]}
        """
        if progress_cb is None:
            async def progress_cb(msg: str, progress: float):
                return

        limits = limits or get_account_limits()
        limit = limits.get(account_type, 10)
        if duration is None:
            duration = limit
        duration = max(1, min(int(duration or limit), limit))

        rewrites: list[dict] = []

        try:
            await self._connect()
            await progress_cb("正在打开豆包…", 5)

            status = await self._login_status()
            if status == "need_login":
                await progress_cb("需要扫码登录豆包，请使用豆包 App 扫码", 10)
                qr_pushed = False
                deadline = time.time() + 300
                while time.time() < deadline:
                    if await self._is_cancelled(cancel_check):
                        return {
                            "success": False,
                            "status": "cancelled",
                            "message": "任务已取消",
                        }
                    # 首次触发登录二维码弹窗（点击右上角「登录」按钮）
                    if not qr_pushed:
                        await self._click_login_button()
                    # 二维码异步渲染，先重试抓取独立 SVG，失败才兜底整页截图
                    qr = None
                    for _ in range(5):
                        qr = await self._extract_qrcode(full_page_fallback=False)
                        if qr:
                            break
                        await self._sleep(0.8, 1.2)
                    if not qr:
                        qr = await self._extract_qrcode()
                    if qr and not qr_pushed:
                        if qrcode_cb:
                            await qrcode_cb(qr)
                        qr_pushed = True
                    await self._sleep(1.0, 1.5)
                    # 轻量检查登录态：不重新加载页面（避免把二维码弹窗关掉），
                    # 右上角「登录」按钮消失即视为扫码成功
                    if not await self._has_login_button():
                        # 通知调用方扫码成功：把任务状态从 need_login 拉回 running 并清空二维码，
                        # 否则前端以 status != need_login 作为弹窗关闭条件，二维码弹窗永不消失
                        if on_login_success:
                            try:
                                await on_login_success()
                            except Exception:
                                logger.exception("on_login_success callback failed")
                        break
                else:
                    return {
                        "success": False,
                        "status": "need_login",
                        "message": "等待扫码登录超时，请重新发起生成",
                    }

            # 已登录（含刚扫码成功）：提取当前登录豆包账户昵称供前端展示
            if on_account_cb:
                try:
                    account = await self._extract_account()
                    await on_account_cb(account)
                except Exception:
                    logger.exception("on_account_cb failed")

            await progress_cb("登录状态正常，正在进入视频生成…", 20)
            result = await self._run_video_generation(
                prompt=prompt,
                duration=duration,
                account_type=account_type,
                progress_cb=progress_cb,
                screenshot_cb=screenshot_cb,
                on_rewrite_available=on_rewrite_available,
                rewrites=rewrites,
                cancel_check=cancel_check,
            )
            result["approved_prompt"] = rewrites[-1]["rewritten"] if rewrites else prompt
            result["rewrites"] = rewrites
            return result

        except NeedLoginError:
            # 流程中途弹出登录拦截弹窗：推送二维码，前端展示扫码引导（不再无提示地进入后续流程）
            if qrcode_cb:
                try:
                    qr = await self._extract_qrcode()
                    if qr:
                        await qrcode_cb(qr)
                    else:
                        await progress_cb("需要扫码登录豆包，但未能自动截取二维码，请直接打开豆包页面扫码", 12)
                except Exception:
                    pass
            return {
                "success": False,
                "status": "need_login",
                "message": "需要扫码登录豆包，请重新发起生成",
            }
        except Exception as e:
            logger.exception("Doubao generate failed")
            return {
                "success": False,
                "status": "failed",
                "message": f"豆包生成失败: {e}",
            }
        finally:
            await self._close()

    async def _run_video_generation(
        self,
        prompt: str,
        duration: int,
        account_type: str,
        progress_cb,
        rewrites: list,
        screenshot_cb=None,
        on_rewrite_available=None,
        cancel_check=None,
    ) -> dict:
        """进入视频生成技能并发送提示词，处理改写闭环直到成功或失败。"""
        await self.page.goto(DOUBAO_CHAT_URL, wait_until="domcontentloaded", timeout=45000)
        await self._sleep(1.0, 2.0)

        try:
            await self.page.get_by_text(VIDEO_GEN_ENTRY, exact=False).first.click(timeout=8000)
            # 登录拦截弹窗异步出现，多等几秒再检测
            await self._sleep(3.0, 4.0)
        except Exception:
            await progress_cb("未找到视频生成入口，尝试直接对话…", 25)
        # 未登录时「视频生成」会弹登录拦截弹窗 → 抛出 NeedLoginError 走扫码流程
        if await self._detect_login_modal():
            raise NeedLoginError("需要扫码登录豆包")

        await progress_cb("已进入视频生成，正在配置参数…", 30)
        await self._set_duration(duration)

        current_prompt = prompt
        max_rounds = 5
        for round_idx in range(1, max_rounds + 1):
            if await self._is_cancelled(cancel_check):
                return {"success": False, "status": "cancelled", "message": "任务已取消"}
            await progress_cb(f"正在发送提示词（第 {round_idx} 轮）…", 33 + round_idx * 3)
            send_ok = await self._send_prompt(current_prompt)
            if not send_ok:
                return {
                    "success": False,
                    "status": "failed",
                    "message": "未找到输入框，无法发送提示词（豆包页面可能改版，请检查 RPA 容器）",
                }

            await progress_cb("已发送，等待豆包生成视频…", 50)
            outcome = await self._wait_for_generation_outcome(progress_cb, cancel_check, screenshot_cb)

            if outcome.get("status") == "completed":
                return {
                    "success": True,
                    "status": "completed",
                    "message": "视频生成完成",
                    "download_url": outcome.get("download_url"),
                }

            if outcome.get("status") == "rejected":
                reason = outcome.get("reason") or "提示词可能包含违规内容"
                # 改写闭环：最多尝试 3 次改写稿，用户确认后才重新发送
                approved_rewrite = None
                rejected_prompt = current_prompt
                for attempt in range(1, 4):
                    if await self._is_cancelled(cancel_check):
                        return {"success": False, "status": "cancelled", "message": "任务已取消"}
                    await progress_cb(f"豆包拒绝了提示词，正在用本地模型改写（第 {attempt} 次）…", 60)
                    rewritten = await self._llm_rewrite_prompt(rejected_prompt, reason)
                    if not rewritten:
                        return {
                            "success": False,
                            "status": "failed",
                            "message": "豆包未返回改写稿，生成失败",
                        }
                    rewrites.append({
                        "round": round_idx,
                        "attempt": attempt,
                        "original": current_prompt,
                        "rewritten": rewritten,
                        "reason": reason,
                        "created_at": datetime.utcnow().isoformat(),
                    })
                    if on_rewrite_available is not None:
                        decision = await on_rewrite_available({
                            "round": round_idx,
                            "attempt": attempt,
                            "original": current_prompt,
                            "rewritten": rewritten,
                            "reason": reason,
                        })
                        if decision == "cancelled":
                            return {"success": False, "status": "cancelled", "message": "任务已取消"}
                        if decision == "approved":
                            approved_rewrite = rewritten
                            break
                        # rejected → 继续让豆包再改一版
                        reason = "用户对上一版改写稿不满意，请进一步修改（保留剧情结构）"
                        rejected_prompt = rewritten
                    else:
                        approved_rewrite = rewritten
                        break
                if approved_rewrite is None:
                    return {
                        "success": False,
                        "status": "failed",
                        "message": "多次改写未获用户确认，已放弃",
                    }
                current_prompt = approved_rewrite
                continue

            if outcome.get("status") == "cancelled":
                return {"success": False, "status": "cancelled", "message": "任务已取消"}

            return {
                "success": False,
                "status": "failed",
                "message": outcome.get("message") or "豆包生成结果未知",
            }

        return {
            "success": False,
            "status": "failed",
            "message": "改写确认轮次超过上限，已放弃",
        }

    # ──────────────────────────────────────────────
    # 具体操作
    # ──────────────────────────────────────────────

    async def _set_duration(self, duration: int):
        """设置生成时长（在账户类型允许范围内）。"""
        try:
            try:
                await self.page.get_by_text(f"{duration}秒", exact=False).first.click(timeout=4000)
                await self._sleep(0.4, 0.8)
            except Exception:
                inputs = await self.page.query_selector_all(
                    "input[type='number'], input[placeholder*='时长'], [class*='duration'] input"
                )
                if inputs:
                    await inputs[0].fill(str(duration))
                    await self._sleep(0.3, 0.6)
        except Exception as e:
            logger.warning("set duration failed (ignore): %s", e)

    async def _send_prompt(self, prompt: str) -> bool:
        """定位输入框并发送提示词。

        豆包页面为 React 动态渲染，点击「视频生成」后输入框需数百毫秒到数秒
        才挂载完成。因此先等待候选输入框出现（最多约 15s），再按可见性过滤：
        视频生成模式下页面会残留隐藏 textarea（height=0），真正可输入的是
        可见的 contenteditable（ProseMirror/tiptap）。若一次查询失败就返回，
        会误报「未找到输入框」。
        """
        textarea = None
        deadline = time.time() + 15
        while time.time() < deadline:
            candidates: list = []
            for sel in ("textarea", "[contenteditable='true']", "[class*='chat-input'] textarea"):
                try:
                    candidates.extend(await self.page.query_selector_all(sel))
                except Exception:
                    pass
            # 优先可见的候选（视频生成模式下隐藏 textarea 会被跳过）
            for el in candidates:
                try:
                    if await el.is_visible():
                        textarea = el
                        break
                except Exception:
                    continue
            if textarea:
                break
            await self._sleep(0.8, 1.2)
        # 都不可见/未出现时退而求其次用第一个
        if not textarea and candidates:
            textarea = candidates[0]
        if not textarea:
            logger.warning("_send_prompt: no visible input found (page=%s)", self.page.url)
            return False

        # 点击输入框：被弹窗遮挡时先检测登录弹窗（抛 NeedLoginError），
        # 其它弹窗尝试关闭后重试，仍失败则退回键盘操作
        try:
            await textarea.click(timeout=5000)
        except Exception:
            if await self._detect_login_modal():
                raise NeedLoginError("需要扫码登录豆包")
            await self._dismiss_modal()
            try:
                await textarea.click(timeout=5000)
            except Exception:
                pass
        await self._sleep(0.3, 0.6)
        # fill 可能因残留弹窗遮挡/页面未渲染完失败：先关非登录弹窗再重试，
        # 仍失败且检测到登录弹窗则抛 NeedLoginError 走扫码流程。
        # 视频生成模式输入框是 ProseMirror/tiptap 富文本，fill 偶发不可靠，
        # 最终兜底改用 click + 全选 + 键盘输入。
        try:
            await textarea.fill(prompt, timeout=10000)
        except Exception:
            if await self._detect_login_modal():
                raise NeedLoginError("需要扫码登录豆包")
            await self._dismiss_modal()
            await self._sleep(0.5, 0.8)
            try:
                await textarea.fill(prompt, timeout=15000)
            except Exception:
                try:
                    await textarea.click(timeout=5000)
                    await self.page.keyboard.press("Meta+A")
                    await self.page.keyboard.type(prompt, delay=15)
                except Exception:
                    return False
        await self._sleep(0.3, 0.6)
        try:
            send_btn = await self.page.query_selector(
                "button[class*='send'], button:has-text('发送'), [class*='send-button']"
            )
        except Exception:
            send_btn = None
        if send_btn:
            try:
                await send_btn.click()
                return True
            except Exception:
                pass
        await self.page.keyboard.press("Enter")
        return True

    async def _wait_for_generation_outcome(self, progress_cb, cancel_check=None, screenshot_cb=None) -> dict:
        """等待豆包生成结果，识别成功 / 被拒 / 超时。"""
        deadline = time.time() + 900  # 15 分钟
        self._gen_tick = 0
        last_progress = 50
        shot_count = 0
        while time.time() < deadline:
            if await self._is_cancelled(cancel_check):
                return {"status": "cancelled", "message": "任务已取消"}
            await self._sleep(2.5, 3.5)

            try:
                page_text = await self._get_last_message_text() or ""
            except Exception:
                page_text = ""
            reject_markers = [
                "包含敏感内容", "违反", "无法生成", "审核未通过",
                "违规", "生成失败", "内容不符合", "安全策略",
            ]
            for m in reject_markers:
                if m in page_text:
                    return {"status": "rejected", "reason": self._extract_reject_reason(page_text, m)}

            # 完成判定：豆包出片后会在对话里回“你的视频生成好了”。视频以自定义播放器
            # （.video-player-wrapper + 播放图标）渲染，并非 <video> 标签；真实视频文件
            # URL 仅在点击播放后加载（douyin CDN mp4 直链）。
            if "视频生成好了" in page_text:
                logger.info("[DOUBAO] 检测到“视频生成好了”，开始抓取成片地址")
                try:
                    download_url = await self._capture_video_url()
                except Exception:
                    logger.exception("[DOUBAO] 抓取成片地址异常")
                    download_url = None
                if download_url:
                    return {"status": "completed", "download_url": download_url}
                logger.warning("[DOUBAO] 完成文案已出现但暂未取到成片地址，继续轮询等待播放器就绪")

            last_progress = min(last_progress + 2, 85)
            await progress_cb("豆包正在生成视频，请稍候…", last_progress)
            # 周期截取对话窗口，供前端实时展示制作过程（约每 10s 一张）
            if screenshot_cb:
                shot_count += 1
                if shot_count % 3 == 0:
                    try:
                        shot = await self._take_screenshot()
                        if shot:
                            await screenshot_cb(shot)
                    except Exception:
                        pass

        return {"status": "error", "message": "等待豆包生成超时（15 分钟）"}

    def _extract_reject_reason(self, page_text: str, marker: str) -> str:
        """从页面文本中提取拒绝原因（关键词附近 60 字）。"""
        idx = page_text.find(marker)
        if idx < 0:
            return marker
        start = max(0, idx - 30)
        end = min(len(page_text), idx + 60)
        return page_text[start:end].replace("\n", " ").strip()

    async def _get_last_message_text(self) -> str:
        """读取对话列表里【最新单条】消息的文本（用于判定本次回复是拒绝还是出片）。

        关键：豆包视频生成是持久会话，历史消息会一直留在页面里。
        历史里的旧拒绝文案若混入扫描范围，会导致「已确认改写的提示词被重新判为拒绝
        → 再次进入改写循环 → 用户未二次确认 → 最终失败」，而豆包侧其实已生成成功。

        因此必须只取对话列表【最后一条消息节点】的文本，严禁扫描整段对话。
        """
        try:
            ml = await self.page.query_selector("[class*='message-list']")
            if not ml:
                return ""
            # 只取最后一条非空消息节点，彻底排除历史污染
            nodes = await ml.query_selector_all(":scope > *")
            for node in reversed(nodes):
                try:
                    t = (await node.inner_text()).strip()
                except Exception:
                    t = ""
                if t:
                    return t
            return ""
        except Exception:
            return ""

    async def _llm_rewrite_prompt(self, original: str, reason: str) -> Optional[str]:
        """用本地大模型（DashScope / 通义千问，OpenAI 兼容模式）把被拒提示词改写成合规版本。

        不依赖豆包聊天抓取：豆包视频生成是持久会话且 DOM 类名为哈希值，抓取极不稳定；
        改为确定性 LLM 调用，稳定可靠。改写后由调用方重新发送给豆包生成视频。
        """
        api_key = os.getenv("DASHSCOPE_API_KEY")
        model = os.getenv("API_MODEL_NAME") or "qwen3.7-flash-2026-07-15"
        if not api_key:
            logger.warning("[LLM_REWRITE] DASHSCOPE_API_KEY 未配置，无法改写")
            return None
        system = (
            "你是一名短视频生成提示词合规改写专家。用户会给你一条被短视频平台拒绝的提示词，"
            "以及平台给出的拒绝原因。请在不改变剧情、时长、镜头结构与整体风格的前提下，"
            "仅修改违规或敏感内容，使其符合主流短视频平台规范。"
            "直接输出改写后的提示词全文，不要任何解释、前缀或代码块标记。"
        )
        user = (
            f"【原始提示词】\n{original}\n\n"
            f"【平台拒绝原因】\n{reason}\n\n"
            "请直接输出改写后的提示词全文："
        )
        url = os.getenv("LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            # 去掉可能的代码块标记 / 引号包裹
            text = text.strip("`").strip()
            if text.startswith("```"):
                body = text.strip("`")
                body = body.split("\n", 1)[1] if "\n" in body else body
                text = body.strip("`").strip()
            if len(text) < 5:
                logger.warning("[LLM_REWRITE] 返回过短，视为失败: %r", text)
                return None
            logger.info("[LLM_REWRITE] ok len=%d: %s", len(text), text[:80])
            return text
        except Exception as e:
            logger.exception("[LLM_REWRITE] call failed: %s", e)
            return None

    async def _capture_video_url(self) -> Optional[str]:
        """豆包出片后抓取真实成片地址。

        豆包视频卡片是自定义播放器（.video-player-wrapper + 播放图标），并非 <video> 标签；
        真实视频文件 URL 仅在点击播放后注入 <video>（douyin CDN mp4 直链）。本方法定位
        “你的视频生成好了”消息卡片 → 点击播放图标 → 等待 <video> 出现并读取 currentSrc。
        """
        # 1) 点击“你的视频生成好了”所在卡片的播放图标，触发 <video> 加载
        click_res = await self.page.evaluate(
            """() => {
                const ml = document.querySelector("[class*='message-list']");
                if (!ml) return 'no_ml';
                let card = null;
                for (const n of Array.from(ml.children)) {
                    if ((n.innerText || '').includes('你的视频生成好了')) { card = n; break; }
                }
                if (!card) return 'no_card';
                card.scrollIntoView({block: 'center'});
                const player = card.querySelector("[class*='video-player']")
                              || card.querySelector("[class*='play-icon']");
                if (!player) return 'no_player';
                try { player.click(); } catch (e) { return 'click_err:' + e; }
                return 'ok';
            }"""
        )
        logger.info("[DOUBAO] play click -> %s", click_res)

        # 2) 监听 mp4 网络响应作兜底，同时轮询 <video>.currentSrc
        resp_url = [None]

        def _on_resp(resp):
            try:
                ct = resp.headers.get("content-type", "")
                u = resp.url or ""
                if "video" in ct or ".mp4" in u:
                    resp_url[0] = u
            except Exception:
                pass

        self.page.on("response", _on_resp)
        try:
            for _ in range(15):
                await self._sleep(1.0, 1.5)
                cur = await self.page.evaluate(
                    """() => { const v = document.querySelector('video');
                        return v ? (v.currentSrc || v.src || '') : ''; }"""
                )
                if cur:
                    logger.info("[DOUBAO] 取到成片地址 len=%d", len(cur))
                    return cur
            if resp_url[0]:
                logger.info("[DOUBAO] 退回网络响应地址")
                return resp_url[0]
        finally:
            try:
                self.page.remove_listener("response", _on_resp)
            except Exception:
                pass
        logger.warning("[DOUBAO] 未能取到成片地址")
        return None
