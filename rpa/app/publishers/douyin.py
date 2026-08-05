import asyncio
import logging
from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)

class DouyinPublisher:
    """抖音自动发布（Playwright RPA）"""
    
    def __init__(self, chrome_port: int = 9222):
        self.chrome_port = chrome_port
        self.creator_url = "https://creator.douyin.com/creator-micro/content/upload"
    
    async def publish(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        cover_path: str = None,
        require_confirm: bool = True
    ) -> dict:
        """发布视频到抖音"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.chrome_port}"
            )
            contexts = browser.contexts
            if not contexts:
                return {"success": False, "status": "error", "error": "浏览器没有打开的上下文，请检查 Chrome 是否正常"}
            context = contexts[0]
            page = await context.new_page()
            
            try:
                await page.goto(self.creator_url, timeout=30000)
                await page.wait_for_load_state("networkidle")
                
                # Check login
                if await self._need_login(page):
                    return {"success": False, "status": "need_login", "error": "需要扫码登录抖音"}
                
                # Upload video
                upload_input = await page.wait_for_selector('input[type="file"]', timeout=5000)
                await upload_input.set_input_files(video_path)
                
                # Wait for upload
                upload_ok = await self._wait_for_upload(page)
                if not upload_ok:
                    logger.warning("Video upload may not have completed, proceeding anyway...")
                
                # Fill title/description
                desc_input = await page.query_selector('[class*="desc"] [contenteditable="true"]')
                if desc_input:
                    full_text = f"{title} {description}"
                    for tag in tags:
                        full_text += f" #{tag}"
                    await desc_input.fill(full_text)
                
                # Set cover
                if cover_path:
                    await self._set_cover(page, cover_path)
                
                if require_confirm:
                    screenshot = await page.screenshot()
                    return {
                        "success": False,
                        "status": "pending_confirm",
                        "screenshot": screenshot,
                        "message": "请确认后点击发布"
                    }
                else:
                    publish_btn = await page.query_selector('button:has-text("发布")')
                    if publish_btn:
                        await publish_btn.click()
                        await asyncio.sleep(3)
                        return {"success": True, "video_url": page.url, "status": "published"}
                    return {"success": False, "error": "未找到发布按钮"}
                    
            except Exception as e:
                logger.error(f"Douyin publish error: {e}")
                return {"success": False, "status": "error", "error": str(e)}
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
    
    async def check_login_status(self) -> dict:
        """检查登录态是否有效"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.chrome_port}"
            )
            contexts = browser.contexts
            if not contexts:
                return {"status": "error", "error": "浏览器没有打开的上下文，请检查 Chrome 是否正常"}
            context = contexts[0]
            page = await context.new_page()
            try:
                await page.goto(self.creator_url, timeout=30000)
                await page.wait_for_load_state("networkidle")
                need_login = await self._need_login(page)
                return {
                    "status": "expired" if need_login else "valid",
                    "platform": "douyin"
                }
            except Exception as e:
                return {"status": "error", "error": str(e)}
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
    
    async def _need_login(self, page: Page) -> bool:
        login_btn = await page.query_selector('[class*="login"]')
        return login_btn is not None
    
    async def _wait_for_upload(self, page: Page, timeout: int = 300) -> bool:
        try:
            await page.wait_for_selector(
                '[class*="upload-progress"]',
                state="hidden",
                timeout=timeout * 1000
            )
            return True
        except Exception:
            logger.warning("Upload progress indicator not found or timed out")
            return False
    
    async def _set_cover(self, page: Page, cover_path: str):
        try:
            cover_btn = await page.query_selector('[class*="cover"]')
            if cover_btn:
                await cover_btn.click()
                cover_input = await page.wait_for_selector('input[type="file"]')
                if cover_input:
                    await cover_input.set_input_files(cover_path)
        except Exception as e:
            logger.warning(f"Failed to set cover: {e}")
