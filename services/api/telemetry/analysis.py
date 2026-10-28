"""Pipeline de análisis de telemetría con Pandas.

Cada función de métrica sigue el patrón obligatorio del pipeline técnico:

1. **Cargar (SQL)** — filtrar por rango temporal y tipo de evento en la query.
2. **Refinar (Pandas)** — extraer dimensiones desde ``tags``, descartar nulos.
3. **Convertir tipos** — ``timestamp`` → datetime antes de agrupar.
4. **Agrupar** — por la dimensión que responde la pregunta.
5. **Agregar** — ``.count()``, ``.sum()``, ``.mean()`` vectorizados.
6. **Servir** — ``.reset_index().to_dict(orient='records')``.

Todas las métricas son **técnicas** (volumen, errores, latencia), nunca de negocio.
Cada función es **pura**: mismo input → mismo output, sin efectos secundarios.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import text as sa_text
from sqlalchemy.engine import Engine


# ========================================================================
# Utilidad interna — carga SQL con filtros en base de datos
# ========================================================================


def _load_events(
    engine: Engine,
    start_date: date,
    end_date: date,
    event_types: list[str] | None = None,
) -> pd.DataFrame:
    """Carga eventos desde ``telemetry_events`` filtrando en SQL.

    Nunca carga toda la tabla en memoria.  El filtro temporal se aplica
    exclusivamente en la base de datos (``WHERE timestamp >= :start
    AND timestamp < :end``).

    Args:
        engine: Motor SQLAlchemy conectado a Supabase / PostgreSQL.
        start_date: Inicio del rango (inclusivo).
        end_date: Fin del rango (exclusivo).
        event_types: Opcional, solo estos ``event_type``.

    Returns:
        DataFrame con las columnas ``id``, ``event_type``, ``timestamp``,
        ``tags``, ``user_id``, ``session_id``.
    """
    query = """
        SELECT id, event_type, timestamp, tags, user_id, session_id
        FROM telemetry_events
        WHERE timestamp >= :start AND timestamp < :end
    """
    params: dict[str, Any] = {"start": start_date, "end": end_date}

    if event_types:
        placeholders = ", ".join(f":et_{i}" for i in range(len(event_types)))
        query += f" AND event_type IN ({placeholders})"
        for i, et in enumerate(event_types):
            params[f"et_{i}"] = et

    with engine.connect() as conn:
        df = pd.read_sql_query(sa_text(query), conn, params=params)

    return df


# ========================================================================
# Utilidad interna — normalización de la columna tags
# ========================================================================


def _normalize_tags(series: pd.Series) -> pd.Series:
    """Convierte cada elemento de una serie de tags a ``dict``.

    PostgreSQL devuelve ``JSONB`` como ``dict`` nativo con psycopg2,
    pero por seguridad se parsea si aparece como ``str``.
    """

    def _to_dict(val: Any) -> dict[str, Any]:
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            return json.loads(val)
        return {}

    return series.apply(_to_dict)


# ========================================================================
# Métrica 1 — events_per_day
# ========================================================================


def events_per_day(
    engine: Engine,
    start_date: date,
    end_date: date,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Conteo diario de eventos, opcionalmente filtrado por tipo.

    Responde: ¿cuántos eventos de cada tipo se registraron por día?

    Args:
        engine: Motor SQLAlchemy.
        start_date: Inicio del rango (inclusivo).
        end_date: Fin del rango (exclusivo).
        event_type: Opcional, filtra por un tipo específico de evento.

    Returns:
        ``[{"date": "2026-08-01", "event_type": "auth_login_attempted",
            "count": 42}, ...]``
    """
    event_types = [event_type] if event_type else None
    df = _load_events(engine, start_date, end_date, event_types)

    if df.empty:
        return []

    # --- Convertir tipos -------------------------------------------------
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date

    # --- Agrupar y agregar -----------------------------------------------
    result = (
        df.groupby(["date", "event_type"])
        .size()
        .reset_index(name="count")
        .sort_values(["date", "event_type"])
    )

    # --- Servir JSON serializable ----------------------------------------
    result["date"] = result["date"].astype(str)
    return result.to_dict(orient="records")


