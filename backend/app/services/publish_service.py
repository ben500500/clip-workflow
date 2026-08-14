"""
Publish service - RPA-based video publishing to short video platforms.

Uses Playwright to automate video uploads to platforms like WeChat Video Channel,
Douyin, and Kuaishou. Supports screenshot-based manual confirmation workflow.

设计说明（一键发布收敛）：
- 唯一的 Publisher 实现收敛到本模块，由 backend Celery worker 通过 CDP 连接
  rpa_worker 容器内常驻的 Chromium 执行（CHROME_DEBUG_HOST:CHROME_DEBUG_PORT）。
- 人工确认流程：publish() 填写表单后返回 pending_confirm，并把已填好表单的
  Playwright page 缓存到进程内 _PENDING_TABS；confirm_publish() 复用同一 tab
  点击「发布」，避免重新打开页面导致表单丢失。
- 若确认时缓存失效（worker 重启/超时），退化为重新打开创作中心并尽力点击发布。
"""

import asyncio
import logging
import os
import tempfile
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 进程内待确认发布 tab 缓存：publish_task_id -> {"browser": Browser, "page": Page}
# backend worker 采用 --concurrency=1 串行处理 publish 队列任务，publish 与后续
# confirm 在同一 worker 进程内执行，模块级缓存跨任务存活可用。
_PENDING_TABS: dict = {}
_PENDING_TABS_LOCK = threading.Lock()

# 进程级共享 Playwright 实例：backend worker 常驻，所有 CDP 连接复用同一个
# driver，避免缓存 tab 的 browser 代理因 driver 被 GC 而失效。
_shared_playwright = None
_shared_playwright_lock = threading.Lock()


async def _get_playwright():
    """获取进程级共享 Playwright 实例（懒启动，worker 进程内复用）。"""
    global _shared_playwright
    if _shared_playwright is None:
        # Celery worker 默认单进程；用锁保证多线程/多 worker 场景下只初始化一次
        with _shared_playwright_lock:
            if _shared_playwright is None:
                from playwright.async_api import async_playwright
                _shared_playwright = await async_playwright().start()
    return _shared_playwright


def _cache_pending_tab(task_id: str, browser, page) -> None:
    """缓存已填好表单的待确认页面。"""
    with _PENDING_TABS_LOCK:
        # 同任务重复发布时先释放旧 tab
        old = _PENDING_TABS.pop(task_id, None)
        if old:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(old["browser"].close())
                else:
                    loop.run_until_complete(old["browser"].close())
            except Exception:
                pass
        _PENDING_TABS[task_id] = {"browser": browser, "page": page}


def _pop_pending_tab(task_id: str):
    """取出并移除待确认页面缓存。"""
    with _PENDING_TABS_LOCK:
        return _PENDING_TABS.pop(task_id, None)


def release_pending_tab(task_id: str) -> None:
    """释放待确认 tab（取消/失败时调用）。"""
    entry = _pop_pending_tab(task_id)
    if entry:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(entry["browser"].close())
            else:
                loop.run_until_complete(entry["browser"].close())
        except Exception:
            pass


