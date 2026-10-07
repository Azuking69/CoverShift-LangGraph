# Celery インスタンス定義・Redis接続設定
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "covershift_v4",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["covershift_prototype_V4_celery_redis.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Tokyo",
    enable_utc=True,
    # Windows環境での動作を安定させるための設定
    worker_connection_max_retries=None,
)