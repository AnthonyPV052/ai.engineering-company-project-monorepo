"""Módulo de reporting — Endpoints para el Reporte Semanal de Costo y Merma.

Expone los KPIs calculados por el pipeline de desempeño de negocio a través
de tres endpoints.  Siempre importa lógica desde ``data/pipelines/`` y
``data/process/`` — nunca duplica el código del pipeline.

Endpoints:
  - ``GET  /reporting/weekly-location-performance`` — KPIs semanales por local
  - ``GET  /reporting/pipeline-runs/latest``       — Estado y metadata de la última corrida
  - ``POST /reporting/pipeline-runs``              — Disparar corrida manual del pipeline
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Importar lógica compartida desde data/ — nunca duplicar
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

api_dir = Path(__file__).resolve().parent.parent / "api"
if api_dir.is_dir():
    sys.path.insert(0, str(api_dir))
from security import get_current_user  # noqa: E402

data_dir_candidates = (
    Path(__file__).resolve().parent.parent / "data",  # Docker: /app/data
    Path(__file__).resolve().parents[2] / "data",  # Monorepo checkout
)
data_dir = next((path for path in data_dir_candidates if path.is_dir()), None)
if data_dir is not None:
    sys.path.insert(0, str(data_dir))
from pipelines.pipeline import (  # noqa: E402
    get_source_engine,
    get_target_engine,
)
from tasks import run_pipeline

logger = logging.getLogger("reporting.router")

router = APIRouter(prefix="/reporting", tags=["reporting"])


# ========================================================================
# GET /reporting/kpis
# ========================================================================


@router.get("/weekly-location-performance")
def get_weekly_kpis(
    week_start: str | None = Query(
        default=None,
        description="Lunes de la semana ISO (formato YYYY-MM-DD). "
        "Por defecto: la semana más reciente disponible en la tabla.",
    ),
    location_id: str | None = Query(
        default=None,
        description="Filtro opcional por local (ej. medellin-centro).",
    ),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Consulta los KPIs semanales desde ``reporting.weekly_location_performance``.

    Args:
        week_start: Semana a consultar. Si no se provee, se usa la más reciente.
        location_id: Opcional, filtra por un local específico.

    Returns:
        Dict con ``week_start`` y lista de ``locations`` con los 5 KPIs.
    """
    engine = get_source_engine()
    query = text("""
        SELECT
            location_id,
            country,
            week_start,
            total_purchase_cost,
            total_waste_cost,
            waste_ratio,
            stockout_events_count,
            price_alert_events_count,
            currency
        FROM reporting.weekly_location_performance
        WHERE 1=1
    """)
    params: dict[str, Any] = {}

    if location_id:
        query = text(str(query) + " AND location_id = :location_id")
        params["location_id"] = location_id

    # Resolver semana por defecto (la más reciente)
    week = None
    if week_start:
        week = date.fromisoformat(week_start)
    else:
        # Obtener la semana más reciente de la tabla
        max_week_query = text("""
            SELECT MAX(week_start) FROM reporting.weekly_location_performance
        """)
        with engine.connect() as conn:
            result = conn.execute(max_week_query).scalar()
            if result:
                week = result

        if week is None:
            return {
                "week_start": None,
                "locations": [],
                "message": "No hay datos disponibles en reporting.weekly_location_performance.",
            }

    query = text(str(query) + " AND week_start = :week_start")
    params["week_start"] = week

    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()
        locations: list[dict[str, Any]] = []
        for row in rows:
            locations.append({
                "location_id": row.location_id,
                "country": row.country,
                "total_purchase_cost": float(row.total_purchase_cost),
                "total_waste_cost": float(row.total_waste_cost),
                "waste_ratio": float(row.waste_ratio),
                "stockout_events_count": row.stockout_events_count,
                "price_alert_events_count": row.price_alert_events_count,
                "currency": row.currency,
            })

    return {
        "week_start": week.isoformat(),
        "locations": locations,
    }


# ========================================================================
# GET /reporting/status
# ========================================================================


@router.get("/pipeline-runs/latest")
def get_pipeline_status(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Estado y metadata de la última corrida del pipeline.

    Consulta ``reporting.pipeline_runs`` ordenado por ``started_at`` descendente.

    Returns:
        Dict con los datos de la última corrida o un mensaje si no hay registros.
    """
    engine = get_target_engine()

    query = text("""
        SELECT
            id,
            pipeline_name,
            week_start,
            status,
            started_at,
            finished_at,
            rows_upserted,
            error_message
        FROM reporting.pipeline_runs
        ORDER BY started_at DESC
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query).fetchone()

    if row is None:
        return {
            "status": "no_runs",
            "message": "No se ha ejecutado el pipeline aún.",
        }

    return {
        "id": str(row.id),
        "pipeline_name": row.pipeline_name,
        "week_start": row.week_start.isoformat() if hasattr(row.week_start, "isoformat") else str(row.week_start),
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "rows_upserted": row.rows_upserted,
        "error_message": row.error_message,
    }


# ========================================================================
# POST /reporting/run
# ========================================================================


@router.post("/pipeline-runs", status_code=status.HTTP_202_ACCEPTED)
def trigger_pipeline_run(
    week_start: str | None = Query(
        default=None,
        description="Lunes de la semana ISO a procesar (YYYY-MM-DD). "
        "Por defecto: la semana más reciente con datos.",
    ),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Dispara una corrida manual del pipeline de desempeño de negocio.

    Args:
        week_start: Semana a procesar. Si no se provee, se calcula la más
                    reciente (lunes anterior a hoy).

    Returns:
        Dict con el resultado de la corrida.
    Raises:
        HTTPException 500: Si el pipeline falla.
    """
    task = run_pipeline.delay(week_start)
    return {"task_id": task.id}

