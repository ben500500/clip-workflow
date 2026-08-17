"""wechat_download Celery 任务（独立 wechat_dl 队列）。

并入形态：使用主系统 `app.celery.tasks.celery_app` 注册任务，并通过
`app/celery/tasks.py` 顶部 `import wechat_download.tasks` 触发注册，
worker 以 `-A app.celery.tasks` 启动即可发现并消费 `wechat_dl` 队列任务。

可剥离性：任务函数自包含（仅调用本包 service），剥离时可替换为独立
Celery app 实例，逻辑零改动。
"""

import logging
import uuid

from app.celery.tasks import celery_app, run_async

from wechat_download.service import run_download_pipeline, RetryableImportError

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="wechat_dl.download", max_retries=1, default_retry_delay=30)
def task_wechat_dl_download(self, task_id: str):
    """执行视频号下载流水线（解析 → 拉流 → 入库）。

    task_id 为 wechat_download_tasks.id（字符串形式）。

    失败重试（P3-1）：对可重试的瞬态失败（下载中断/限流，RetryableImportError）
    显式 self.retry()，利用已保留的临时文件断点续传；不可重试失败（链接失效、
    解析失败、MinIO 入库失败）直接置 FAILURE，避免无效重试。
    """
    self.update_state(state="STARTED", meta={"progress": 0, "message": "任务启动"})
    try:
        result = run_async(run_download_pipeline(uuid.UUID(task_id)))
        if not result.get("ok"):
            err = result.get("error", "下载失败")
            self.update_state(
                state="FAILURE",
                meta={"progress": 0, "message": err},
            )
            raise RuntimeError(err)
        return result
    except RetryableImportError as e:
        logger.warning("wechat_dl download retryable failure for %s: %s", task_id, e)
        self.update_state(
            state="RETRY",
            meta={"progress": 0, "message": f"下载中断，自动重试中: {e}"},
        )
        raise self.retry(exc=e) from e
    except Exception as e:
        logger.exception("wechat_dl download task failed for %s", task_id)
        self.update_state(state="FAILURE", meta={"progress": 0, "message": str(e)})
        raise
