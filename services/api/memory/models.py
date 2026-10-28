"""SQLModel + Pydantic schemas for the Agent Memory System.

Define los modelos de datos para:
- agent_memories: hechos episódicos almacenados
- memory_proposals: propuestas pendientes de confirmación
- memory_audit_log: registro auditable de decisiones
- DTOs para comunicación con el agente y API
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SQLField, SQLModel

# ============================================================================
# Enumeraciones
# ============================================================================


class MemoryCategory(str, Enum):
    """Categorías permitidas para memorias de agente.

    Alineadas con el BRIEFING de Brasaland:
    - Correcciones operativas recurrentes por location
    - Contexto de escalaciones resueltas
    - Preferencias de comunicación de gerentes
    """
    HORARIOS = "horarios"
    PROVEEDORES = "proveedores"
    INCIDENTES_CONOCIDOS = "incidentes_conocidos"
    PREFERENCIAS = "preferencias"
    GENERAL = "general"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISCARDED = "discarded"
    EDITED = "edited"


class AuditEventType(str, Enum):
    PROPOSAL_CREATED = "proposal_created"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISCARDED = "discarded"
    EDITED = "edited"
    CONSOLIDATED = "consolidated"
    MEMORY_USED = "memory_used"


# ============================================================================
# Modelos SQL (SQLModel → PostgreSQL)
# ============================================================================


class AgentMemory(SQLModel, table=True):
    """Hecho episódico almacenado por el agente (con aprobación)."""

    __tablename__ = "agent_memories"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    summary: str = SQLField(nullable=False)
    location: str = SQLField(default="", max_length=128)
    category: str = SQLField(default="", max_length=64)
    confidence: float = SQLField(default=1.0)
    approved_by: str = SQLField(default="", max_length=256)
    approved_at: Optional[datetime] = SQLField(default=None)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )
    usage_count: int = SQLField(default=0)
    last_used_at: Optional[datetime] = SQLField(default=None)
    archived: bool = SQLField(default=False)
    archived_at: Optional[datetime] = SQLField(default=None)
    consolidated_version: int = SQLField(default=1)
    parent_memory_id: Optional[UUID] = SQLField(default=None, foreign_key="agent_memories.id")


class MemoryProposal(SQLModel, table=True):
    """Propuesta de memoria pendiente de confirmación del usuario."""

    __tablename__ = "memory_proposals"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    session_id: str = SQLField(nullable=False, max_length=256)
    conversation_id: Optional[UUID] = SQLField(default=None)
    proposed_summary: str = SQLField(nullable=False)
    proposed_location: str = SQLField(default="", max_length=128)
    proposed_category: str = SQLField(default="", max_length=64)
    proposed_confidence: float = SQLField(default=0.8)
    trigger_message: str = SQLField(default="")
    status: str = SQLField(default="pending", max_length=16)
    approved_memory_id: Optional[UUID] = SQLField(default=None, foreign_key="agent_memories.id")
    resolved_by: str = SQLField(default="", max_length=256)
    resolved_at: Optional[datetime] = SQLField(default=None)
    resolution_note: str = SQLField(default="")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = SQLField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )


class MemoryAuditLog(SQLModel, table=True):
    """Registro auditable de todas las decisiones de memoria."""

    __tablename__ = "memory_audit_log"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    proposal_id: Optional[UUID] = SQLField(default=None)
    event_type: str = SQLField(nullable=False, max_length=32)
    description: str = SQLField(default="")
    event_data: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    session_id: str = SQLField(default="", max_length=256)
    actor: str = SQLField(default="system", max_length=256)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# DTOs para comunicación con el agente
# ============================================================================


class MemorySuggestion(BaseModel):
    """Salida estructurada que el agente genera junto a su respuesta.

    El agente produce esto en la MISMA llamada al LLM que su respuesta
    al usuario — no requiere una segunda llamada.
    """
    should_store: bool = Field(
        default=False,
        description="Si hay algo nuevo/corregido que valga la pena recordar"
    )
    summary: str = Field(
        default="",
        description="Texto del hecho a memorizar (ej. 'El proveedor X entrega los martes en Medellín')"
    )
    location: str = Field(
        default="",
        description="Location asociada (vacío si es global)"
    )
    category: str = Field(
        default="",
        pattern=r"^(horarios|proveedores|incidentes_conocidos|preferencias|general)$",
        description="Categoría: horarios, proveedores, incidentes_conocidos, preferencias, general"
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Qué tan seguro está el agente de que esto es correcto"
    )

    reason: str = Field(
        default="",
        description="Por qué esto merece ser recordado (explicación para el usuario)"
    )


class MemoryProposalResponse(BaseModel):
    """DTO para devolver una propuesta al frontend/agente."""
    id: UUID
    summary: str
    location: str
    category: str
    confidence: float
    trigger_message: str
    status: str
    created_at: datetime


class MemorySearchResult(BaseModel):
    """Resultado de una búsqueda de memoria."""
    id: UUID
    summary: str
    location: str
    category: str
    confidence: float
    score: float
    usage_count: int


class IntentionClassification(BaseModel):
    """Clasificación de la intención del usuario ante una propuesta."""
    intention: str = Field(
        pattern=r"^(approved|rejected|edited|topic_change|unrelated)$",
        description="approved | rejected | edited | topic_change | unrelated"
    )
    edited_summary: str = Field(
        default="",
        description="Si intention=edited, el nuevo texto propuesto"
    )
    edited_location: str = Field(
        default="",
        description="Si intention=edited, nueva location (opcional)"
    )
    edited_category: str = Field(
        default="",
        description="Si intention=edited, nueva categoría (opcional)"
    )