# ========================================================================
# Métrica 2 — error_rate_by_type
# ========================================================================


def error_rate_by_type(
    engine: Engine,
    start_date: date,
    end_date: date,
    endpoint: str | None = None,
    country: str | None = None,
) -> list[dict[str, Any]]:
    """Distribución de tipos de error entre eventos ``api_error_occurred``.

    Responde: de todos los errores de API registrados, ¿qué proporción
    corresponde a cada tipo (validation_error, not_found, server_error,
    unauthorized)?

    Args:
        engine: Motor SQLAlchemy.
        start_date: Inicio del rango (inclusivo).
        end_date: Fin del rango (exclusivo).
        endpoint: Opcional, filtra por ruta de API (tags["path"]).
        country: Opcional, filtra por país (tags["country"]).

    Returns:
        ``[{"error_type": "validation_error", "count": 10,
            "rate": 0.4545}, ...]``  (ordenado descendente por count)
    """
    df = _load_events(engine, start_date, end_date, ["api_error_occurred"])

    if df.empty:
        return []

    # --- Convertir tipos -------------------------------------------------
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # --- Refinar: extraer dimensiones desde tags -------------------------
    df["tags"] = _normalize_tags(df["tags"])
    df["error_type"] = df["tags"].apply(lambda t: t.get("error_type"))

    # Filtros opcionales sobre tags (después de extraer)
    if endpoint is not None:
        df = df[df["tags"].apply(lambda t: t.get("path") == endpoint)]
    if country is not None:
        df = df[df["tags"].apply(lambda t: t.get("country") == country)]

    # Descartar filas donde error_type sea nulo
    df = df.dropna(subset=["error_type"])

    if df.empty:
        return []

    # --- Agrupar y agregar -----------------------------------------------
    grouped = df.groupby("error_type").size().reset_index(name="count")
    total = grouped["count"].sum()
    grouped["rate"] = (grouped["count"] / total).round(4)

    result = grouped.sort_values("count", ascending=False)

    return result.to_dict(orient="records")


# ========================================================================
# Métrica 3 — auth_failure_rate
# ========================================================================


def auth_failure_rate(
    engine: Engine,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Tasa diaria de fallos de autenticación.

    Fórmula::

        failures_per_day / total_attempts_per_day

    donde ``success=false`` se considera fallo.  Solo contempla eventos
    ``auth_login_attempted``.

    Responde: ¿qué porcentaje de intentos de login están fallando cada día?

    Args:
        engine: Motor SQLAlchemy.
        start_date: Inicio del rango (inclusivo).
        end_date: Fin del rango (exclusivo).

    Returns:
        ``[{"date": "2026-08-01", "attempts": 100, "failures": 3,
            "failure_rate": 0.03}, ...]``
    """
    df = _load_events(engine, start_date, end_date, ["auth_login_attempted"])

    if df.empty:
        return []

    # --- Convertir tipos -------------------------------------------------
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date

    # --- Refinar: extraer success desde tags -----------------------------
    df["tags"] = _normalize_tags(df["tags"])
    df["success"] = df["tags"].apply(lambda t: t.get("success"))

    # Descartar eventos sin campo success
    df = df.dropna(subset=["success"])

    if df.empty:
        return []

    # --- Agrupar y agregar -----------------------------------------------
    grouped = (
        df.groupby("date")
        .agg(
            attempts=("success", "count"),
            # success es booleano; sum(~bool) cuenta los False (fallos)
            failures=("success", lambda s: (~s.astype(bool)).sum()),
        )
        .reset_index()
    )

    grouped["failure_rate"] = (grouped["failures"] / grouped["attempts"]).round(4)

    # --- Servir JSON serializable ----------------------------------------
    grouped["date"] = grouped["date"].astype(str)
    result = grouped.sort_values("date")

    return result.to_dict(orient="records")