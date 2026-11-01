"""HTTP routes for RFP intake (Parte 1 + Part 2 + Part 3).

POST   /api/rfp/upload                           — Upload PDF, create ticket, trigger background pipeline
GET    /api/rfp/tickets                          — List all tickets
GET    /api/rfp/tickets/{ticket_id}              — Get ticket detail + metadata + department sections
POST   /api/rfp/tickets/{ticket_id}/generate     — Trigger Part 2 (generation + evaluation) from Part 1 handoff
GET    /api/rfp/tickets/{ticket_id}/part2        — Get Part 2 results (drafts + evaluations)
POST   /api/rfp/tickets/{ticket_id}/approve      — Trigger Part 3 (approval pipeline) from Part 2 handoff
POST   /api/rfp/tickets/{ticket_id}/approve/{department} — Human approves/rejects/requests changes per department
POST   /api/rfp/tickets/{ticket_id}/ceo-approve  — CEO (Mariana Restrepo) approves or rejects
GET    /api/rfp/tickets/{ticket_id}/trace        — Get full execution trace for the ticket
GET    /api/rfp/tickets/{ticket_id}/final-document — Get the generated final document

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
    RFPNodeExecution,
    RFPCheckpoint,
    RFPFinalDocument,
    RFPArbitrationRecord,
    TICKET_STATUS_ANALISIS_COMPLETO,
    TICKET_STATUS_ANALIZANDO,
    TICKET_STATUS_GENERANDO_BORRADOR,
    TICKET_STATUS_EN_EVALUACION,
    TICKET_STATUS_NEEDS_HUMAN_REVIEW,
    TICKET_STATUS_DESCARTADO,
    APPROVAL_STATUS_PENDIENTE,
    APPROVAL_STATUS_APROBADO,
    APPROVAL_STATUS_RECHAZADO,
    APPROVAL_STATUS_REQUEST_CHANGES,
    DEPARTMENT_APPROVERS,
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


# ---------------------------------------------------------------------------
# PARTE 3 — Human approval, arbitration & final document
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/approve", status_code=status.HTTP_202_ACCEPTED)
def trigger_part3(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Trigger the Part 3 approval pipeline.

    Must be called after Part 2 has finished (status = needs_human_review
    or generando_borrador or en_evaluacion).
    """
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    # Allow Part 3 from any post-Part-2 state
    allowed_statuses = {
        TICKET_STATUS_NEEDS_HUMAN_REVIEW,
        TICKET_STATUS_GENERANDO_BORRADOR,
        TICKET_STATUS_EN_EVALUACION,
        "analisis_completo",
    }
    if ticket.status == TICKET_STATUS_ANALISIS_COMPLETO and ticket.handoff_payload:
        pass  # Allow this too — Part 2 may not have run yet but we still accept
    elif ticket.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ticket en estado '{ticket.status}'. Se requiere un estado posterior "
                f"a la Parte 1 (analisis_completo, generando_borrador, en_evaluacion, "
                f"needs_human_review)."
            ),
        )

    if not ticket.handoff_payload:
        raise HTTPException(
            status_code=400,
            detail="Ticket no tiene payload de handoff. Parte 1 no completada.",
        )

    # Dispatch Part 3
    task_id = _trigger_part3(ticket_id)

    return {
        "ticket_id": ticket_id,
        "status": "esperando_aprobacion",
        "task_id": task_id,
        "message": "Parte 3 iniciada. Se han creado puntos de control para aprobación departamental.",
    }


def _trigger_part3(ticket_id: str) -> Optional[str]:
    """Trigger Part 3 pipeline via Celery, or run inline."""
    try:
        from celery_app import celery_app
        from rfp_tasks import run_rfp_approval_pipeline

        task = run_rfp_approval_pipeline.delay(ticket_id=ticket_id)
        logger.info("Part 3 dispatched via Celery: ticket=%s task=%s", ticket_id, task.id)
        return task.id
    except Exception as exc:
        logger.warning("Celery not available, running Part 3 inline: %s", exc)
        _run_part3_inline(ticket_id)
        return None


