"""Celery tasks for the RFP intake pipeline.

Runs the LangGraph pipeline in the background after a PDF is uploaded.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("celery.tasks.rfp")

# Ensure monorepo root and API dir are on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "services" / "api"
for p in (str(REPO_ROOT), str(API_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_sys_path() -> None:
    """Idempotent sys.path setup for Celery worker context."""
    for p in (str(REPO_ROOT), str(API_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


@celery_app.task(bind=True, max_retries=2, acks_late=True, name="tasks.run_rfp_pipeline")
def run_rfp_pipeline(self: Any, ticket_id: str, pdf_path: str) -> dict[str, Any]:
    """Execute the RFP intake LangGraph pipeline in background."""
    _ensure_sys_path()

    started = time.perf_counter()
    attempt = self.request.retries + 1

    try:
        from data.pipelines.rfp_intake.graph import run_pipeline

        logger.info("task=%s ticket=%s attempt=%s starting pipeline",
                     self.request.id, ticket_id, attempt)

        result = run_pipeline(ticket_id=ticket_id, pdf_path=pdf_path)

        duration = time.perf_counter() - started
        logger.info("task=%s ticket=%s attempt=%s status=%s duration=%.3fs",
                     self.request.id, ticket_id, attempt,
                     result.get("status", "unknown"), duration)
        return {
            "ticket_id": ticket_id,
            "status": result.get("status"),
            "duration_seconds": round(duration, 2),
        }

    except Exception as exc:
        duration = time.perf_counter() - started
        if self.request.retries < self.max_retries:
            countdown = 2 ** self.request.retries
            logger.warning("task=%s ticket=%s attempt=%s retrying after %.3fs: %s",
                           self.request.id, ticket_id, attempt, duration, exc)
            raise self.retry(exc=exc, countdown=countdown)

        logger.error("task=%s ticket=%s attempt=%s failed after %.3fs: %s",
                      self.request.id, ticket_id, attempt, duration, exc)
        # Mark ticket as failed
        _mark_ticket_failed(ticket_id, str(exc))
        raise


def _mark_ticket_failed(ticket_id: str, error: str) -> None:
    """Mark a ticket as descartado with error detail."""
    try:
        from datetime import datetime, timezone
        from sqlmodel import Session

        from database import _get_engine
        from rfp_models import RFPEventLog, RFPTicket

        engine = _get_engine()
        with Session(engine) as db:
            ticket = db.get(RFPTicket, ticket_id)
            if ticket:
                ticket.status = "descartado"
                ticket.updated_at = datetime.now(timezone.utc)
                db.add(ticket)

            event = RFPEventLog(
                ticket_id=ticket_id,
                event="pipeline_error",
                detail=error,
            )
            db.add(event)
            db.commit()
    except Exception as persist_exc:
        logger.error("Failed to mark ticket %s as failed: %s", ticket_id, persist_exc)


# Import celery_app at the bottom to avoid circular imports
from celery_app import celery_app  # noqa: E402, F811