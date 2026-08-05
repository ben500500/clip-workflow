import asyncio
import logging
from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)

class VideoChannelPublisher:
    """视频号自动发布（Playwright RPA）"""
    
    def __init__(self, chrome_port: int = 9222):
        self.chrome_port = chrome_port
        self.creator_url = "https://channels.weixin.qq.com/platform/post/create"
    
    async def publish(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        cover_path: str = None,
        require_confirm: bool = True
    ) -> dict:
        """
        发布视频到视频号
        
        Returns:
            {"success": bool, "video_url": str, "error": str, "status": str, "screenshot": bytes}
        """
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
                # 1. 打开创作中心
                await page.goto(self.creator_url, timeout=30000)
                await page.wait_for_load_state("networkidle")
                
                # 2. 检查登录态
                if await self._need_login(page):
                    return {"success": False, "status": "need_login", "error": "需要扫码登录"}
                
                # 3. 上传视频
                upload_input = await page.wait_for_selector(
                    'input[type="file"]', timeout=5000
                )
                await upload_input.set_input_files(video_path)
                
                # 4. 等待视频转码完成
                upload_ok = await self._wait_for_upload(page)
                if not upload_ok:
                    logger.warning("Video upload may not have completed, proceeding anyway...")
                
                # 5. 填写标题和描述
                title_input = await page.query_selector('[placeholder*="标题"]')
                if title_input:
                    await title_input.fill(title)
                
                desc_input = await page.query_selector('[placeholder*="描述"]')
                if desc_input:
                    await desc_input.fill(description)
                
                # 6. 添加标签
                for tag in tags:
                    tag_input = await page.query_selector('[class*="tag-input"]')
                    if tag_input:
                        await tag_input.click()
                        await page.keyboard.type(f"#{tag}")
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(0.5)
                
                # 7. 设置封面
                if cover_path:
                    await self._set_cover(page, cover_path)
                
                # 8. 人工确认 or 自动发布
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
                logger.error(f"WeChat publish error: {e}")
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
                    "platform": "wechat_channels"
                }
            except Exception as e:
                return {"status": "error", "error": str(e)}
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
    
    async def _need_login(self, page: Page) -> bool:
        """检查是否需要登录"""
        login_btn = await page.query_selector('[class*="login"]')
        return login_btn is not None
    
    async def _wait_for_upload(self, page: Page, timeout: int = 300) -> bool:
        """等待视频上传转码完成"""
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
        """设置封面"""
        try:
            cover_btn = await page.query_selector('[class*="cover-upload"]')
            if cover_btn:
                await cover_btn.click()
                cover_input = await page.wait_for_selector('input[type="file"]')
                if cover_input:
                    await cover_input.set_input_files(cover_path)
        except Exception as e:
            logger.warning(f"Failed to set cover: {e}")
