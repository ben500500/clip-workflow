"""lan_source Celery 任务（独立 lan_source 队列，并入 worker-fast）。

并入形态：使用主系统 `app.celery.tasks.celery_app` 注册任务，并通过
`app/celery/tasks.py` 顶部 `import lan_source.tasks` 触发注册。

可剥离性：任务函数自包含（仅调用本包 service），剥离时可替换为独立
Celery app 实例，逻辑零改动。
"""

import logging
import uuid

from app.celery.tasks import celery_app, run_async

from lan_source.service import run_import_pipeline, RetryableLanSourceError

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="lan_source.import_episodes", max_retries=2, default_retry_delay=30)
def task_lan_source_import(self, task_id: str):
    """执行局域网剧集导入流水线（发现直链 → 下载 → 入库）。

    task_id 为 lan_source_imports.id（字符串形式）。

    失败重试：对可重试的瞬态失败（发现/下载中断、网络抖动，RetryableLanSourceError）
    显式 self.retry()（配合断点续传）；不可重试失败（源不可达、MinIO 入库失败）
    直接置 FAILURE，避免无效重试。
    """
    self.update_state(state="STARTED", meta={"progress": 0, "message": "任务启动"})
    try:
        result = run_async(run_import_pipeline(uuid.UUID(task_id)))
        if not result.get("ok"):
            err = result.get("error", "导入失败")
            self.update_state(state="FAILURE", meta={"progress": 0, "message": err})
            raise RuntimeError(err)
        return result
    except RetryableLanSourceError as e:
        logger.warning("lan_source import retryable failure for %s: %s", task_id, e)
        self.update_state(state="RETRY", meta={"progress": 0, "message": f"网络抖动，自动重试中: {e}"})
        raise self.retry(exc=e) from e
    except Exception as e:
        logger.exception("lan_source import task failed for %s", task_id)
        self.update_state(state="FAILURE", meta={"progress": 0, "message": str(e)})
        raise
