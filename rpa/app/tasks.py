import asyncio
import logging
import requests
from datetime import datetime
from app.celery_app import celery_app
from app.publishers import VideoChannelPublisher, DouyinPublisher, KuaishouPublisher
from app.config import settings

logger = logging.getLogger(__name__)

def run_async(coro):
    """Helper to run async code in sync Celery task"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def _check_chrome(port=9222):
    """检查 Chrome 浏览器是否可用"""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=5)
        return r.status_code == 200
    except Exception:
        return False

@celery_app.task(bind=True, name="publish_wechat_channels", max_retries=2)
def publish_wechat_channels(self, task_id: str, video_path: str, title: str, 
                            description: str, tags: list, cover_path: str = None,
                            chrome_port: int = None):
    """Publish video to WeChat Channels via Playwright RPA"""
    port = chrome_port or settings.CHROME_DEBUG_PORT
    
    async def _publish():
        publisher = VideoChannelPublisher(chrome_port=port)
        return await publisher.publish(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            cover_path=cover_path,
            require_confirm=settings.RPA_REQUIRE_MANUAL_CONFIRM,
        )
    
    try:
        logger.info(f"Starting WeChat Channels publish for task {task_id}")
        result = run_async(_publish())
        logger.info(f"Publish result for task {task_id}: {result}")
        return result
    except Exception as exc:
        logger.error(f"Publish failed for task {task_id}: {exc}")
        retry_num = getattr(self.request, 'retries', 0)
        countdown = min(60 * (2 ** retry_num), 600)  # 60s, 120s, 240s, max 600s
        if not _check_chrome(port):
            raise Exception("Chrome 浏览器不可用，请检查 RPA 容器状态")
        raise self.retry(exc=exc, countdown=countdown)

@celery_app.task(bind=True, name="publish_douyin", max_retries=2)
def publish_douyin(self, task_id: str, video_path: str, title: str,
                   description: str, tags: list, cover_path: str = None,
                   chrome_port: int = None):
    """Publish video to Douyin via Playwright RPA"""
    port = chrome_port or settings.CHROME_DEBUG_PORT
    
    async def _publish():
        publisher = DouyinPublisher(chrome_port=port)
        return await publisher.publish(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            cover_path=cover_path,
        )
    
    try:
        logger.info(f"Starting Douyin publish for task {task_id}")
        result = run_async(_publish())
        return result
    except Exception as exc:
        logger.error(f"Douyin publish failed for task {task_id}: {exc}")
        retry_num = getattr(self.request, 'retries', 0)
        countdown = min(60 * (2 ** retry_num), 600)  # 60s, 120s, 240s, max 600s
        if not _check_chrome(port):
            raise Exception("Chrome 浏览器不可用，请检查 RPA 容器状态")
        raise self.retry(exc=exc, countdown=countdown)

@celery_app.task(bind=True, name="publish_kuaishou", max_retries=2)
def publish_kuaishou(self, task_id: str, video_path: str, title: str,
                     description: str, tags: list, cover_path: str = None,
                     chrome_port: int = None):
    """Publish video to Kuaishou via Playwright RPA"""
    port = chrome_port or settings.CHROME_DEBUG_PORT
    
    async def _publish():
        publisher = KuaishouPublisher(chrome_port=port)
        return await publisher.publish(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            cover_path=cover_path,
        )
    
    try:
        logger.info(f"Starting Kuaishou publish for task {task_id}")
        result = run_async(_publish())
        return result
    except Exception as exc:
        logger.error(f"Kuaishou publish failed for task {task_id}: {exc}")
        retry_num = getattr(self.request, 'retries', 0)
        countdown = min(60 * (2 ** retry_num), 600)  # 60s, 120s, 240s, max 600s
        if not _check_chrome(port):
            raise Exception("Chrome 浏览器不可用，请检查 RPA 容器状态")
        raise self.retry(exc=exc, countdown=countdown)

@celery_app.task(name="check_cookie_status")
def check_cookie_status():
    """Periodic task to check if platform cookies are still valid"""
    async def _check():
        publisher = VideoChannelPublisher(chrome_port=settings.CHROME_DEBUG_PORT)
        return await publisher.check_login_status()
    
    try:
        result = run_async(_check())
        logger.info(f"Cookie status check: {result}")
        return result
    except Exception as exc:
        logger.error(f"Cookie check failed: {exc}")
        return {"status": "error", "message": str(exc)}
