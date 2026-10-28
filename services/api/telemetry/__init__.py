"""Paquete de telemetría para el sistema de monitorización de eventos.

Proporciona:
- ``TelemetryEvent`` — modelo Pydantic del envelope de eventos.
- ``TelemetryEventRecord`` — modelo SQLModel para persistencia.
- ``router`` (events) — ``POST /telemetry/events`` para recepción y persistencia.
- ``report_router`` — ``GET /telemetry/report`` con métricas técnicas cacheadas.
- ``analysis`` — pipeline de análisis con Pandas (events_per_day,
  error_rate_by_type, auth_failure_rate).
"""

from telemetry.models import TelemetryEvent, TelemetryEventRecord
from telemetry.router import router
from telemetry.report import router as report_router

__all__ = [
    "TelemetryEvent",
    "TelemetryEventRecord",
    "router",
    "report_router",
]