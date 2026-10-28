"""Utilidad de telemetría para el backend de Brasaland.

Proporciona funciones para emitir eventos de telemetría desde las rutas
del backend con el mismo envelope estándar que el frontend.

Cada evento se registra en un log estructurado y, si TELEMETRY_ENDPOINT
está configurado, se reenvía asíncronamente al endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("brasaland.telemetry")

# Variable de entorno — mismo patrón que el frontend
_TELEMETRY_ENDPOINT: str | None = os.getenv("TELEMETRY_ENDPOINT")
_TELEMETRY_SOURCE: str = os.getenv("TELEMETRY_SOURCE", "backend")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_uuid() -> str:
    return str(uuid.uuid4())


def emit_telemetry_event(
    event_type: str,
    *,
    user_id: str = "",
    session_id: str = "",
    properties: dict[str, Any] | None = None,
    request_id: str = "",
) -> None:
    """Emite un evento de telemetría desde el backend.

    Construye el envelope estándar y lo registra en log. Si
    ``TELEMETRY_ENDPOINT`` está configurado, también lo reenvía
    (pero no se bloquea si el envío falla).

    Args:
        event_type: Nombre del evento (ej. ``inbound_order_created``).
        user_id:  Identificador del usuario autenticado (vacío si es anónimo).
        session_id: Identificador de sesión (opcional).
        properties: Diccionario con las propiedades específicas del evento.
        request_id: Identificador de correlación (se genera automáticamente si
                    no se provee).
    """
    if properties is None:
        properties = {}

    event: dict[str, Any] = {
        "eventId": _new_uuid(),
        "timestamp": _now_iso(),
        "sessionId": session_id,
        "userId": user_id,
        "eventType": event_type,
        "schemaVersion": "1.0",
        "requestId": request_id or _new_uuid(),
        "properties": properties,
    }

    # Log estructurado
    logger.info(
        "EVENT %s | userId=%s | props=%s",
        event_type,
        user_id or "(anonymous)",
        json.dumps(properties, default=str),
    )

    # Reenvío al endpoint externo (si está configurado)
    if _TELEMETRY_ENDPOINT:
        try:
            import httpx  # type: ignore[import-untyped]

            httpx.post(
                _TELEMETRY_ENDPOINT,
                json={"events": [event]},
                timeout=2.0,
            )
        except Exception:
            logger.debug(
                "No se pudo reenviar evento %s a %s",
                event_type,
                _TELEMETRY_ENDPOINT,
            )


def emit_api_perf_event(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    country: str = "",
) -> None:
    """Emite un evento de latencia de API.

    Se llama desde el middleware de timing para cada petición.
    """
    logger.info(
        "PERF %s %s → %d | %.1fms",
        method,
        path,
        status_code,
        duration_ms,
    )

    if _TELEMETRY_ENDPOINT:
        emit_telemetry_event(
            "api_latency_recorded",
            properties={
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "country": country,
            },
        )


def emit_api_error_event(
    method: str,
    path: str,
    status_code: int,
    error_type: str,
    country: str = "",
) -> None:
    """Emite un evento de error de API."""
    emit_telemetry_event(
        "api_error_occurred",
        properties={
            "method": method,
            "path": path,
            "status_code": status_code,
            "error_type": error_type,
            "country": country,
        },
    )