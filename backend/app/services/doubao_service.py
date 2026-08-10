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
import time
from datetime import datetime
from typing import Optional

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
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.connect_over_cdp(
            f"http://{self.chrome_host}:{self.chrome_port}"
        )
        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("Chrome 没有打开的上下文，请检查 rpa_worker 容器状态")
        self.context = contexts[0]
        self.page = await self.context.new_page()

    async def _close(self):
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

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

    async def _extract_qrcode(self) -> Optional[str]:
        """提取登录二维码：优先截取内嵌 SVG 节点，返回 PNG data URL。"""
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
            else:
                # 二维码不是独立 SVG 节点时，直接整页截图（用户可自行放大定位二维码）
                shot = await self.page.screenshot(type="png")
            if not shot:
                return None
            return "data:image/png;base64," + base64.b64encode(shot).decode()
        except Exception:
            return None

    async def _detect_login_modal(self) -> bool:
        """检测登录拦截弹窗（semi-modal 居中弹窗 + 登录文本）。"""
        try:
            modal = await self.page.query_selector(".semi-modal-wrap, .semi-modal")
            if modal:
                text = await modal.inner_text(timeout=3000)
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

    async def _login_status(self) -> str:
        """返回登录态：'valid'（已登录）/ 'need_login'（需要扫码）/ 'unknown'。"""
        try:
            await self.page.goto(DOUBAO_CHAT_URL, wait_until="domcontentloaded", timeout=45000)
            await self._sleep(1.0, 2.0)
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
            on_rewrite_available: async def cb(payload: dict) -> str
                返回 'approved'（使用改写稿）或 'rejected'（让豆包再改一版）
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
                    qr = await self._extract_qrcode()
                    if qr and not qr_pushed:
                        if qrcode_cb:
                            await qrcode_cb(qr)
                        qr_pushed = True
                    await self._sleep(1.0, 1.5)
                    cur = await self._login_status()
                    if cur == "valid":
                        break
                else:
                    return {
                        "success": False,
                        "status": "need_login",
                        "message": "等待扫码登录超时，请重新发起生成",
                    }

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
                for attempt in range(1, 4):
                    if await self._is_cancelled(cancel_check):
                        return {"success": False, "status": "cancelled", "message": "任务已取消"}
                    await progress_cb(f"豆包拒绝了提示词，正在让豆包改写（第 {attempt} 次）…", 60)
                    rewritten = await self._ask_rewrite(reason, attempt)
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
        """定位输入框并发送提示词。"""
        textarea = None
        try:
            textarea = await self.page.query_selector("textarea")
        except Exception:
            pass
        if not textarea:
            try:
                textarea = await self.page.query_selector("[contenteditable='true']")
            except Exception:
                pass
        if not textarea:
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
        await textarea.fill(prompt)
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
        deadline = time.time() + 180  # 3 分钟
        last_progress = 50
        shot_count = 0
        while time.time() < deadline:
            if await self._is_cancelled(cancel_check):
                return {"status": "cancelled", "message": "任务已取消"}
            await self._sleep(2.5, 3.5)

            try:
                page_text = await self.page.inner_text("body", timeout=5000)
            except Exception:
                page_text = ""
            reject_markers = [
                "包含敏感内容", "违反", "无法生成", "审核未通过",
                "违规", "生成失败", "内容不符合", "安全策略",
            ]
            for m in reject_markers:
                if m in page_text:
                    return {"status": "rejected", "reason": self._extract_reject_reason(page_text, m)}

            try:
                download_btn = await self.page.query_selector(
                    "[class*='download'], button:has-text('下载'), text=下载视频"
                )
                video_el = await self.page.query_selector("video")
            except Exception:
                download_btn = None
                video_el = None
            if download_btn or video_el:
                download_url = await self._resolve_download_url()
                return {"status": "completed", "download_url": download_url}

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

        return {"status": "error", "message": "等待豆包生成超时（3 分钟）"}

    def _extract_reject_reason(self, page_text: str, marker: str) -> str:
        """从页面文本中提取拒绝原因（关键词附近 60 字）。"""
        idx = page_text.find(marker)
        if idx < 0:
            return marker
        start = max(0, idx - 30)
        end = min(len(page_text), idx + 60)
        return page_text[start:end].replace("\n", " ").strip()

    async def _ask_rewrite(self, reason: str, attempt: int = 1) -> Optional[str]:
        """在同一个会话里追加一条消息，让豆包把提示词改成合规版本。"""
        if attempt <= 1:
            instruction = (
                "请把上面那条被拒绝的提示词改写成合规版本。只修改违规/敏感内容，"
                "保留剧情、时长、镜头结构和风格，直接输出改写后的提示词全文，不要任何解释。"
                f"（拒绝原因参考：{reason}）"
            )
        else:
            instruction = (
                "上一版改写稿仍未通过/用户不满意，请继续修改上面那条提示词。"
                "只修改有问题的内容，保留剧情、时长、镜头结构和风格，"
                "直接输出改写后的提示词全文，不要任何解释。"
                f"（参考意见：{reason}）"
            )
        ok = await self._send_prompt(instruction)
        if not ok:
            return None
        await self._sleep(2.0, 3.0)
        deadline = time.time() + 60
        while time.time() < deadline:
            await self._sleep(2.0, 3.0)
            rewritten = await self._extract_last_assistant_text()
            if rewritten and len(rewritten) > 10:
                return rewritten
        return None

    async def _extract_last_assistant_text(self) -> Optional[str]:
        """提取页面上最后一条助手消息文本。

        豆包页面为动态 React 且经常改版，类名不固定，这里用多选择器兜底
        （assistant / bot-message / message-content / message-item / chat-message
        / ai-message / turn-content / answer 等），去重后取最后一条。
        """
        try:
            selectors = [
                "[class*='assistant']", "[class*='bot-message']", "[class*='message-content']",
                "[class*='message-item']", "[class*='chat-message']", "[class*='ai-message']",
                "[class*='turn-content']", "[class*='answer']", "[class*='response-text']",
            ]
            texts: list[str] = []
            seen: set[str] = set()
            for sel in selectors:
                try:
                    els = await self.page.query_selector_all(sel)
                except Exception:
                    continue
                for el in els:
                    try:
                        t = (await el.inner_text()).strip()
                    except Exception:
                        continue
                    if len(t) > 5 and t not in seen:
                        seen.add(t)
                        texts.append(t)
            return texts[-1] if texts else None
        except Exception:
            return None

    async def _resolve_download_url(self) -> Optional[str]:
        """尝试解析视频下载地址。"""
        try:
            url = await self.page.evaluate(
                """() => {
                    const s = JSON.stringify(window);
                    const m = s.match(/"download_url":"([^"]+)"/);
                    return m ? m[1] : null;
                }"""
            )
            if url:
                return url
        except Exception:
            pass
        try:
            src = await self.page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    return v ? (v.src || v.currentSrc || null) : null;
                }"""
            )
            if src:
                return src
        except Exception:
            pass
        return None
