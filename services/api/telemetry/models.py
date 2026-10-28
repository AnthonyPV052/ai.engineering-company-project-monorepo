from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TelemetryEvent(BaseModel):
    """Modelo Pydantic para un evento individual de telemetría.

    Cada evento sigue el envelope estándar definido para el sistema
    de telemetría. Este modelo se reutilizará sin cambios en fases
    posteriores (Fase 3+).
    """

    eventId: str = Field(..., description="Identificador único del evento")
    timestamp: datetime = Field(..., description="Momento en que ocurrió el evento")
    sessionId: str = Field(..., description="Identificador de la sesión de usuario")
    userId: str = Field(..., description="Identificador del usuario")
    eventType: str = Field(..., description="Tipo de evento (ej: inbound_order_created)")
    schemaVersion: str = Field(..., description="Versión del esquema del envelope (ej: 1.0)")
    requestId: str = Field(..., description="Identificador de la petición HTTP original")
    properties: dict = Field(
        default_factory=dict,
        description="Propiedades adicionales del evento (contenido variable)",
    )


# ========================================================================
# Modelo SQLModel — tabla telemetry_events en Supabase / PostgreSQL
# ========================================================================

from sqlalchemy import JSON as SQLJSON  # noqa: E402
from sqlmodel import Field as SQLModelField, SQLModel  # noqa: E402


class TelemetryEventRecord(SQLModel, table=True):
    """Registro persistente de un evento de telemetría en Supabase.

    Mapea la tabla ``telemetry_events`` existente en Supabase (creada en
    la Fase 1). Los nombres de columna usan snake_case según la DDL real.
    """

    __tablename__ = "telemetry_events"

    id: int | None = SQLModelField(default=None, primary_key=True)
    event_type: str = SQLModelField(nullable=False, index=True)
    timestamp: datetime = SQLModelField(nullable=False)
    service: str = SQLModelField(default="", nullable=False)
    tags: dict = SQLModelField(default={}, sa_type=SQLJSON)
    received_at: datetime = SQLModelField(
        default_factory=lambda: datetime.now(),
        nullable=False,
    )
    user_id: str | None = SQLModelField(default=None, index=True)
    session_id: str | None = SQLModelField(default=None, index=True)