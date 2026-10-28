"""Módulo de transformación reutilizable para el pipeline de desempeño de negocio.

Contiene la lógica de agregación que transforma eventos crudos de telemetría
en los 5 KPIs semanales por local. Es importable desde:

- ``data/pipelines/pipeline.py`` (flujo Prefect)
- ``services/reporting/router.py`` (endpoints FastAPI)
- Scripts de validación en ``data/eval/``

Nunca modifica la base de datos — es una función pura: mismo input → mismo output.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

# ========================================================================
# Columnas del DataFrame de salida (una fila por location_id + week_start)
# ========================================================================

OUTPUT_COLUMNS: list[str] = [
    "location_id",
    "country",
    "week_start",
    "total_purchase_cost",
    "total_waste_cost",
    "waste_ratio",
    "stockout_events_count",
    "price_alert_events_count",
    "currency",
]

# --------------------------------------------------------------------------
# Mapeo de país → moneda
# --------------------------------------------------------------------------
_COUNTRY_CURRENCY: dict[str, str] = {
    "CO": "COP",
    "US": "USD",
}


def compute_kpis(events: pd.DataFrame, week_start: date) -> pd.DataFrame:
    """Calcula los 5 KPIs semanales a partir de eventos crudos de telemetría.

    El DataFrame de entrada debe tener las columnas:
    ``event_type``, ``location_id``, ``country``, ``total_cost``.

    Args:
        events: Eventos extraídos de ``telemetry_events`` para una semana.
        week_start: Lunes de la semana ISO procesada (se incluye en la salida).

    Returns:
        DataFrame agregado con una fila por ``location_id`` y los 5 KPIs:
        - ``total_purchase_cost``  — suma de costos de ``inbound_order_created``
        - ``total_waste_cost``     — suma de costos de ``stock_waste_registered``
        - ``waste_ratio``          — ``total_waste_cost / total_purchase_cost``
        - ``stockout_events_count`` — conteo de ``stock_threshold_triggered``
        - ``price_alert_events_count`` — conteo de ``ingredient_price_variance_detected``
        - ``currency``             — ``COP`` o ``USD`` según país
    """
    if events.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Asegurar tipos numéricos
    if "total_cost" in events.columns:
        events["total_cost"] = pd.to_numeric(events["total_cost"], errors="coerce").fillna(0)

    # ---- 1. Costo de compra por local ----
    purchases = events[events["event_type"] == "inbound_order_created"]
    purchase_agg = (
        purchases.groupby(["location_id", "country"])["total_cost"]
        .sum()
        .reset_index(name="total_purchase_cost")
        if not purchases.empty
        else pd.DataFrame(columns=["location_id", "country", "total_purchase_cost"])
    )

    # ---- 2. Costo de merma por local ----
    waste = events[events["event_type"] == "stock_waste_registered"]
    waste_agg = (
        waste.groupby(["location_id", "country"])["total_cost"]
        .sum()
        .reset_index(name="total_waste_cost")
        if not waste.empty
        else pd.DataFrame(columns=["location_id", "country", "total_waste_cost"])
    )

    # ---- 3. Frecuencia de quiebre de stock ----
    stockouts = events[events["event_type"] == "stock_threshold_triggered"]
    stockout_agg = (
        stockouts.groupby(["location_id", "country"])
        .size()
        .reset_index(name="stockout_events_count")
        if not stockouts.empty
        else pd.DataFrame(columns=["location_id", "country", "stockout_events_count"])
    )

    # ---- 4. Frecuencia de alertas de precio ----
    price_alerts = events[events["event_type"] == "ingredient_price_variance_detected"]
    price_alert_agg = (
        price_alerts.groupby(["location_id", "country"])
        .size()
        .reset_index(name="price_alert_events_count")
        if not price_alerts.empty
        else pd.DataFrame(columns=["location_id", "country", "price_alert_events_count"])
    )

    # ---- Fusionar todas las agregaciones ----
    # Partimos de purchase_agg como base y hacemos left joins sucesivos
    merged = purchase_agg.copy()

    for agg_df in [waste_agg, stockout_agg, price_alert_agg]:
        if merged.empty and not agg_df.empty:
            merged = agg_df.copy()
        elif not merged.empty and not agg_df.empty:
            merged = merged.merge(
                agg_df,
                on=["location_id", "country"],
                how="outer",
            )

    # Si no hubo ningún evento, devolver DataFrame vacío
    if merged.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Rellenar nulos (locales sin cierto tipo de evento)
    for col in ["total_purchase_cost", "total_waste_cost"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    for col in ["stockout_events_count", "price_alert_events_count"]:
        if col not in merged.columns:
            merged[col] = 0
        else:
            merged[col] = merged[col].fillna(0).astype(int)

    # Asegurar columnas base
    if "total_purchase_cost" not in merged.columns:
        merged["total_purchase_cost"] = 0
    if "total_waste_cost" not in merged.columns:
        merged["total_waste_cost"] = 0

    # ---- 5. Calcular ratio de merma ----
    merged["waste_ratio"] = merged.apply(
        lambda row: (
            round(row["total_waste_cost"] / row["total_purchase_cost"], 4)
            if row["total_purchase_cost"] > 0
            else 0.0
        ),
        axis=1,
    )

    # ---- 6. Asignar moneda según país ----
    merged["currency"] = merged["country"].map(_COUNTRY_CURRENCY).fillna("USD")

    # ---- 7. Agregar week_start ----
    merged["week_start"] = week_start

    # Reordenar columnas según OUTPUT_COLUMNS
    for col in OUTPUT_COLUMNS:
        if col not in merged.columns:
            merged[col] = 0 if col in ("stockout_events_count", "price_alert_events_count") else ""

    return merged[OUTPUT_COLUMNS]


def build_upsert_sql() -> str:
    """Genera la sentencia SQL de upsert para ``reporting.weekly_location_performance``.

    Usa ``ON CONFLICT (location_id, week_start) DO UPDATE`` para garantizar
    idempotencia: ejecutar la misma corrida dos veces produce los mismos valores.
    """
    return """
        INSERT INTO reporting.weekly_location_performance
            (location_id, country, week_start,
             total_purchase_cost, total_waste_cost, waste_ratio,
             stockout_events_count, price_alert_events_count, currency,
             computed_at)
        VALUES
            (:location_id, :country, :week_start,
             :total_purchase_cost, :total_waste_cost, :waste_ratio,
             :stockout_events_count, :price_alert_events_count, :currency,
             now())
        ON CONFLICT (location_id, week_start) DO UPDATE SET
            total_purchase_cost      = EXCLUDED.total_purchase_cost,
            total_waste_cost         = EXCLUDED.total_waste_cost,
            waste_ratio              = EXCLUDED.waste_ratio,
            stockout_events_count    = EXCLUDED.stockout_events_count,
            price_alert_events_count = EXCLUDED.price_alert_events_count,
            currency                 = EXCLUDED.currency,
            computed_at              = now()
    """