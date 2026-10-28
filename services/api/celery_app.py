"""Configuración compartida de Celery para la API y los workers."""
from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "brasaland",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    result_expires=24 * 60 * 60,
    task_default_queue="default",
    task_routes={"tasks.run_pipeline": {"queue": "default"}},
    timezone="UTC",
    enable_utc=True,
)

app = celery_app
