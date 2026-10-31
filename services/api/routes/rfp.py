"""HTTP routes for RFP intake (Parte 1 + Part 2).

POST /api/rfp/upload                        — Upload PDF, create ticket, trigger background pipeline
GET  /api/rfp/tickets                       — List all tickets
GET  /api/rfp/tickets/{ticket_id}           — Get ticket detail + metadata + department sections
POST /api/rfp/tickets/{ticket_id}/generate  — Trigger Part 2 (generation + evaluation) from Part 1 handoff
GET  /api/rfp/tickets/{ticket_id}/part2     — Get Part 2 results (drafts + evaluations)

Follows the existing pattern from routes/inventory.py.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request, status
from sqlmodel import Session, select

from database import get_db
from rfp_models import (
    DepartmentSection,
    RFPEventLog,
    RFPMetadata,
    RFPTicket,
    TICKET_STATUS_ANALISIS_COMPLETO,
    TICKET_STATUS_ANALIZANDO,
    TICKET_STATUS_GENERANDO_BORRADOR,
    TICKET_STATUS_EN_EVALUACION,
    TICKET_STATUS_NEEDS_HUMAN_REVIEW,
    TICKET_STATUS_DESCARTADO,
)
from security import get_current_user

logger = logging.getLogger("api.rfp")

router = APIRouter(
    prefix="/api/rfp",
    tags=["rfp"],
    dependencies=[Depends(get_current_user)],
)

# Where uploaded PDFs are stored
# Inside container: /app/routes/rfp.py → /app/data/raw
DATA_RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Schemas (inline to keep this file self-contained)
# ---------------------------------------------------------------------------


class TicketListItem:
    """Lightweight ticket representation for list endpoint."""
    pass


# ---------------------------------------------------------------------------
# POST /api/rfp/upload — Upload PDF and create ticket
# ---------------------------------------------------------------------------


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_rfp(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a PDF RFP, create a ticket, and trigger background processing.

    Returns immediately with 202 + ticket_id. The pipeline runs async via Celery.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se aceptan archivos PDF.",
        )

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )

    # Generate ticket ID
    ticket_id = str(uuid.uuid4())

    # Save PDF to data/raw/
    safe_filename = f"{ticket_id}_{file.filename}"
    pdf_path = DATA_RAW_DIR / safe_filename
    pdf_path.write_bytes(content)
    logger.info("PDF saved: %s (%d bytes)", pdf_path, len(content))

    # Create ticket in DB
    ticket = RFPTicket(
        ticket_id=ticket_id,
        status=TICKET_STATUS_ANALIZANDO,
        raw_pdf_path=str(pdf_path),
    )
    db.add(ticket)
    # Flush so ticket_id exists for the foreign key in rfp_event_log below
    db.flush()

    # Log event
    event = RFPEventLog(
        ticket_id=ticket_id,
        event="pdf_received",
        detail=f"Archivo: {file.filename} ({len(content)} bytes)",
    )
    db.add(event)
    db.commit()

    # Trigger background pipeline via Celery
    task_id = _trigger_pipeline(ticket_id, str(pdf_path))

    return {
        "ticket_id": ticket_id,
        "status": TICKET_STATUS_ANALIZANDO,
        "filename": file.filename,
        "task_id": task_id,
        "message": "RFP recibida. El análisis está en progreso.",
    }


def _trigger_pipeline(ticket_id: str, pdf_path: str) -> Optional[str]:
    """Trigger the RFP pipeline via Celery.

    Falls back to a synchronous inline execution if Celery is unavailable
    (development mode).
    """
    try:
        from celery_app import celery_app
        from rfp_tasks import run_rfp_pipeline

        task = run_rfp_pipeline.delay(ticket_id=ticket_id, pdf_path=pdf_path)
        logger.info("Pipeline dispatched via Celery: ticket=%s task=%s", ticket_id, task.id)
        return task.id
    except Exception as exc:
        logger.warning(
            "Celery not available, running pipeline inline: %s", exc
        )
        _run_pipeline_inline(ticket_id, pdf_path)
        return None


def _run_pipeline_inline(ticket_id: str, pdf_path: str) -> None:
    """Execute the pipeline synchronously (fallback when no Celery)."""
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from data.pipelines.rfp_intake.graph import run_pipeline

        logger.info("Running pipeline inline for ticket %s", ticket_id)
        run_pipeline(ticket_id=ticket_id, pdf_path=pdf_path)
        logger.info("Inline pipeline completed for ticket %s", ticket_id)
    except Exception as exc:
        logger.error("Inline pipeline failed for ticket %s: %s", ticket_id, exc)
        # Mark as descartado
        try:
            from sqlmodel import Session
            from database import _get_engine

            engine = _get_engine()
            with Session(engine) as session:
                ticket = session.get(RFPTicket, ticket_id)
                if ticket:
                    ticket.status = TICKET_STATUS_DESCARTADO
                    ticket.updated_at = datetime.now(timezone.utc)
                    session.add(ticket)
                    event = RFPEventLog(
                        ticket_id=ticket_id,
                        event="pipeline_error",
                        detail=f"Inline pipeline failed: {exc}",
                    )
                    session.add(event)
                    session.commit()
        except Exception:
            logger.exception("Failed to mark ticket as descartado")


# ---------------------------------------------------------------------------
# GET /api/rfp/tickets — List all tickets
# ---------------------------------------------------------------------------


@router.get("/tickets")
def list_tickets(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    """List all RFP tickets, optionally filtered by status."""
    query = select(RFPTicket).order_by(RFPTicket.created_at.desc())

    if status_filter:
        query = query.where(RFPTicket.status == status_filter)

    tickets = db.exec(query).all()

    results = []
    for ticket in tickets:
        # Fetch metadata summary
        meta = db.exec(
            select(RFPMetadata).where(RFPMetadata.ticket_id == ticket.ticket_id)
        ).first()

        # Count departments
        dept_count = len(db.exec(
            select(DepartmentSection).where(
                DepartmentSection.ticket_id == ticket.ticket_id
            )
        ).all())

        results.append({
            "ticket_id": ticket.ticket_id,
            "status": ticket.status,
            "client_name": meta.client_name if meta else None,
            "service_type": meta.service_type if meta else None,
            "departments_count": dept_count,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        })

    return results


# ---------------------------------------------------------------------------
# GET /api/rfp/tickets/{ticket_id} — Full ticket detail
# ---------------------------------------------------------------------------


@router.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get full detail for a specific RFP ticket."""
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    # Metadata
    meta = db.exec(
        select(RFPMetadata).where(RFPMetadata.ticket_id == ticket_id)
    ).first()

    # Department sections
    sections = db.exec(
        select(DepartmentSection).where(DepartmentSection.ticket_id == ticket_id)
    ).all()

    # Events
    events = db.exec(
        select(RFPEventLog).where(RFPEventLog.ticket_id == ticket_id)
        .order_by(RFPEventLog.created_at.asc())
    ).all()

    # Parse departments_needed from metadata
    departments_needed = []
    if meta and meta.departments_needed:
        try:
            departments_needed = json.loads(meta.departments_needed)
        except (json.JSONDecodeError, TypeError):
            departments_needed = []

    section_list = []
    for s in sections:
        section_list.append({
            "id": s.id,
            "department_id": s.department_id,
            "key_aspects": s.key_aspects,
            "approval_status": s.approval_status,
        })

    return {
        "ticket_id": ticket.ticket_id,
        "status": ticket.status,
        "raw_pdf_path": ticket.raw_pdf_path,
        "handoff_payload": ticket.handoff_payload,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "metadata": {
            "client_name": meta.client_name,
            "location": meta.location,
            "service_type": meta.service_type,
            "scope": meta.scope,
            "deadline": meta.deadline,
            "budget_range": meta.budget_range,
            "annual_estimated_usd": meta.annual_estimated_usd,
            "departments_needed": departments_needed,
            "flesch_reading_ease": meta.flesch_reading_ease,
            "flesch_kincaid_grade": meta.flesch_kincaid_grade,
            "gunning_fog": meta.gunning_fog,
            "word_count": meta.word_count,
            "classifier_confidence": meta.classifier_confidence,
            "classification_reason": meta.classification_reason,
        } if meta else None,
        "department_sections": section_list,
        "events": [
            {
                "event": e.event,
                "detail": e.detail,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/rfp/tickets/{ticket_id}/synthesis — Synthesis summary
# ---------------------------------------------------------------------------


@router.get("/tickets/{ticket_id}/synthesis")
def get_ticket_synthesis(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get the synthesis (handoff payload) for a completed ticket."""
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    if ticket.status not in (TICKET_STATUS_ANALISIS_COMPLETO,):
        raise HTTPException(
            status_code=400,
            detail=f"Ticket en estado '{ticket.status}'. El análisis debe estar completo.",
        )

    payload = None
    if ticket.handoff_payload:
        try:
            payload = json.loads(ticket.handoff_payload)
        except json.JSONDecodeError:
            payload = {"raw": ticket.handoff_payload}

    return {
        "ticket_id": ticket_id,
        "status": ticket.status,
        "synthesis": payload,
    }


# ---------------------------------------------------------------------------
# POST /api/rfp/tickets/{ticket_id}/generate — Trigger Part 2 pipeline
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_response(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Trigger Part 2 response generation for a completed Part 1 ticket."""
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    if ticket.status != TICKET_STATUS_ANALISIS_COMPLETO:
        raise HTTPException(
            status_code=400,
            detail=f"Ticket en estado '{ticket.status}'. Se requiere 'analisis_completo'.",
        )

    if not ticket.handoff_payload:
        raise HTTPException(
            status_code=400,
            detail="Ticket no tiene payload de handoff (Parte 1 incompleta).",
        )

    # Dispatch via Celery or run inline
    task_id = _trigger_part2(ticket_id)

    return {
        "ticket_id": ticket_id,
        "status": "generando_borrador",
        "task_id": task_id,
        "message": "Generación de borradores iniciada.",
    }


def _trigger_part2(ticket_id: str) -> Optional[str]:
    """Trigger Part 2 pipeline via Celery, or run inline."""
    try:
        from celery_app import celery_app
        from rfp_tasks import run_rfp_response_generation

        task = run_rfp_response_generation.delay(ticket_id=ticket_id)
        logger.info("Part 2 dispatched via Celery: ticket=%s task=%s", ticket_id, task.id)
        return task.id
    except Exception as exc:
        logger.warning("Celery not available, running Part 2 inline: %s", exc)
        _run_part2_inline(ticket_id)
        return None


def _run_part2_inline(ticket_id: str) -> None:
    """Run Part 2 pipeline synchronously (fallback when no Celery)."""
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from data.pipelines.rfp_intake.graph_part2 import trigger_part2

        logger.info("Running Part 2 inline for ticket %s", ticket_id)
        result = trigger_part2(ticket_id)
        logger.info("Inline Part 2 completed for ticket %s: status=%s", ticket_id, result.get("status"))
    except Exception as exc:
        logger.error("Inline Part 2 failed for ticket %s: %s", ticket_id, exc)
        try:
            from sqlmodel import Session
            from database import _get_engine
            from rfp_models import RFPEventLog, RFPTicket

            engine = _get_engine()
            with Session(engine) as session:
                ticket = session.get(RFPTicket, ticket_id)
                if ticket:
                    ticket.status = TICKET_STATUS_NEEDS_HUMAN_REVIEW
                    ticket.updated_at = datetime.now(timezone.utc)
                    session.add(ticket)
                    event = RFPEventLog(
                        ticket_id=ticket_id,
                        event="part2_error",
                        detail=f"Part 2 failed: {exc}",
                    )
                    session.add(event)
                    session.commit()
        except Exception:
            logger.exception("Failed to mark ticket error")


# ---------------------------------------------------------------------------
# GET /api/rfp/tickets/{ticket_id}/part2 — Get Part 2 results
# ---------------------------------------------------------------------------


@router.get("/tickets/{ticket_id}/part2")
def get_part2_results(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get Part 2 results (drafts + evaluations) for a ticket."""
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    p2_statuses = {
        TICKET_STATUS_GENERANDO_BORRADOR,
        TICKET_STATUS_EN_EVALUACION,
        TICKET_STATUS_NEEDS_HUMAN_REVIEW,
    }

    # Also show if the handoff payload contains Part 2 results
    is_part2 = ticket.status in p2_statuses
    has_part2_payload = False
    part2_payload = None
    if ticket.handoff_payload and ticket.status != TICKET_STATUS_ANALISIS_COMPLETO:
        try:
            payload = json.loads(ticket.handoff_payload)
            if payload.get("sections"):
                has_part2_payload = True
                part2_payload = payload
        except (json.JSONDecodeError, TypeError):
            pass

    if not is_part2 and not has_part2_payload:
        raise HTTPException(
            status_code=400,
            detail=f"Parte 2 no iniciada para ticket '{ticket.status}'. "
                   f"Use POST /api/rfp/tickets/{ticket_id}/generate para comenzar.",
        )

    # Get department sections with Part 2 data
    sections = db.exec(
        select(DepartmentSection).where(DepartmentSection.ticket_id == ticket_id)
    ).all()

    section_list = []
    for s in sections:
        eval_results = None
        if s.evaluation_results:
            try:
                eval_results = json.loads(s.evaluation_results)
            except json.JSONDecodeError:
                eval_results = {"raw": s.evaluation_results}

        section_list.append({
            "id": s.id,
            "department_id": s.department_id,
            "draft_content": s.draft_content,
            "evaluation_results": eval_results,
            "approval_status": s.approval_status,
            "key_aspects": s.key_aspects,
        })

    return {
        "ticket_id": ticket_id,
        "status": ticket.status,
        "part2_payload": part2_payload,
        "department_sections": section_list,
    }