def _run_part3_inline(ticket_id: str) -> None:
    """Run Part 3 pipeline synchronously (fallback when no Celery)."""
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from data.pipelines.rfp_intake.graph_part3 import trigger_part3

        logger.info("Running Part 3 inline for ticket %s", ticket_id)
        result = trigger_part3(ticket_id)
        logger.info("Inline Part 3 completed for ticket %s: status=%s", ticket_id, result.get("status"))
    except Exception as exc:
        logger.error("Inline Part 3 failed for ticket %s: %s", ticket_id, exc)
        try:
            from sqlmodel import Session
            from database import _get_engine
            from rfp_models import RFPEventLog, RFPTicket

            engine = _get_engine()
            with Session(engine) as session:
                ticket = session.get(RFPTicket, ticket_id)
                if ticket:
                    ticket.status = TICKET_STATUS_DESCARTADO
                    ticket.updated_at = datetime.now(timezone.utc)
                    session.add(ticket)
                    event = RFPEventLog(
                        ticket_id=ticket_id,
                        event="part3_error",
                        detail=f"Part 3 failed: {exc}",
                    )
                    session.add(event)
                    session.commit()
        except Exception:
            logger.exception("Failed to mark ticket error after Part 3 failure")


# ---------------------------------------------------------------------------
# POST /api/rfp/tickets/{ticket_id}/approve/{department}
#   Human approval action per department
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/approve/{department}")
def department_approval(
    ticket_id: str,
    department: str,
    request: Request,
    body: dict,
    db: Session = Depends(get_db),
):
    """Record a human approval decision for a specific department.

    The request body must include:
    - action: "approve" | "reject" | "request_changes"

    Optionally:
    - comment: str — reason or feedback

    This resumes the Part 3 pipeline from the department's checkpoint.
    """
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    action = body.get("action")
    if action not in ("approve", "reject", "request_changes"):
        raise HTTPException(
            status_code=400,
            detail="action debe ser 'approve', 'reject' o 'request_changes'.",
        )

    valid_departments = list(DEPARTMENT_APPROVERS.keys())
    if department not in valid_departments:
        raise HTTPException(
            status_code=400,
            detail=f"Departamento inválido. Válidos: {', '.join(valid_departments)}",
        )

    # Verify there is a checkpoint for this department.
    # RFPCheckpoint has no `status` column — an "active" checkpoint is one that
    # has not been resumed yet (is_resumed == False), matching the checkpointer.
    checkpoint = db.exec(
        select(RFPCheckpoint).where(
            RFPCheckpoint.ticket_id == ticket_id,
            RFPCheckpoint.department_id == department,
            RFPCheckpoint.is_resumed == False,
        )
        .order_by(RFPCheckpoint.created_at.desc())
    ).first()

    if not checkpoint:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay checkpoint activo para '{department}'. "
                f"Asegúrese de haber llamado POST /api/rfp/tickets/{ticket_id}/approve "
                f"primero."
            ),
        )

    # Log the human action
    event = RFPEventLog(
        ticket_id=ticket_id,
        event=f"human_approval:{department}",
        detail=json.dumps({
            "action": action,
            "comment": body.get("comment", ""),
            "approver": DEPARTMENT_APPROVERS.get(department, department),
        }),
    )
    db.add(event)
    db.commit()

    # Resume the pipeline with the human decision
    task_id = _trigger_part3_resume(ticket_id, department, action)

    return {
        "ticket_id": ticket_id,
        "department": department,
        "action": action,
        "approver": DEPARTMENT_APPROVERS.get(department, department),
        "task_id": task_id,
        "message": f"Decisión '{action}' registrada para {department}. "
                   f"Pipeline reanudándose.",
    }


def _trigger_part3_resume(ticket_id: str, department: str, action: str) -> Optional[str]:
    """Trigger Part 3 resume via Celery, or run inline."""
    try:
        from celery_app import celery_app
        from rfp_tasks import resume_rfp_approval

        task = resume_rfp_approval.delay(
            ticket_id=ticket_id,
            department_id=department,
            action=action,
        )
        logger.info("Part 3 resume dispatched via Celery: ticket=%s dept=%s task=%s",
                    ticket_id, department, task.id)
        return task.id
    except Exception as exc:
        logger.warning("Celery not available, running Part 3 resume inline: %s", exc)
        _run_part3_resume_inline(ticket_id, department, action)
        return None


def _run_part3_resume_inline(ticket_id: str, department: str, action: str) -> None:
    """Run Part 3 resume synchronously."""
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from data.pipelines.rfp_intake.graph_part3 import resume_ticket

        logger.info("Resuming Part 3 inline for ticket %s dept=%s action=%s",
                    ticket_id, department, action)
        result = resume_ticket(ticket_id, department, action)
        logger.info("Part 3 resume completed for ticket %s: status=%s",
                    ticket_id, result.get("status"))
    except Exception as exc:
        logger.error("Part 3 resume failed for ticket %s: %s", ticket_id, exc)


