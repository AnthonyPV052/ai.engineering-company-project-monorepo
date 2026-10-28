from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from database import get_db
from telemetry.models import TelemetryEvent, TelemetryEventRecord

logger = logging.getLogger("telemetry.router")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# Leer variable de entorno para establecer el patrón desde el inicio.
# Aún no se usa para redirigir tráfico, pero estará disponible
# cuando se implemente el envío a un endpoint externo en Fase 3.
TELEMETRY_ENDPOINT: str | None = os.getenv("TELEMETRY_ENDPOINT")


class EventsPayload(BaseModel):
    """Payload esperado para el endpoint POST /telemetry/events.

    Se parsea de forma laxa: la lista ``events`` contiene diccionarios
    crudos, no instancias pre-validadas de ``TelemetryEvent``.
    """

    events: list[dict[str, Any]]


@router.post("/events")
def receive_events(
    payload: EventsPayload,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Recibe un lote de eventos de telemetría, valida cada uno
    individualmente y persiste los válidos en ``telemetry_events``.

    - Cada evento crudo se parsea con ``TelemetryEvent.model_validate()``
      dentro de un bloque try/except ``ValidationError``.
    - Los eventos válidos se insertan en una única operación de bulk insert.
    - Los eventos inválidos se rechazan individualmente sin cancelar el lote.

    Responde con ``{"received": N, "stored": M, "rejected": R}`` donde:
    - N  = total de eventos recibidos en el envelope
    - M  = eventos válidos que fueron persistidos
    - R  = eventos rechazados por no cumplir el contrato
    """
    events_data = payload.events
    total = len(events_data)
    logger.info("Eventos recibidos: %d", total)

    valid_records: list[TelemetryEventRecord] = []
    rejected = 0

    for idx, raw in enumerate(events_data):
        try:
            event = TelemetryEvent.model_validate(raw)
            record = TelemetryEventRecord(
                event_type=event.eventType,
                timestamp=event.timestamp,
                user_id=event.userId or None,
                session_id=event.sessionId or None,
                service="backend",
                tags={
                    "eventId": event.eventId,
                    "schemaVersion": event.schemaVersion,
                    "requestId": event.requestId,
                    **event.properties,
                },
            )
            valid_records.append(record)
            logger.info(
                "  [%d/%d] eventId=%s event_type=%s sessionId=%s",
                idx + 1,
                total,
                event.eventId,
                event.eventType,
                event.sessionId,
            )
        except ValidationError as exc:
            rejected += 1
            logger.warning(
                "  [%d/%d] Evento inválido (eventId=%s): %s",
                idx + 1,
                total,
                raw.get("eventId", "?"),
                exc.errors(),
            )

    stored = 0
    if valid_records:
        try:
            db.add_all(valid_records)
            db.commit()
            stored = len(valid_records)
            logger.info("Persistidos %d eventos en telemetry_events", stored)
        except Exception as exc:
            db.rollback()
            logger.error(
                "Error al insertar lote en telemetry_events: %s", exc
            )
            stored = 0

    return {"received": total, "stored": stored, "rejected": rejected}