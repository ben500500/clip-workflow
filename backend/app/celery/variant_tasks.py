"""多视频号素材去重：素材变体生成 / 指纹校验 Celery 任务（圆桌定稿 Phase 1）。

任务：
- generate_variants_task：对基准切片输出生成 N 套结构性差异变体（异步，不阻塞主链路），
  生成后自动计算指纹、撞车自动换参重试、落库 ClipVariant + VideoFingerprint。
- verify_variant_fingerprint_task：发布前复核变体指纹，确认与同组其它变体拉开距离。

护栏：variant_count=1 时任务直接返回（零侵入）；生成异步不阻塞主链路；
撞车失败宁可降级人工处理，绝不把同素材原样发多号。
"""
import asyncio
import logging

from app.celery.tasks import celery_app, run_async
from app.services import variant_service as vs

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_variants_task(
    self,
    output_id: str,
    count: int = 1,
    base_dedupe: dict = None,
    created_by: str = None,
    thresholds: dict = None,
):
    """对基准切片输出生成 N 个结构性差异变体，并做指纹校验 + 撞车自动换参重试。

    A1：无论成功/失败/异常/重试耗尽，finally 都必须把该输出下仍为 running/pending
    的变体回写 failed（收敛永久 running），再由 Celery 决定重试。
    """
    try:
        result = run_async(
            vs.generate_variants_for_output(
                output_id=output_id,
                count=count,
                base_dedupe=base_dedupe,
                created_by=created_by,
                thresholds=thresholds,
            )
        )
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result
    except Exception as e:
        logger.exception("generate_variants failed output=%s: %s", output_id, e)
        # A1 兜底：把该输出下遗留的 running/pending 变体统一回写 failed，
        # 杜绝 Celery 重试间隔/队列拥挤期间永久 running（最早堆积 1 天+ 的根因）。
        try:
            run_async(vs.mark_output_variants_failed(
                output_id, f"generate failed: {e}"
            ))
        except Exception as mark_e:
            logger.error("mark_output_variants_failed output=%s failed: %s", output_id, mark_e)
        self.retry(exc=e)


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def verify_variant_fingerprint_task(self, variant_id: str, thresholds: dict = None):
    """发布前复核变体指纹，返回 {safe, distances, reason}。"""
    return run_async(vs.verify_variant_fingerprint(variant_id, thresholds))
