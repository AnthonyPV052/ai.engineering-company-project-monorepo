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

from celery_app import celery_app

logger = logging.getLogger("celery.tasks.rfp")

# Ensure monorepo root and API dir are on sys.path.
# In the Docker container the file lives at /app/rfp_tasks.py (mounted from
# services/api), so `parents[2]` may not exist. We resolve the layout robustly:
#   - If /app/rfp_tasks.py (container), API_DIR = /app, REPO_ROOT = /app
#   - If services/api/rfp_tasks.py (local monorepo), API_DIR = services/api,
#     REPO_ROOT = monorepo root (parents[2])
_self = Path(__file__).resolve()
try:
    REPO_ROOT = _self.parents[2]
except IndexError:
    # Shallow layout (container /app): the api dir is this file's parent.
    REPO_ROOT = _self.parent
API_DIR = _self.parent
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


# ---------------------------------------------------------------------------
# Part 2 — RFP response generation pipeline
# ---------------------------------------------------------------------------


@celery_app.task(bind=True, max_retries=2, acks_late=True, name="tasks.run_rfp_response_generation")
def run_rfp_response_generation(self: Any, ticket_id: str) -> dict[str, Any]:
    """Execute the Part 2 response generation pipeline from Part 1 handoff."""
    _ensure_sys_path()

    started = time.perf_counter()
    attempt = self.request.retries + 1

    try:
        from data.pipelines.rfp_intake.graph_part2 import trigger_part2

        logger.info("task=%s ticket=%s attempt=%s starting Part 2",
                     self.request.id, ticket_id, attempt)

        result = trigger_part2(ticket_id)

        duration = time.perf_counter() - started
        logger.info("task=%s ticket=%s attempt=%s Part 2 status=%s duration=%.3fs",
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
            logger.warning("task=%s ticket=%s attempt=%s Part 2 retrying after %.3fs: %s",
                           self.request.id, ticket_id, attempt, duration, exc)
            raise self.retry(exc=exc, countdown=countdown)

        logger.error("task=%s ticket=%s attempt=%s Part 2 failed after %.3fs: %s",
                      self.request.id, ticket_id, attempt, duration, exc)
        _mark_ticket_failed(ticket_id, str(exc))
        raise


# ---------------------------------------------------------------------------
# Part 3 — RFP approval pipeline
# ---------------------------------------------------------------------------


@celery_app.task(bind=True, max_retries=2, acks_late=True, name="tasks.run_rfp_approval_pipeline")
def run_rfp_approval_pipeline(self: Any, ticket_id: str) -> dict[str, Any]:
    """Execute the Part 3 approval pipeline from Part 2 handoff.

    This runs the initial entry into Part 3 (save_interrupts), then returns
    control so humans can approve via the API.
    """
    _ensure_sys_path()

    started = time.perf_counter()
    attempt = self.request.retries + 1

    try:
        from data.pipelines.rfp_intake.graph_part3 import trigger_part3

        logger.info("task=%s ticket=%s attempt=%s starting Part 3",
                     self.request.id, ticket_id, attempt)

        result = trigger_part3(ticket_id)

        duration = time.perf_counter() - started
        logger.info("task=%s ticket=%s attempt=%s Part 3 status=%s duration=%.3fs",
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
            logger.warning("task=%s ticket=%s attempt=%s Part 3 retrying after %.3fs: %s",
                           self.request.id, ticket_id, attempt, duration, exc)
            raise self.retry(exc=exc, countdown=countdown)

        logger.error("task=%s ticket=%s attempt=%s Part 3 failed after %.3fs: %s",
                      self.request.id, ticket_id, attempt, duration, exc)
        _mark_ticket_failed(ticket_id, str(exc))
        raise


@celery_app.task(bind=True, max_retries=2, acks_late=True, name="tasks.resume_rfp_approval")
def resume_rfp_approval(self: Any, ticket_id: str, department_id: str, action: str) -> dict[str, Any]:
    """Resume the Part 3 approval pipeline after a human decision.

    Loads the checkpoint for the given department, processes the decision,
    runs arbitration, and continues to final document if all approvals are done.
    """
    _ensure_sys_path()

    started = time.perf_counter()
    attempt = self.request.retries + 1

    try:
        from data.pipelines.rfp_intake.graph_part3 import resume_ticket

        logger.info("task=%s ticket=%s dept=%s action=%s resuming Part 3",
                     self.request.id, ticket_id, department_id, action, attempt)

        result = resume_ticket(ticket_id, department_id, action)

        duration = time.perf_counter() - started
        logger.info("task=%s ticket=%s dept=%s Part 3 resume status=%s duration=%.3fs",
                     self.request.id, ticket_id, department_id,
                     result.get("status", "unknown"), duration)
        return {
            "ticket_id": ticket_id,
            "department_id": department_id,
            "action": action,
            "status": result.get("status"),
            "duration_seconds": round(duration, 2),
        }

    except Exception as exc:
        duration = time.perf_counter() - started
        if self.request.retries < self.max_retries:
            countdown = 2 ** self.request.retries
            logger.warning("task=%s ticket=%s dept=%s Part 3 resume retrying after %.3fs: %s",
                           self.request.id, ticket_id, department_id, duration, exc)
            raise self.retry(exc=exc, countdown=countdown)

        logger.error("task=%s ticket=%s dept=%s Part 3 resume failed after %.3fs: %s",
                      self.request.id, ticket_id, department_id, duration, exc)
        raise


# Import celery_app at the bottom to avoid circular imports
from celery_app import celery_app  # noqa: E402, F811