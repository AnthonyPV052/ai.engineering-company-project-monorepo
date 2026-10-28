"""Tareas Celery de larga duración y registro de Dead Letter Queue."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from celery_app import celery_app

logger = logging.getLogger("celery.tasks")


def _database_url() -> str | None:
    """Load the API .env when the worker is started outside FastAPI."""
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _record_dlq(task_id: str, attempt: int, error: str) -> None:
    """Persiste el fallo final si hay una base SQL configurada."""
    database_url = _database_url()
    if database_url:
        from sqlalchemy import create_engine
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS celery_dead_letter_queue (
                    id BIGSERIAL PRIMARY KEY,
                    task_id VARCHAR(255) NOT NULL,
                    attempt INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """))
            connection.execute(
                text("INSERT INTO celery_dead_letter_queue "
                     "(task_id, attempt, error, created_at) "
                     "VALUES (:task_id, :attempt, :error, :created_at)"),
                {"task_id": task_id, "attempt": attempt, "error": error,
                 "created_at": datetime.now(timezone.utc)},
            )
        engine.dispose()
        return

    # Fallback local para desarrollo sin PostgreSQL.
    path = Path(__file__).resolve().parent / "data" / "celery_dlq.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(f"{datetime.now(timezone.utc).isoformat()} "
                     f"task_id={task_id} attempt={attempt} error={error}\n")


@celery_app.task(bind=True, max_retries=3, acks_late=True, name="tasks.run_pipeline")
def run_pipeline(self: Any, week_start: str | None = None) -> dict[str, Any]:
    """Ejecuta el pipeline pesado fuera del proceso de FastAPI."""
    started = time.perf_counter()
    attempt = self.request.retries + 1
    try:
        from datetime import date
        import sys
        repo_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo_root))
        from data.pipelines.pipeline import run_business_performance_pipeline

        result = run_business_performance_pipeline(
            week_start=date.fromisoformat(week_start) if week_start else None
        )
        if result.get("snapshot_path") is not None:
            result["snapshot_path"] = str(result["snapshot_path"])
        duration = time.perf_counter() - started
        logger.info("task_id=%s attempt=%s status=success duration=%.3fs",
                    self.request.id, attempt, duration)
        return result
    except Exception as exc:
        duration = time.perf_counter() - started
        if self.request.retries < self.max_retries:
            countdown = 2 ** self.request.retries
            logger.warning("task_id=%s attempt=%s status=retry duration=%.3fs error=%s",
                           self.request.id, attempt, duration, exc, exc_info=True)
            raise self.retry(exc=exc, countdown=countdown)
        logger.error("task_id=%s attempt=%s status=failure duration=%.3fs error=%s",
                     self.request.id, attempt, duration, exc, exc_info=True)
        _record_dlq(self.request.id, attempt, str(exc))
        raise


@celery_app.task(name="tasks.demo_success")
def demo_success() -> dict[str, str]:
    """Small successful task used to verify Flower during development."""
    logger.info("task_id=%s attempt=1 status=success duration=0s", demo_success.request.id)
    return {"status": "completed", "message": "Flower demo task completed"}


@celery_app.task(bind=True, max_retries=3, name="tasks.demo_failure")
def demo_failure(self: Any) -> None:
    """Controlled failure used to demonstrate retries and the DLQ."""
    attempt = self.request.retries + 1
    error = "Controlled Flower DLQ demonstration failure"
    if self.request.retries < self.max_retries:
        logger.warning("task_id=%s attempt=%s status=retry error=%s",
                       self.request.id, attempt, error)
        raise self.retry(exc=RuntimeError(error), countdown=2 ** self.request.retries)
    logger.error("task_id=%s attempt=%s status=failure error=%s",
                 self.request.id, attempt, error)
    _record_dlq(self.request.id, attempt, error)
    raise RuntimeError(error)
