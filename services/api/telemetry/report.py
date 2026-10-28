"""Endpoint de reporte técnico de telemetría con cache en memoria.

Resuelve el período una sola vez, delega el cálculo al pipeline de análisis
(``analysis.py``) y cachea el resultado 60 segundos con TTL.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from database import _get_engine
from telemetry.analysis import auth_failure_rate, error_rate_by_type, events_per_day

logger = logging.getLogger("telemetry.report")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# ---------------------------------------------------------------------------
# Cache en memoria con TTL
# ---------------------------------------------------------------------------


class _MetricCache:
    """Cache simple en memoria con expiración por TTL.

    Almacena el resultado del reporte indexado por clave de caché
    (combinación de ``start_date`` / ``end_date``).  Si el tiempo
    transcurrido desde la última inserción supera ``ttl_seconds``,
    el resultado se considera expirado y toca recalcular.
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, Any] = {}
        self._timestamp: float = 0.0
        self._key: str = ""

    def _make_key(self, start_date: date, end_date: date) -> str:
        return f"{start_date.isoformat()}/{end_date.isoformat()}"

    def get(self, start_date: date, end_date: date) -> dict[str, Any] | None:
        """Retorna el resultado cacheado si la clave coincide y no expiró."""
        key = self._make_key(start_date, end_date)
        if key == self._key and (time.monotonic() - self._timestamp) < self._ttl:
            logger.debug("Cache HIT  key=%s", key)
            return self._data
        logger.debug("Cache MISS key=%s", key)
        return None

    def set(self, start_date: date, end_date: date, data: dict[str, Any]) -> None:
        """Almacena el resultado con la clave actual."""
        self._key = self._make_key(start_date, end_date)
        self._data = data
        self._timestamp = time.monotonic()
        logger.info("Cache SET  key=%s  TTL=%ds", self._key, self._ttl)


_cache = _MetricCache()


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------


def _parse_date_param(value: str | None, default: date) -> date:
    """Convierte un string ISO 8601 opcional a ``date``.

    Args:
        value: String en formato ISO 8601 o ``None``.
        default: Valor por defecto si ``value`` es ``None``.

    Returns:
        Objeto ``date``.
    """
    if value is None:
        return default
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return default


def _now_utc() -> datetime:
    """Retorna la fecha-hora actual en UTC."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------


@router.get("/report")
def get_telemetry_report(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Reporte técnico de telemetría con métricas operacionales.

    Calcula y cachea (TTL 60 s) las siguientes métricas:

    - ``events_per_day``:  conteo diario de eventos por tipo.
    - ``error_rate_by_type``:  distribución de errores de API.
    - ``auth_failure_rate``:  tasa diaria de fallo de login.

    Parámetros query (opcionales):

    - ``start_date``:  inicio del período (ISO 8601).  Por defecto: ahora − 7 días.
    - ``end_date``:  fin del período (ISO 8601).  Por defecto: ahora (UTC).

    Respuesta::

        {
          "period": {"from": "2026-08-25", "to": "2026-09-01"},
          "metrics": {
            "events_per_day": [...],
            "error_rate_by_type": [...],
            "auth_failure_rate": [...]
          }
        }
    """
    now = _now_utc()

    # Resolver el período una sola vez
    p_start = _parse_date_param(start_date, (now - timedelta(days=7)).date())
    p_end = _parse_date_param(end_date, now.date())

    logger.info("Report requested  period=[%s, %s)", p_start, p_end)

    # Intentar cache
    cached = _cache.get(p_start, p_end)
    if cached is not None:
        return cached

    # Obtener engine
    engine = _get_engine()

    # Delegar al pipeline — las funciones son puras
    result: dict[str, Any] = {
        "period": {
            "from": p_start.isoformat(),
            "to": p_end.isoformat(),
        },
        "metrics": {
            "events_per_day": events_per_day(engine, p_start, p_end),
            "error_rate_by_type": error_rate_by_type(engine, p_start, p_end),
            "auth_failure_rate": auth_failure_rate(engine, p_start, p_end),
        },
    }

    # Almacenar en cache
    _cache.set(p_start, p_end, result)

    return result