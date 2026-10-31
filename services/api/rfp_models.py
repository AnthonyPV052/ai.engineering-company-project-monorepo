"""SQLModel definitions for the RFP intake pipeline (Parte 1).

Persisted in PostgreSQL (Supabase) — same stack as inventory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums (strings for portability across SQL/JSON)
# ---------------------------------------------------------------------------

# Ticket lifecycle states (Parte 1 focus)
TICKET_STATUS_ANALIZANDO = "analizando"
TICKET_STATUS_DESCARTADO = "descartado"
TICKET_STATUS_ANALISIS_COMPLETO = "analisis_completo"
TICKET_STATUS_GENERANDO_BORRADOR = "generando_borrador"
TICKET_STATUS_EN_EVALUACION = "en_evaluacion"
TICKET_STATUS_NEEDS_HUMAN_REVIEW = "needs_human_review"
TICKET_STATUS_ESPERANDO_APROBACION = "esperando_aprobacion"
TICKET_STATUS_TERMINADO = "terminado"

VALID_TICKET_STATUSES_P1 = {
    TICKET_STATUS_ANALIZANDO,
    TICKET_STATUS_DESCARTADO,
    TICKET_STATUS_ANALISIS_COMPLETO,
}

DEPARTMENT_IDS = {"marketing", "operaciones", "procurement", "training"}

APPROVAL_STATUS_PENDIENTE = "pendiente"
APPROVAL_STATUS_APROBADO = "aprobado"
APPROVAL_STATUS_RECHAZADO = "rechazado"
APPROVAL_STATUS_REQUEST_CHANGES = "request_changes"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class RFPTicket(SQLModel, table=True):
    """Cabecera del ticket de recepción de RFP."""

    __tablename__ = "rfp_ticket"

    ticket_id: str = Field(default_factory=_new_id, primary_key=True)
    status: str = Field(default=TICKET_STATUS_ANALIZANDO, nullable=False, index=True)
    raw_pdf_path: str = Field(default="", nullable=False)
    created_at: datetime = Field(default_factory=_utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=_utc_now, nullable=False)
    # Handoff payload for Part 2 (JSON string, set when status → analisis_completo)
    handoff_payload: Optional[str] = Field(default=None, nullable=True)


class RFPMetadata(SQLModel, table=True):
    """Metadatos extraídos del documento RFP."""

    __tablename__ = "rfp_metadata"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    # --- Extraídos por el clasificador / extractor ---
    client_name: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)
    service_type: Optional[str] = Field(default=None)
    scope: Optional[str] = Field(default=None)
    deadline: Optional[str] = Field(default=None)
    budget_range: Optional[str] = Field(default=None)
    annual_estimated_usd: Optional[float] = Field(default=None)
    # Departamentos que aplican (JSON list string, e.g. '["marketing","operaciones"]')
    departments_needed: Optional[str] = Field(default=None)
    # --- Métricas de legibilidad (py-readability-metrics) ---
    flesch_reading_ease: Optional[float] = Field(default=None)
    flesch_kincaid_grade: Optional[float] = Field(default=None)
    gunning_fog: Optional[float] = Field(default=None)
    coleman_liau_index: Optional[float] = Field(default=None)
    automated_readability_index: Optional[float] = Field(default=None)
    word_count: Optional[int] = Field(default=None)
    sentence_count: Optional[int] = Field(default=None)
    # --- Enriquecimiento ---
    raw_markdown: Optional[str] = Field(default=None)
    classifier_confidence: Optional[float] = Field(default=None)
    classification_reason: Optional[str] = Field(default=None)


class DepartmentSection(SQLModel, table=True):
    """Análisis por departamento activo para una RFP (Parte 1 → key_aspects)."""

    __tablename__ = "rfp_department_section"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    department_id: str = Field(nullable=False)  # one of DEPARTMENT_IDS
    # Parte 1 — aspectos clave
    key_aspects: Optional[str] = Field(default=None)  # Markdown text
    # Parte 2 — borrador y evaluación
    draft_content: Optional[str] = Field(default=None)
    evaluation_results: Optional[str] = Field(default=None)  # JSON
    # Parte 3 — aprobación
    approval_status: str = Field(default=APPROVAL_STATUS_PENDIENTE)
    approver: Optional[str] = Field(default=None)
    approved_at: Optional[datetime] = Field(default=None)
    # Timestamps
    created_at: datetime = Field(default_factory=_utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=_utc_now, nullable=False)


class RFPEventLog(SQLModel, table=True):
    """Audit log of pipeline events for a ticket."""

    __tablename__ = "rfp_event_log"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    event: str = Field(nullable=False)         # e.g. "pdf_received", "classified", "analysis_complete"
    detail: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_utc_now, nullable=False)