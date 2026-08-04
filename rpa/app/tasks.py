import asyncio
import logging
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
        raise self.retry(exc=exc, countdown=60)

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
        raise self.retry(exc=exc, countdown=60)

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
        raise self.retry(exc=exc, countdown=60)

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
