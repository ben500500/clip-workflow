"""
Publish service - RPA-based video publishing to short video platforms.

Uses Playwright to automate video uploads to platforms like WeChat Video Channel,
Douyin, and Kuaishou. Supports screenshot-based manual confirmation workflow.
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


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
    ):
        self.chrome_debug_port = chrome_debug_port
        self.cookie_file = cookie_file
        self.require_manual_confirm = require_manual_confirm
        self.browser = None
        self.page = None

    async def publish(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        cover_file_key: Optional[str] = None,
        mini_program_link: Optional[str] = None,
    ) -> dict:
        """
        Execute the full publishing workflow.

        Returns:
            dict with keys: success, published_url, published_id, screenshot_path, error
        """
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                # Connect to existing Chrome or launch new browser
                if self.chrome_debug_port:
                    from app.config import settings as s
                    self.browser = await p.chromium.connect_over_cdp(
                        f"http://{s.CHROME_DEBUG_HOST}:{self.chrome_debug_port}"
                    )
                    context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
                else:
                    self.browser = await p.chromium.launch(headless=True)
                    context = await self.browser.new_context()

                self.page = await context.new_page()

                # Check login state
                if await self._need_login():
                    return {
                        "success": False,
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
                    # Return screenshot path and wait for manual confirmation
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
            return {
                "success": False,
                "error": str(e),
                "screenshot_path": None,
                "published_url": None,
                "published_id": None,
            }
        finally:
            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass

    async def _need_login(self) -> bool:
        """Check if the current session requires login."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            # Check for login indicators (e.g., QR code or login button)
            login_selector = await self.page.query_selector(".login-guide, .qrcode-login, [class*='login']")
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
            link_input = await self.page.query_selector("input[placeholder*='链接'], input[placeholder*='link']")
            if link_input:
                await link_input.fill(link)
                await asyncio.sleep(1)
                confirm_btn = await self.page.query_selector("button:has-text('确定'), button:has-text('确认')")
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

    async def confirm_publish(self) -> dict:
        """Confirm a pending publish action (called after manual screenshot review)."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                if self.chrome_debug_port:
                    from app.config import settings as s
                    self.browser = await p.chromium.connect_over_cdp(
                        f"http://{s.CHROME_DEBUG_HOST}:{self.chrome_debug_port}"
                    )
                    context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
                else:
                    self.browser = await p.chromium.launch(headless=True)
                    context = await self.browser.new_context()

                self.page = await context.new_page()
                await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                return {
                    "success": True,
                    "published_url": published_url,
                    "published_id": published_id,
                }
        except Exception as e:
            logger.error(f"Confirm publish failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
        finally:
            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass


class DouyinPublisher(VideoChannelPublisher):
    """Publisher for Douyin (抖音) platform - stub implementation."""

    PLATFORM = "douyin"
    CREATOR_URL = "https://creator.douyin.com/creator-micro/content/upload"

    async def _need_login(self) -> bool:
        """Check Douyin login state."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            login_selector = await self.page.query_selector(".login-container, [class*='login']")
            return login_selector is not None
        except Exception:
            return True

    async def _set_tags(self, tags: list):
        """Set Douyin-specific tags (话题)."""
        tag_input = await self.page.query_selector("[class*='tag'] input, [placeholder*='话题']")
        if tag_input:
            for tag in tags:
                await tag_input.fill(f"#{tag}")
                await asyncio.sleep(0.5)
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(0.3)


class KuaishouPublisher(VideoChannelPublisher):
    """Publisher for Kuaishou (快手) platform - stub implementation."""

    PLATFORM = "kuaishou"
    CREATOR_URL = "https://cp.kuaishou.com/article/publish/video"

    async def _need_login(self) -> bool:
        """Check Kuaishou login state."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            login_selector = await self.page.query_selector("[class*='login'], .qr-login")
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
        raise ValueError(f"Unsupported platform: {platform}. Supported: {list(publishers.keys())}")
    return publisher_class(**kwargs)
