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

from wechat_download.service import (
    RetryableImportError,
    recover_stale_tasks,
    run_download_pipeline,
)

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


@celery_app.task(bind=True, name="wechat_dl.recover_stale")
def task_wechat_dl_recover_stale(self):
    """beat 守护：回收超时未收敛的非终态下载任务（回写 failed）。

    兜底场景：worker 崩溃 / 节点重启 / 消息丢失，任务永久停在 pending 或中间态。
    Celery 的 task_reject_on_worker_lost 只覆盖「已被消费」的任务，消息丢失时
    无人消费，因此必须有库侧巡检兜底（参考 remotion_stale_recovery_task）。

    回写 failed 后前端「重试」按钮即可用（retry_task 亦放宽支持超时 pending）。
    """
    try:
        recovered = run_async(recover_stale_tasks())
        if recovered:
            logger.warning("wechat_dl stale recovery: %s 条任务回写 failed", len(recovered))
        return {"ok": True, "affected": len(recovered), "tasks": recovered}
    except Exception as e:
        logger.exception("wechat_dl stale recovery failed: %s", e)
        return {"ok": False, "error": str(e)}