# ---------------------------------------------------------------------------
# POST /api/rfp/tickets/{ticket_id}/ceo-approve
#   CEO (Mariana Restrepo) approval
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/ceo-approve")
def ceo_approval(
    ticket_id: str,
    request: Request,
    body: dict,
    db: Session = Depends(get_db),
):
    """CEO approves or rejects a proposal that exceeds $50K USD.

    The request body must include:
    - approved: bool

    Optionally:
    - comment: str
    """
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    approved = body.get("approved")
    if approved not in (True, False):
        raise HTTPException(
            status_code=400,
            detail="'approved' debe ser true o false.",
        )

    action = "approved" if approved else "rejected"
    event = RFPEventLog(
        ticket_id=ticket_id,
        event=f"ceo_{action}",
        detail=json.dumps({
            "ceo": "Mariana Restrepo",
            "approved": approved,
            "comment": body.get("comment", ""),
        }),
    )
    db.add(event)

    if approved:
        ticket.status = "terminado"
    else:
        ticket.status = TICKET_STATUS_DESCARTADO

    ticket.updated_at = datetime.now(timezone.utc)
    db.add(ticket)
    db.commit()

    # If approved, we could continue the pipeline inline to generate the final doc
    if approved:
        try:
            import sys
            from pathlib import Path

            repo_root = Path(__file__).resolve().parents[1]
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))

            from data.pipelines.rfp_intake.graph_part3 import ceo_approve_ticket

            result = ceo_approve_ticket(ticket_id, approved=True)
            logger.info("CEO approval pipeline continued for ticket %s", ticket_id)
            return {
                "ticket_id": ticket_id,
                "status": result.get("status", "terminado"),
                "ceo": "Mariana Restrepo",
                "approved": True,
                "message": "CEO aprobó la propuesta. Documento final generado.",
            }
        except Exception as exc:
            logger.error("CEO approval continuation failed: %s", exc)
            return {
                "ticket_id": ticket_id,
                "status": "terminado",
                "ceo": "Mariana Restrepo",
                "approved": True,
                "message": "CEO aprobó. Continuación automática falló, documento pendiente.",
            }
    else:
        return {
            "ticket_id": ticket_id,
            "status": TICKET_STATUS_DESCARTADO,
            "ceo": "Mariana Restrepo",
            "approved": False,
            "message": "CEO rechazó la propuesta.",
        }


# ---------------------------------------------------------------------------
# GET /api/rfp/tickets/{ticket_id}/trace — Full execution trace
# ---------------------------------------------------------------------------


@router.get("/tickets/{ticket_id}/trace")
def get_trace(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get the full execution trace for a ticket (all pipeline steps)."""
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    nodes = db.exec(
        select(RFPNodeExecution)
        .where(RFPNodeExecution.ticket_id == ticket_id)
        .order_by(RFPNodeExecution.created_at.asc())
    ).all()

    return {
        "ticket_id": ticket_id,
        "trace": [
            {
                "node_name": n.node_name,
                "agent": n.agent,
                "department_id": n.department_id,
                "input_data": n.input_data,
                "output_data": n.output_data,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in nodes
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/rfp/tickets/{ticket_id}/final-document
# ---------------------------------------------------------------------------


@router.get("/tickets/{ticket_id}/final-document")
def get_final_document(
    ticket_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get the generated final document for a completed ticket."""
    ticket = db.get(RFPTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    doc = db.exec(
        select(RFPFinalDocument)
        .where(RFPFinalDocument.ticket_id == ticket_id)
        .order_by(RFPFinalDocument.created_at.desc())
    ).first()

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="No hay documento final. El pipeline de aprobación no ha terminado.",
        )

    return {
        "ticket_id": ticket_id,
        "document_id": doc.id,
        "content": doc.content,
        "total_estimated_value_cop": doc.total_estimated_value_cop,
        "total_estimated_value_usd": doc.total_estimated_value_usd,
        "ceo_approval_required": doc.ceo_approval_required,
        "ceo_approved": doc.ceo_approved,
        "ceo_approved_at": doc.ceo_approved_at.isoformat() if doc.ceo_approved_at else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }