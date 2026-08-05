from celery import Celery
from app.config import settings

celery_app = Celery(
    "rpa_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_routes={
        "app.tasks.*": {"queue": "publish"},
    },
    task_ack_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,        # 10 min hard limit
    task_soft_time_limit=540,   # 9 min soft limit
    result_expires=86400,       # 24h
    broker_connection_retry_on_startup=True,
    broker_heartbeat=30,
)

celery_app.autodiscover_tasks(["app"])
