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

# --- Aprobadores por departamento (Parte 3) ---
DEPARTMENT_APPROVERS: dict[str, str] = {
    "marketing": "Camila Ospina",
    "operaciones": "Felipe Guerrero",
    "procurement": "Lucía Fernández",
    "training": "Jake Morrison",
}

CEO_NAME = "Mariana Restrepo"

CEO_THRESHOLD_USD = 50000.0


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


# --- Constantes de arbitraje (Parte 3) ---

CONFLICT_TRIGGER_COST_VS_FEASIBILITY = "cost-vs-feasibility"
CONFLICT_TRIGGER_SETUP_SLA_BREACH = "setup-sla-breach"
CONFLICT_TRIGGER_CEO_THRESHOLD = "ceo-threshold"

ARBITRATION_TRIGGER_IDS = {
    CONFLICT_TRIGGER_COST_VS_FEASIBILITY,
    CONFLICT_TRIGGER_SETUP_SLA_BREACH,
    CONFLICT_TRIGGER_CEO_THRESHOLD,
}

# Árbitros fijos por trigger (no LLM)
ARBITRATION_ARBITERS: dict[str, str] = {
    CONFLICT_TRIGGER_COST_VS_FEASIBILITY: "Camila Ospina",       # Marketing, dueña del ticket
    CONFLICT_TRIGGER_SETUP_SLA_BREACH: "Felipe Guerrero",        # Operaciones rechaza; Camila escala
    CONFLICT_TRIGGER_CEO_THRESHOLD: "Mariana Restrepo",          # CEO
}

# Resoluciones posibles de arbitraje
ARBITRATION_RESOLUTION_APPROVE = "approve"
ARBITRATION_RESOLUTION_REJECT = "reject"
ARBITRATION_RESOLUTION_REQUEST_CHANGES = "request_changes"

VALID_ARBITRATION_RESOLUTIONS = {
    ARBITRATION_RESOLUTION_APPROVE,
    ARBITRATION_RESOLUTION_REJECT,
    ARBITRATION_RESOLUTION_REQUEST_CHANGES,
}

# Límite de iteraciones del ciclo generador-evaluador
MAX_GENERATOR_ITERATIONS = 3


class RFPNodeExecution(SQLModel, table=True):
    """Trazabilidad: registro de cada ejecución de un nodo del grafo."""

    __tablename__ = "rfp_node_execution"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    node_name: str = Field(nullable=False)       # e.g. "generate_drafts", "arbitration"
    agent: str = Field(nullable=False)           # e.g. "generator:marketing", "arbiter:cost-vs-feasibility"
    input_snapshot: Optional[str] = Field(default=None)   # JSON — input relevante para ese nodo
    output_snapshot: Optional[str] = Field(default=None)  # JSON — output del nodo
    department_id: Optional[str] = Field(default=None)    # Rama (None si es global)
    created_at: datetime = Field(default_factory=_utc_now, nullable=False)


class RFPCheckpoint(SQLModel, table=True):
    """Checkpoint para reanudar ejecución después de una interrupción.

    Namespaced por thread_id para permitir tickets concurrentes.
    """

    __tablename__ = "rfp_checkpoint"

    id: int | None = Field(default=None, primary_key=True)
    thread_id: str = Field(nullable=False, index=True)  # e.g. "rfp-{ticket_id}" o "rfp-{ticket_id}:{department}"
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    department_id: Optional[str] = Field(default=None)   # None si es global, o el department_id de la rama
    node_name: str = Field(nullable=False)               # Node donde se guardó el checkpoint
    state_snapshot: str = Field(nullable=False)          # JSON — estado completo del grafo en ese punto
    is_resumed: bool = Field(default=False)              # True si ya fue reanudado
    created_at: datetime = Field(default_factory=_utc_now, nullable=False)
    resumed_at: Optional[datetime] = Field(default=None)


class RFPFinalDocument(SQLModel, table=True):
    """Documento final consolidado generado después de todas las aprobaciones."""

    __tablename__ = "rfp_final_document"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    content: str = Field(nullable=False)                 # Markdown del documento final
    total_estimated_value_cop: Optional[float] = Field(default=None)
    total_estimated_value_usd: Optional[float] = Field(default=None)
    ceo_approval_required: bool = Field(default=False)
    ceo_approved: bool = Field(default=False)
    ceo_approved_at: Optional[datetime] = Field(default=None)
    generated_at: datetime = Field(default_factory=_utc_now, nullable=False)


class RFPArbitrationRecord(SQLModel, table=True):
    """Registro de una decisión de arbitraje para un conflicto."""

    __tablename__ = "rfp_arbitration_record"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_ticket.ticket_id", nullable=False, index=True)
    trigger_id: str = Field(nullable=False)              # Uno de CONFLICT_TRIGGER_*
    arbiter: str = Field(nullable=False)                 # Nombre del árbitro fijo
    departments_involved: Optional[str] = Field(default=None)  # JSON list
    description: str = Field(default="")
    resolution: str = Field(nullable=False)              # approve | reject | request_changes
    resolved_by: Optional[str] = Field(default=None)     # Humano que resolvió
    resolved_at: datetime = Field(default_factory=_utc_now, nullable=False)