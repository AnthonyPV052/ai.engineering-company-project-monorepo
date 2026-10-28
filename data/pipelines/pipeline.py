"""Pipeline de desempeño de negocio — Brasaland.

Implementa el **Reporte Semanal de Costo y Merma por Local** que Mariana (CEO)
y Felipe (Director de Operaciones) abren cada lunes.

Estructura del pipeline (Prefect):
  1. ``extract_events``   — Lee eventos de ``telemetry_events`` filtrados por
     tipo y semana ISO.
  2. ``transform_kpis``   — Agrupa por ``location_id`` y calcula los 5 KPIs
     (costo de compra, costo de merma, ratio de merma, quiebres de stock,
     alertas de precio).
  3. ``load_kpis``        — Escribe los KPIs en ``reporting.weekly_location_performance``
     mediante upsert y registra la corrida en ``reporting.pipeline_runs``.
  4. ``export_snapshot``  — Task no crítica que exporta un snapshot JSON a
     ``data/eval/`` para validación. Su fallo **no detiene** el flujo.

Resiliencia:
  - Tasks externas (DB) llevan ``retries=2`` y ``retry_delay_seconds=30``.
  - ``extract_events`` usa ``cache_key_fn=task_input_hash`` con expiración de
    1 hora para evitar releer datos inmutables en corridas repetidas.
  - ``load_kpis`` maneja fallos parciales mediante upsert idempotente.
  - La task ``export_snapshot`` se invoca con ``return_state=True`` para que
    su fallo no propague la excepción al flujo principal.

Uso (CLI):
  python -m data.pipelines.pipeline --week-start 2026-08-31
  python -m data.pipelines.pipeline  # Semana más reciente con datos
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from prefect import flow, task
from prefect.tasks import task_input_hash
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Permitir importaciones desde data/process/
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from process.transform import OUTPUT_COLUMNS, build_upsert_sql, compute_kpis  # noqa: E402

logger = logging.getLogger("pipeline.business_performance")

# ========================================================================
# Constantes
# ========================================================================

# ── Eventos fuente del pipeline (solo estos 4 tipos alimentan los KPIs) ─
SOURCE_EVENT_TYPES: list[str] = [
    "inbound_order_created",
    "stock_waste_registered",
    "stock_threshold_triggered",
    "ingredient_price_variance_detected",
]

# ── Ruta para snapshots de validación ──────────────────────────────────
EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"

# ========================================================================
# Configuración de conexión (desde variable de entorno, con fallback local)
# ========================================================================


def get_source_engine() -> Engine:
    """Retorna el motor SQLAlchemy para la base de datos de origen (telemetría).

    Se conecta a la misma base de datos que la API de Brasaland, usando
    ``DATABASE_URL``.  Es **solo lectura** — este pipeline nunca escribe
    en tablas de telemetría.
    """
    database_url: str = os.getenv(
        "DATABASE_URL",
        "",  # Sin default — fallará con error claro si no está configurada
    )
    if not database_url:
        # Intentar leer desde services/api/.env
        env_path = (
            Path(__file__).resolve().parent.parent.parent
            / "services"
            / "api"
            / ".env"
        )
        if env_path.exists():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if line.startswith("DATABASE_URL="):
                    database_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL no está configurada. "
            "Defínela como variable de entorno o en services/api/.env"
        )

    return create_engine(database_url, echo=False)


def get_target_engine() -> Engine:
    """Retorna el motor SQLAlchemy para la base de datos destino (reporting).

    Por ahora comparte la misma conexión que la fuente. En el futuro podría
    apuntar a un data warehouse separado.
    """
    return get_source_engine()


# ========================================================================
# Task 1: Extract — Extracción con caché y reintentos
# ========================================================================


@task(
    name="extract_events",
    description=(
        "Extrae eventos de telemetry_events filtrados por event_type y semana. "
        "Usa cache_key_fn=task_input_hash para evitar releer datos inmutables "
        "en corridas repetidas del mismo week_start. "
        "La clave de caché se define a partir del hash de los parámetros de "
        "entrada (week_start), por lo que una misma semana produce la misma "
        "clave. "
        "Cache expiration: 1 hora — asume que los eventos de una semana "
        "cerrada no cambian después de 1 hora."
    ),
    retries=2,
    retry_delay_seconds=30,
    cache_key_fn=task_input_hash,
    cache_expiration=timedelta(hours=1),
)
def extract_events(engine: Engine, week_start: date) -> pd.DataFrame:
    """Task de extracción.

    Query SQL que selecciona solo los ``event_type`` relevantes para los KPIs
    dentro de la semana ISO especificada.

    **Retries:** 2 reintentos con 30s de espera — la base de datos puede estar
    en mantenimiento o experimentar una caída transitoria de red. Dos reintentos
    cubren el percentil 99 de recuperación de PostgreSQL sin alargar la espera
    total más de 60 segundos.

    **Cache:** 1 hora con ``cache_key_fn=task_input_hash``. La clave de caché
    se deriva del hash de los argumentos (``engine`` + ``week_start``). Es
    válida por 1 hora porque los eventos de una semana cerrada son inmutables;
    si se ejecuta el pipeline dos veces para la misma semana dentro de la misma
    hora, la segunda corrida usa los datos cacheados sin golpear la base de
    datos.

    Args:
        engine: Motor SQLAlchemy conectado a Supabase/PostgreSQL.
        week_start: Lunes de la semana ISO a extraer.

    Returns:
        DataFrame con las columnas: ``event_type``, ``timestamp``,
        ``location_id``, ``total_cost``, ``country``.
    """
    week_end = week_start + timedelta(days=7)

    query = text("""
        SELECT
            event_type,
            timestamp,
            tags->>'location_id' AS location_id,
            tags->'properties'->>'total_cost' AS total_cost,
            tags->>'country' AS country
        FROM telemetry_events
        WHERE event_type IN (
            'inbound_order_created',
            'stock_waste_registered',
            'stock_threshold_triggered',
            'ingredient_price_variance_detected'
        )
        AND timestamp >= :week_start
        AND timestamp < :week_end
    """)

    logger.info(
        "Extrayendo eventos desde %s hasta %s",
        week_start.isoformat(),
        week_end.isoformat(),
    )

    df: pd.DataFrame = pd.read_sql(
        query,
        engine,
        params={
            "week_start": week_start,
            "week_end": week_end,
        },
    )

    logger.info("Extraídos %d eventos para la semana %s", len(df), week_start.isoformat())
    return df


# ========================================================================
# Task 2: Transform — Cálculo de KPIs (pura, sin IO)
# ========================================================================


@task(
    name="transform_kpis",
    description=(
        "Agrupa eventos por location_id y calcula los 5 KPIs semanales. "
        "Delega la lógica de agregación a data/process/transform.py para "
        "que sea reutilizable desde otros contextos (endpoints, tests)."
    ),
)
def transform_kpis(events: pd.DataFrame, week_start: date) -> pd.DataFrame:
    """Task de transformación.

    Toma el DataFrame plano de eventos y produce un DataFrame agregado
    con una fila por ``location_id`` + ``week_start`` y los 5 KPIs calculados.

    Es una función **pura** (sin efectos secundarios, sin IO). Esto permite
    cachear su resultado si se invoca varias veces con los mismos datos.

    Args:
        events: DataFrame con eventos crudos de la semana.
        week_start: Lunes de la semana ISO (se incluye como dimensión).

    Returns:
        DataFrame con las columnas definidas en ``OUTPUT_COLUMNS``.
    """
    kpis = compute_kpis(events, week_start)
    logger.info(
        "KPIs calculados para %d locales en semana %s",
        len(kpis),
        week_start.isoformat(),
    )
    return kpis


# ========================================================================
# Task 3: Load — Upsert idempotente + log de corrida
# ========================================================================


@task(
    name="load_kpis",
    description=(
        "Escribe los KPIs en reporting.weekly_location_performance mediante "
        "upsert (ON CONFLICT DO UPDATE). También registra la corrida en "
        "reporting.pipeline_runs."
    ),
    retries=2,
    retry_delay_seconds=30,
)
def load_kpis(engine: Engine, kpis: pd.DataFrame, week_start: date) -> int:
    """Task de carga.

    Toma el DataFrame de KPIs y ejecuta un upsert en
    ``reporting.weekly_location_performance`` con ``ON CONFLICT DO UPDATE``.

    La clave única ``(location_id, week_start)`` garantiza idempotencia:
    ejecutar la misma corrida dos veces para la misma semana produce
    exactamente los mismos valores.

    **Retries:** 2 reintentos con 30s. El upsert es idempotente, por lo que
    si la carga falla a medio escribir (algunas filas persistidas, otras no),
    el reintento simplemente sobrescribe las filas ya escritas sin duplicar
    datos — esto es seguro gracias al constraint ``unique (location_id,
    week_start)``.

    Args:
        engine: Motor SQLAlchemy para la base de datos destino.
        kpis: DataFrame con los KPIs a cargar (una fila por location_id).
        week_start: Semana procesada (para el log).

    Returns:
        Número de filas insertadas/actualizadas.
    """
    upsert_sql = text(build_upsert_sql())
    rows = 0

    # --- Asegurar que la tabla objetivo existe ---
    create_table_sql = text("""
        CREATE TABLE IF NOT EXISTS reporting.weekly_location_performance (
            location_id TEXT NOT NULL,
            country TEXT NOT NULL,
            week_start DATE NOT NULL,
            total_purchase_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_waste_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            waste_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
            stockout_events_count INTEGER NOT NULL DEFAULT 0,
            price_alert_events_count INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'COP',
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (location_id, week_start)
        );
    """)

    with engine.begin() as tx:
        tx.execute(text("CREATE SCHEMA IF NOT EXISTS reporting;"))
        tx.execute(create_table_sql)

        for _, row in kpis.iterrows():
            tx.execute(
                upsert_sql,
                {
                    "location_id": row["location_id"],
                    "country": row["country"],
                    "week_start": week_start,
                    "total_purchase_cost": float(row["total_purchase_cost"]),
                    "total_waste_cost": float(row["total_waste_cost"]),
                    "waste_ratio": float(row["waste_ratio"]),
                    "stockout_events_count": int(row["stockout_events_count"]),
                    "price_alert_events_count": int(row["price_alert_events_count"]),
                    "currency": row["currency"],
                },
            )
            rows += 1

    # ── Registrar corrida en reporting.pipeline_runs ─────────────────
    _log_pipeline_run(engine, week_start, rows, status="completed", error_message=None)

    logger.info("Cargados %d registros en reporting.weekly_location_performance", rows)
    return rows


# ========================================================================
# Función auxiliar: log de ejecución del pipeline
# ========================================================================


def _log_pipeline_run(
    engine: Engine,
    week_start: date,
    rows_upserted: int,
    status: str = "completed",
    error_message: str | None = None,
) -> None:
    """Registra una corrida del pipeline en ``reporting.pipeline_runs``.

    Crea la tabla si no existe (migración automática para entornos locales).
    En producción la tabla debe crearse mediante migración DDL.

    Args:
        engine: Motor SQLAlchemy.
        week_start: Semana procesada.
        rows_upserted: Número de filas escritas/actualizadas.
        status: ``completed``, ``failed`` o ``running``.
        error_message: Mensaje de error si la corrida fallo.
    """
    create_table_sql = text("""
        CREATE TABLE IF NOT EXISTS reporting.pipeline_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pipeline_name TEXT NOT NULL,
            week_start DATE NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            rows_upserted INTEGER DEFAULT 0,
            error_message TEXT
        );
    """)

    insert_sql = text("""
        INSERT INTO reporting.pipeline_runs
            (pipeline_name, week_start, status, started_at, finished_at, rows_upserted, error_message)
        VALUES
            ('business_performance_pipeline', :week_start, :status,
             :started_at, :finished_at, :rows_upserted, :error_message)
    """)

    now_ts = datetime.now(timezone.utc)

    with engine.begin() as tx:
        # Asegurar que el esquema reporting y la tabla existen
        tx.execute(text("CREATE SCHEMA IF NOT EXISTS reporting;"))
        tx.execute(create_table_sql)

        tx.execute(
            insert_sql,
            {
                "week_start": week_start,
                "status": status,
                "started_at": now_ts,
                "finished_at": now_ts if status in ("completed", "failed") else None,
                "rows_upserted": rows_upserted,
                "error_message": error_message,
            },
        )


# ========================================================================
# Task no crítica (opcional): snapshot de validación
# ========================================================================


@task(
    name="export_snapshot",
    description=(
        "Exporta un snapshot JSON de los KPIs calculados a data/eval/ "
        "para validación y depuración. Task no crítica: su fallo no "
        "detiene el flujo principal."
    ),
)
def export_snapshot(kpis: pd.DataFrame, week_start: date) -> Path:
    """Exporta un snapshot de los KPIs a ``data/eval/`` como JSON.

    Esta task es **no crítica**: se invoca con ``return_state=True`` en el
    flow, por lo que si falla (ej. el directorio no es escribible), la
    excepción **no se propaga** y el flujo continúa normal.

    Args:
        kpis: DataFrame con los KPIs calculados.
        week_start: Semana procesada (se usa en el nombre del archivo).

    Returns:
        Ruta absoluta al archivo de snapshot generado.

    Raises:
        OSError: Si no se puede escribir en el directorio de salida (el
                 fallo es capturado por ``return_state=True``).
    """
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    snapshot_path = EVAL_DIR / f"kpis_snapshot_{week_start.isoformat()}.json"

    # Convertir a lista de dicts serializable
    records = kpis.to_dict(orient="records")

    # Convertir tipos no serializables
    for rec in records:
        for key, val in rec.items():
            if isinstance(val, (date,)):
                rec[key] = val.isoformat()

    snapshot = {
        "pipeline": "business_performance_pipeline",
        "week_start": week_start.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "locations_count": len(records),
        "kpis": records,
    }

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)

    logger.info("Snapshot exportado a %s (%d locales)", snapshot_path, len(records))
    return snapshot_path



# ========================================================================
# Subflows (cada uno envuelve una task para permitir composición desde el flow principal)
# ========================================================================


@flow(
    name="extract_events_subflow",
    description="Subflow de extracción: lee eventos de telemetry_events para una semana."
)
def subflow_extract(engine: Engine, week_start: date) -> pd.DataFrame:
    """Subflow de extracción.

    Args:
        engine: Motor SQLAlchemy conectado a Supabase/PostgreSQL.
        week_start: Lunes de la semana ISO a extraer.

    Returns:
        DataFrame con eventos crudos de la semana.
    """
    return extract_events(engine, week_start)


@flow(
    name="transform_kpis_subflow",
    description="Subflow de transformación: calcula los 5 KPIs semanales por local."
)
def subflow_transform(events: pd.DataFrame, week_start: date) -> pd.DataFrame:
    """Subflow de transformación.

    Args:
        events: DataFrame con eventos crudos de la semana.
        week_start: Lunes de la semana ISO procesada.

    Returns:
        DataFrame con una fila por location_id y los 5 KPIs calculados.
    """
    return transform_kpis(events, week_start)


@flow(
    name="load_kpis_subflow",
    description="Subflow de carga: upsert en reporting.weekly_location_performance + snapshot."
)
def subflow_load(engine: Engine, kpis: pd.DataFrame, week_start: date) -> dict[str, Any]:
    """Subflow de carga.

    Ejecuta el upsert y el snapshot de validación. El snapshot es no crítico:
    si falla no propaga la excepción al flow principal.

    Args:
        engine: Motor SQLAlchemy para la base de datos destino.
        kpis: DataFrame con los KPIs a cargar.
        week_start: Semana procesada.

    Returns:
        Dict con ``rows_upserted`` y ``snapshot_path`` (puede ser None).
    """
    rows_upserted = load_kpis(engine, kpis, week_start)

    # ── Snapshot (no crítico — return_state=True) ────────────────────
    snapshot_result = export_snapshot.with_options(  # type: ignore[attr-defined]
        name="export_snapshot_noncritical"
    )(kpis, week_start, return_state=True)

    if snapshot_result.is_completed():
        snapshot_path = snapshot_result.result()
        logger.info("Snapshot completado: %s", snapshot_path)
    else:
        snapshot_path = None
        logger.warning(
            "Snapshot falló (tipo=%s): %s — el pipeline continúa normal",
            snapshot_result.type,
            snapshot_result.message,
        )

    return {
        "rows_upserted": rows_upserted,
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
    }


# ========================================================================
# Flow principal
# ========================================================================


@flow(name="business_performance_pipeline")
def run_business_performance_pipeline(week_start: date | None = None) -> dict[str, Any]:
    """Flow principal del pipeline de desempeño de negocio.

    Calcula los 5 KPIs semanales (costo de compra, costo de merma, ratio de
    merma, quiebres de stock, alertas de precio) y los escribe en
    ``reporting.weekly_location_performance``.

    Etapas:
    1. **Extract** — Lee eventos de ``telemetry_events`` (solo lectura).
    2. **Transform** — Agrupa por ``location_id`` y calcula KPIs.
    3. **Load** — Upsert en ``reporting.weekly_location_performance`` + log.
    4. **Snapshot** (no crítico) — Exporta JSON a ``data/eval/`` para validación.

    Args:
        week_start: Lunes de la semana ISO a procesar. Por defecto, calcula
                    la semana más reciente (lunes anterior a hoy).

    Returns:
        Dict con metadata de la corrida: ``week_start``, ``locations``,
        ``rows_upserted``, ``snapshot_path``.
    """
    # ── Resolver semana por defecto ───────────────────────────────────
    if week_start is None:
        today = date.today()
        # Calcular el lunes más reciente
        days_since_monday = today.weekday()  # 0=lunes, 6=domingo
        week_start = today - timedelta(days=days_since_monday)

    logger.info("Iniciando pipeline para semana %s", week_start.isoformat())

    # ── Conexiones ────────────────────────────────────────────────────
    source_engine = get_source_engine()
    target_engine = get_target_engine()

    # ── Registrar inicio de corrida ────────────────────────────────────
    _log_pipeline_run(target_engine, week_start, rows_upserted=0, status="running", error_message=None)

    try:
        # ── 1. Extract subflow ────────────────────────────────────────
        events = subflow_extract(source_engine, week_start)

        # ── 2. Transform subflow ─────────────────────────────────────
        kpis = subflow_transform(events, week_start)

        # ── 3. Load subflow (incluye load_kpis + snapshot) ───────────
        load_result = subflow_load(target_engine, kpis, week_start)

        result: dict[str, Any] = {
            "status": "completed",
            "week_start": week_start.isoformat(),
            "locations": len(kpis),
            "rows_upserted": load_result["rows_upserted"],
            "snapshot_path": load_result["snapshot_path"],
        }

    except Exception as exc:
        logger.exception("Pipeline falló para semana %s", week_start.isoformat())
        _log_pipeline_run(
            target_engine, week_start, rows_upserted=0, status="failed", error_message=str(exc)
        )
        raise

    return result


# ========================================================================
# CLI entry point
# ========================================================================


def main() -> None:
    """Punto de entrada para ejecución como script CLI.

    Uso:
        python -m data.pipelines.pipeline --week-start 2026-08-31
        python -m data.pipelines.pipeline  # Semana más reciente
    """
    parser = argparse.ArgumentParser(
        description="Pipeline de desempeño de negocio — Brasaland",
    )
    parser.add_argument(
        "--week-start",
        type=str,
        default=None,
        help="Lunes de la semana ISO a procesar (formato YYYY-MM-DD). "
        "Por defecto: la semana más reciente.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Activa logging detallado.",
    )

    args = parser.parse_args()

    # Configurar logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Resolver week_start
    week_start: date | None = None
    if args.week_start:
        week_start = date.fromisoformat(args.week_start)

    # Ejecutar pipeline
    result = run_business_performance_pipeline(week_start=week_start)

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETED")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()