class VideoChannelPublisher:
    """
    Playwright-based publisher for WeChat Video Channel (微信视频号).

    Workflow:
    1. Connect to Chrome via debug port or launch new browser
    2. Navigate to the Video Channel creator page
    3. Upload video file
    4. Set title, description, tags, cover image
    5. Optionally attach mini program link
    6. Take screenshot for manual confirmation
    7. Wait for user confirmation or auto-publish
    """

    PLATFORM = "wechat_channel"
    CREATOR_URL = "https://channels.weixin.qq.com/platform/post/create"

    def __init__(
        self,
        chrome_debug_port: int = 9222,
        cookie_file: Optional[str] = None,
        require_manual_confirm: bool = True,
        cdp_url: Optional[str] = None,
        cdp_token: Optional[str] = None,
    ):
        self.chrome_debug_port = chrome_debug_port
        self.cookie_file = cookie_file
        self.require_manual_confirm = require_manual_confirm
        # 多运营者（R19）：显式 CDP 目标地址 + 短期访问 token（经 cdp_proxy 鉴权转发）
        self.cdp_url = cdp_url
        self.cdp_token = cdp_token
        self.browser = None
        self.page = None
        self._playwright = None

    async def _connect(self) -> None:
        """连接常驻 Chromium（CDP）或启动独立浏览器。

        多运营者（flag=true）时使用 cdp_url + cdp_token（注入 Authorization 头，R19）；
        否则按 chrome_debug_port 连 rpa_worker（一期旧链路，零侵入）。
        """
        self._playwright = await _get_playwright()
        if self.cdp_url:
            # R19：握手前注入 Authorization: Bearer <token>，由 cdp_proxy 校验后转发
            headers = {}
            if self.cdp_token:
                headers["Authorization"] = f"Bearer {self.cdp_token}"
            self.browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_url, headers=headers
            )
        elif self.chrome_debug_port:
            from app.config import settings as s
            self.browser = await self._playwright.chromium.connect_over_cdp(
                f"http://{s.CHROME_DEBUG_HOST}:{self.chrome_debug_port}"
            )
            context = (
                self.browser.contexts[0]
                if self.browser.contexts
                else await self.browser.new_context()
            )
        else:
            self.browser = await self._playwright.chromium.launch(headless=True)
            context = await self.browser.new_context()
        self.page = await context.new_page()

    async def publish(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        cover_file_key: Optional[str] = None,
        mini_program_link: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> dict:
        """
        Execute the full publishing workflow.

        Returns:
            dict with keys: success, status, published_url, published_id,
                            screenshot_path, error
        """
        try:
            await self._connect()

            # Check login state
            if await self._need_login():
                await self._close_connection()
                return {
                    "success": False,
                    "status": "need_login",
                    "error": "Not logged in. Please login first via Chrome debug port.",
                    "screenshot_path": None,
                }

            # Navigate to creator page
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)

            # Upload video
            await self._upload_video(video_path)

            # Set title and description
            await self._set_title(title)
            if description:
                await self._set_description(description)

            # Set tags
            if tags:
                await self._set_tags(tags)

            # Set cover image if provided
            if cover_file_key:
                await self._set_cover(cover_file_key)

            # Attach mini program link if provided
            if mini_program_link:
                await self._attach_mini_program(mini_program_link)

            # Take screenshot for review
            screenshot_path = await self._take_screenshot()

            if self.require_manual_confirm:
                # 保留已填好表单的 tab，供 confirm 复用点击发布（进程内缓存）
                if task_id:
                    _cache_pending_tab(task_id, self.browser, self.page)
                    # 多运营者（R13/R18）：同时把结构化 payload 外移到 Redis，
                    # 供 worker 重启/多副本时 confirm 幂等重填（含 selector 版本校验）
                    await self._save_pending_payload(
                        task_id, title, description, tags, cover_file_key, mini_program_link
                    )
                    # 连接对象交由缓存管理，不在此关闭
                    self.browser = None
                    self.page = None
                else:
                    await self._close_connection()
                return {
                    "success": True,
                    "status": "pending_confirm",
                    "screenshot_path": screenshot_path,
                    "published_url": None,
                    "published_id": None,
                    "error": None,
                }
            else:
                # Auto-publish
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                await self._close_connection()
                return {
                    "success": True,
                    "status": "published",
                    "screenshot_path": screenshot_path,
                    "published_url": published_url,
                    "published_id": published_id,
                    "error": None,
                }

        except Exception as e:
            logger.error(f"Publishing failed: {e}", exc_info=True)
            await self._close_connection()
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                "screenshot_path": None,
                "published_url": None,
                "published_id": None,
            }

    async def _close_connection(self) -> None:
        """关闭当前 publisher 持有的连接（pending tab 由缓存管理，不在此关闭）。

        共享 Playwright 实例不在此 stop（进程级常驻），只关闭浏览器连接。
        """
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        self._playwright = None
        self.page = None

    async def _need_login(self) -> bool:
        """Check if the current session requires login."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            # Check for login indicators (e.g., QR code or login button)
            login_selector = await self.page.query_selector(
                ".login-guide, .qrcode-login, [class*='login']"
            )
            return login_selector is not None
        except Exception:
            return True

    async def _upload_video(self, video_path: str):
        """Upload the video file through the file input element."""
        upload_input = await self.page.query_selector("input[type='file']")
        if not upload_input:
            raise RuntimeError("Cannot find video upload input element")
        await upload_input.set_input_files(video_path)
        # Wait for upload to complete
        await self._wait_for_upload()

    async def _wait_for_upload(self, timeout: int = 300):
        """Wait for the video upload to complete (up to timeout seconds)."""
        try:
            # Wait for upload progress to disappear or success indicator
            await self.page.wait_for_selector(
                "[class*='upload-success'], [class*='upload-complete'], [class*='preview']",
                timeout=timeout * 1000,
            )
            await asyncio.sleep(3)  # Extra wait for processing
        except Exception:
            logger.warning("Upload wait timed out, continuing anyway...")

    async def _set_title(self, title: str):
        """Set the video title."""
        title_input = await self.page.query_selector(
            "[class*='title'] textarea, [class*='title'] input, [placeholder*='标题']"
        )
        if title_input:
            await title_input.fill("")
            await title_input.fill(title)

    async def _set_description(self, description: str):
        """Set the video description."""
        desc_input = await self.page.query_selector(
            "[class*='desc'] textarea, [class*='description'] textarea, [placeholder*='描述']"
        )
        if desc_input:
            await desc_input.fill("")
            await desc_input.fill(description)

    async def _set_tags(self, tags: list):
        """Set video tags."""
        tag_input = await self.page.query_selector(
            "[class*='tag'] input, [placeholder*='标签'], [placeholder*='话题']"
        )
        if tag_input:
            for tag in tags:
                await tag_input.fill(f"#{tag}")
                await asyncio.sleep(0.5)
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(0.3)

    async def _set_cover(self, cover_file_key: str):
        """Set the video cover image."""
        # Cover key is a MinIO object key; download it locally first.
        local_cover = cover_file_key
        if cover_file_key and not os.path.isfile(cover_file_key):
            from app.services.minio_service import download_to_file

            local_cover = os.path.join(
                tempfile.gettempdir(),
                f"cover_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg",
            )
            ok = await download_to_file("raw-footage", cover_file_key, local_cover)
            if not ok:
                logger.warning("Failed to download cover image from MinIO: %s", cover_file_key)
                return

        cover_btn = await self.page.query_selector(
            "[class*='cover'] [class*='upload'], [class*='cover'] button"
        )
        if cover_btn:
            async with self.page.expect_file_chooser() as fc_info:
                await cover_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(local_cover)
            await asyncio.sleep(2)

    async def _attach_mini_program(self, link: str):
        """Attach a mini program link to the video."""
        link_btn = await self.page.query_selector(
            "[class*='mini-program'], [class*='miniprogram'], [class*='link-btn']"
        )
        if link_btn:
            await link_btn.click()
            await asyncio.sleep(1)
            link_input = await self.page.query_selector(
                "input[placeholder*='链接'], input[placeholder*='link']"
            )
            if link_input:
                await link_input.fill(link)
                await asyncio.sleep(1)
                confirm_btn = await self.page.query_selector(
                    "button:has-text('确定'), button:has-text('确认')"
                )
                if confirm_btn:
                    await confirm_btn.click()

    async def _take_screenshot(self) -> str:
        """Take a screenshot of the current page for review."""
        screenshot_path = os.path.join(
            tempfile.gettempdir(),
            f"publish_screenshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png",
        )
        await self.page.screenshot(path=screenshot_path, full_page=True)
        return screenshot_path

    async def _click_publish(self):
        """Click the publish/submit button."""
        publish_btn = await self.page.query_selector(
            "button:has-text('发布'), button:has-text('Publish'), [class*='publish-btn']"
        )
        if publish_btn:
            await publish_btn.click()
        else:
            raise RuntimeError("Cannot find publish button")

    async def _wait_for_publish(self, timeout: int = 60) -> tuple:
        """Wait for the publish action to complete and return (url, id)."""
        try:
            await self.page.wait_for_url("**/success**", timeout=timeout * 1000)
            await asyncio.sleep(2)
            current_url = self.page.url
            # Try to extract published ID from URL or page content
            published_id = None
            id_el = await self.page.query_selector("[class*='post-id'], [data-id]")
            if id_el:
                published_id = await id_el.get_attribute("data-id")
            return current_url, published_id
        except Exception:
            return self.page.url, None

    async def _save_pending_payload(
        self,
        task_id: str,
        title: str,
        description: str,
        tags: Optional[list],
        cover_file_key: Optional[str],
        mini_program_link: Optional[str],
    ) -> None:
        """把待确认发布的结构化 payload 外移到 Redis（R13/R18）。

        不缓存 page 对象；存标题/描述/标签/封面key/小程序链接 + selector 版本号，
        confirm 时据此全量幂等重填（绝不半填）。TTL 30min。
        """
        try:
            from app.services import multi_operator
            payload = {
                "account_id": None,  # 由 celery 层回填 account_id
                "profile_id": None,
                "cdp_url": self.cdp_url or (
                    f"http://{self.chrome_debug_port}" if self.chrome_debug_port else None
                ),
                "title": title,
                "description": description,
                "tags": tags or [],
                "cover_key": cover_file_key,
                "mini_program_link": mini_program_link,
                # 选择器集中管理并带版本号（R18）：confirm 前校验页面结构匹配
                "selector_version": "v1",
            }
            await multi_operator.save_pending(task_id, payload)
        except Exception as e:
            logger.warning(f"save pending payload to Redis failed: {e}")

    async def _refill_pending_form(self, payload: dict, task_id: Optional[str] = None) -> bool:
        """按 Redis payload 全量幂等重填表单（R13/R18）。

        重填前先校验 selector_version 与当前页面结构是否匹配；不匹配即冻结（置
        selector_mismatch）并触发人工介入，绝不静默乱填/半填。返回 False 表示失败。
        """
        try:
            # R18：前置 selector 校验 —— 以关键表单控件哨兵存在性为判据
            if not await self._selector_ok():
                logger.error("selector version mismatch, freeze pending for manual intervention")
                try:
                    from app.services import multi_operator
                    if task_id:
                        await multi_operator.freeze_pending(task_id)
                except Exception:
                    pass
                return False
            # 清空再填（全量幂等），避免半填
            if payload.get("title"):
                await self._set_title(payload["title"])
            if payload.get("description"):
                await self._set_description(payload["description"])
            if payload.get("tags"):
                await self._set_tags(payload["tags"])
            if payload.get("cover_key"):
                await self._set_cover(payload["cover_key"])
            if payload.get("mini_program_link"):
                await self._attach_mini_program(payload["mini_program_link"])
            return True
        except Exception as e:
            logger.error(f"refill pending form failed: {e}", exc_info=True)
            return False

    async def _selector_ok(self) -> bool:
        """前置校验当前页面结构是否匹配已知 selector 版本（R18）。

        以标题输入框 + 发布按钮等关键控件哨兵存在性为判据；微信改版/页面异常时返回 False。
        """
        try:
            title = await self.page.query_selector("input[placeholder*='标题'], [class*='title'] input")
            publish = await self.page.query_selector(
                "[class*='publish'], [class*='release'], button:has-text('发表'), button:has-text('发布')"
            )
            return title is not None and publish is not None
        except Exception:
            return False

    async def confirm_publish(self, task_id: Optional[str] = None) -> dict:
        """Confirm a pending publish by clicking publish on the prepared tab.

        优先复用 publish() 阶段缓存且已填好表单的 tab；若缓存失效（worker
        重启/超时/页面关闭），则从 Redis payload 幂等重填后再点击发布（R13/R18），
        最后退化为重新打开创作中心尽力点击发布。
        """
        # 1. 复用缓存的待确认 tab
        entry = _pop_pending_tab(task_id) if task_id else None
        if entry:
            try:
                self.browser = entry["browser"]
                self.page = entry["page"]
                await self.page.bring_to_front()
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                await self._close_connection()
                return {
                    "success": True,
                    "published_url": published_url,
                    "published_id": published_id,
                }
            except Exception as e:
                logger.error(f"Confirm publish via cached tab failed: {e}", exc_info=True)
                await self._close_connection()
                # 继续尝试 fallback

        # 2. fallback：从 Redis payload 幂等重填（R13/R18）后再点击发布
        pending = None
        if task_id:
            try:
                from app.services import multi_operator
                pending = await multi_operator.get_pending(task_id)
            except Exception:
                pending = None
        if pending:
            try:
                await self._connect()
                await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
                refilled = await self._refill_pending_form(pending, task_id=task_id)
                if not refilled:
                    await self._close_connection()
                    # R18：selector 不匹配已冻结，人工介入，0 误发
                    return {
                        "success": False,
                        "error": "selector_mismatch: form structure changed, pending frozen for manual intervention",
                    }
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                await self._close_connection()
                try:
                    await multi_operator.delete_pending(task_id)
                except Exception:
                    pass
                return {
                    "success": True,
                    "published_url": published_url,
                    "published_id": published_id,
                }
            except Exception as e:
                logger.error(f"Confirm publish via redis refill failed: {e}", exc_info=True)
                await self._close_connection()
                return {"success": False, "error": str(e)}

        # 3. 兜底：重新连接并打开创作中心尽力点击发布（一期旧行为）
        try:
            await self._connect()
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await self._click_publish()
            published_url, published_id = await self._wait_for_publish()
            await self._close_connection()
            return {
                "success": True,
                "published_url": published_url,
                "published_id": published_id,
            }
        except Exception as e:
            logger.error(f"Confirm publish failed: {e}", exc_info=True)
            await self._close_connection()
            return {"success": False, "error": str(e)}

    async def check_login_status(self) -> dict:
        """检查当前登录态是否有效。"""
        try:
            await self._connect()
            need_login = await self._need_login()
            await self._close_connection()
            return {
                "status": "expired" if need_login else "valid",
                "platform": self.PLATFORM,
            }
        except Exception as e:
            logger.error(f"Check login status failed: {e}", exc_info=True)
            await self._close_connection()
            return {"status": "error", "platform": self.PLATFORM, "error": str(e)}


class DouyinPublisher(VideoChannelPublisher):
    """Publisher for Douyin (抖音) platform."""

    PLATFORM = "douyin"
    CREATOR_URL = "https://creator.douyin.com/creator-micro/content/upload"

    async def _need_login(self) -> bool:
        """Check Douyin login state."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            login_selector = await self.page.query_selector(
                ".login-container, [class*='login']"
            )
            return login_selector is not None
        except Exception:
            return True

    async def _set_tags(self, tags: list):
        """Set Douyin-specific tags (话题)."""
        tag_input = await self.page.query_selector(
            "[class*='tag'] input, [placeholder*='话题']"
        )
        if tag_input:
            for tag in tags:
                await tag_input.fill(f"#{tag}")
                await asyncio.sleep(0.5)
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(0.3)


class KuaishouPublisher(VideoChannelPublisher):
    """Publisher for Kuaishou (快手) platform."""

    PLATFORM = "kuaishou"
    CREATOR_URL = "https://cp.kuaishou.com/article/publish/video"

    async def _need_login(self) -> bool:
        """Check Kuaishou login state."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            login_selector = await self.page.query_selector(
                "[class*='login'], .qr-login"
            )
            return login_selector is not None
        except Exception:
            return True


def get_publisher(platform: str, **kwargs) -> VideoChannelPublisher:
    """Factory function to get the appropriate publisher for a platform."""
    publishers = {
        "wechat_channel": VideoChannelPublisher,
        "douyin": DouyinPublisher,
        "kuaishou": KuaishouPublisher,
    }
    publisher_class = publishers.get(platform)
    if not publisher_class:
        raise ValueError(
            f"Unsupported platform: {platform}. Supported: {list(publishers.keys())}"
        )
    return publisher_class(**kwargs)
