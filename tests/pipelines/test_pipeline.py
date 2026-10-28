"""Tests unitarios para el pipeline de desempeño de negocio.

Verifica el comportamiento de las funciones de transformación de forma
**aislada**: sin depender de base de datos ni APIs externas.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Ajustar sys.path para importar desde data/process/
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
sys.path.insert(0, str(DATA_DIR))
from process.transform import OUTPUT_COLUMNS, build_upsert_sql, compute_kpis


# ========================================================================
# Helpers: construir DataFrames de prueba en memoria
# ========================================================================


def _make_event_row(
    event_type: str,
    location_id: str,
    country: str,
    total_cost: float,
) -> dict:
    """Crea una fila de evento de telemetría con la estructura esperada."""
    return {
        "event_type": event_type,
        "location_id": location_id,
        "country": country,
        "total_cost": total_cost,
    }


def _empty_events_df() -> pd.DataFrame:
    """DataFrame vacío con las columnas esperadas por compute_kpis."""
    return pd.DataFrame(columns=["event_type", "location_id", "country", "total_cost"])


# ========================================================================
# Tests para compute_kpis
# ========================================================================


class TestComputeKpis:
    """Tests para la función compute_kpis — el corazón de la transformación."""

    def test_empty_events_returns_empty_dataframe(self):
        """Dado un DataFrame vacío, debe retornar un DataFrame vacío con las
        columnas de salida."""
        events = _empty_events_df()
        result = compute_kpis(events, date(2026, 8, 31))

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        # Debe tener las columnas de salida aunque esté vacío
        for col in OUTPUT_COLUMNS:
            assert col in result.columns, f"Columna '{col}' faltante"

    def test_single_location_all_event_types(self):
        """Verifica que los 5 KPIs se calculan correctamente para un local
        con todos los tipos de evento."""
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "medellin-centro", "CO", 1_000_000),
            _make_event_row("inbound_order_created", "medellin-centro", "CO", 500_000),
            _make_event_row("stock_waste_registered", "medellin-centro", "CO", 30_000),
            _make_event_row("stock_threshold_triggered", "medellin-centro", "CO", 0),
            _make_event_row("stock_threshold_triggered", "medellin-centro", "CO", 0),
            _make_event_row("ingredient_price_variance_detected", "medellin-centro", "CO", 0),
        ])

        result = compute_kpis(events, date(2026, 8, 31))

        assert len(result) == 1
        row = result.iloc[0]

        assert row["location_id"] == "medellin-centro"
        assert row["country"] == "CO"
        assert row["week_start"] == date(2026, 8, 31)
        assert row["total_purchase_cost"] == 1_500_000  # 1M + 500K
        assert row["total_waste_cost"] == 30_000
        assert row["waste_ratio"] == 0.02  # 30_000 / 1_500_000
        assert row["stockout_events_count"] == 2
        assert row["price_alert_events_count"] == 1
        assert row["currency"] == "COP"

    def test_waste_ratio_hand_calculated(self):
        """Test de verificación manual: un KPI calculado a mano debe coincidir
        con el valor producido por compute_kpis.

        Dado:
        - purchase_cost = 2_000_000 (un evento de inbound)
        - waste_cost = 50_000 (un evento de waste)
        - waste_ratio esperado = 50_000 / 2_000_000 = 0.025
        """
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "medellin-poblado", "CO", 2_000_000),
            _make_event_row("stock_waste_registered", "medellin-poblado", "CO", 50_000),
        ])

        result = compute_kpis(events, date(2026, 9, 7))
        row = result.iloc[0]

        expected_ratio = 50_000 / 2_000_000  # 0.025
        assert row["waste_ratio"] == expected_ratio, (
            f"waste_ratio esperado {expected_ratio}, obtenido {row['waste_ratio']}"
        )

    def test_waste_ratio_zero_when_no_purchases(self):
        """Si no hubo compras (total_purchase_cost = 0), waste_ratio debe ser 0
        para evitar división por cero."""
        events = pd.DataFrame([
            _make_event_row("stock_waste_registered", "medellin-envigado", "CO", 10_000),
            _make_event_row("stock_threshold_triggered", "medellin-envigado", "CO", 0),
        ])

        result = compute_kpis(events, date(2026, 8, 31))
        row = result.iloc[0]

        assert row["total_purchase_cost"] == 0
        assert row["waste_ratio"] == 0.0

    def test_multiple_locations(self):
        """Verifica que ubicaciones múltiples producen filas separadas."""
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "bogota-norte", "CO", 800_000),
            _make_event_row("inbound_order_created", "medellin-centro", "CO", 1_200_000),
            _make_event_row("stock_waste_registered", "medellin-centro", "CO", 10_000),
            _make_event_row("stock_threshold_triggered", "bogota-norte", "CO", 0),
            _make_event_row("ingredient_price_variance_detected", "medellin-centro", "CO", 0),
        ])

        result = compute_kpis(events, date(2026, 8, 31))

        assert len(result) == 2  # dos locales distintos

        bogota = result[result["location_id"] == "bogota-norte"].iloc[0]
        assert bogota["total_purchase_cost"] == 800_000
        assert bogota["total_waste_cost"] == 0
        assert bogota["waste_ratio"] == 0.0
        assert bogota["stockout_events_count"] == 1
        assert bogota["price_alert_events_count"] == 0

        medellin = result[result["location_id"] == "medellin-centro"].iloc[0]
        assert medellin["total_purchase_cost"] == 1_200_000
        assert medellin["total_waste_cost"] == 10_000
        # compute_kpis redondea waste_ratio a 4 decimales: 10_000/1_200_000 = 0.008333... → 0.0083
        assert medellin["waste_ratio"] == pytest.approx(0.0083, abs=0.0001)
        assert medellin["price_alert_events_count"] == 1

    def test_usd_currency_for_us_locations(self):
        """Verifica que locales en US usan USD como moneda."""
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "miami-brickell", "US", 5_000),
            _make_event_row("stock_waste_registered", "miami-brickell", "US", 200),
        ])

        result = compute_kpis(events, date(2026, 9, 7))
        row = result.iloc[0]

        assert row["currency"] == "USD"

    def test_cop_currency_for_colombian_locations(self):
        """Verifica que locales en CO usan COP como moneda."""
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "medellin-centro", "CO", 1_000_000),
        ])

        result = compute_kpis(events, date(2026, 8, 31))
        row = result.iloc[0]

        assert row["currency"] == "COP"


# ========================================================================
# Tests de comportamiento defensivo (input inválido / malformado)
# ========================================================================


class TestDefensiveBehavior:
    """Verifica que compute_kpis maneja correctamente entradas inválidas."""

    def test_null_total_cost_does_not_crash(self):
        """Si total_cost es nulo/NaN, no debe lanzar excepción y debe tratarlo
        como 0."""
        events = pd.DataFrame([
            {
                "event_type": "inbound_order_created",
                "location_id": "medellin-centro",
                "country": "CO",
                "total_cost": float("nan"),
            },
            _make_event_row("inbound_order_created", "medellin-centro", "CO", 500_000),
        ])

        # No debe lanzar excepción
        result = compute_kpis(events, date(2026, 8, 31))

        assert len(result) == 1
        row = result.iloc[0]
        # El NaN debe ser coerción a 0, por lo tanto solo suma 500_000
        assert row["total_purchase_cost"] == 500_000

    def test_missing_total_cost_column(self):
        """Si el DataFrame no tiene columna total_cost, debe lanzar KeyError
        porque la columna es requerida para el cálculo. Fallar rápido y claro
        es mejor que propagar un error silencioso."""
        events = pd.DataFrame([
            {"event_type": "inbound_order_created", "location_id": "medellin-centro", "country": "CO"},
        ])

        with pytest.raises(KeyError, match="total_cost"):
            compute_kpis(events, date(2026, 8, 31))

    def test_unknown_event_type_is_ignored(self):
        """Eventos con tipos desconocidos deben ser ignorados silenciosamente."""
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "medellin-centro", "CO", 100_000),
            {"event_type": "unknown_event", "location_id": "medellin-centro", "country": "CO", "total_cost": 99_999},
            _make_event_row("stock_waste_registered", "medellin-centro", "CO", 5_000),
        ])

        result = compute_kpis(events, date(2026, 8, 31))
        row = result.iloc[0]

        # El evento desconocido no debe afectar los KPIs
        assert row["total_purchase_cost"] == 100_000  # no 199_999
        assert row["total_waste_cost"] == 5_000

    def test_string_total_cost_is_coerced(self):
        """Si total_cost viene como string numérico, debe ser convertido."""
        events = pd.DataFrame([
            {
                "event_type": "inbound_order_created",
                "location_id": "medellin-centro",
                "country": "CO",
                "total_cost": "1000000",  # string en vez de número
            },
        ])

        result = compute_kpis(events, date(2026, 8, 31))
        row = result.iloc[0]

        assert row["total_purchase_cost"] == 1_000_000

    def test_non_numeric_string_total_cost_is_zero(self):
        """Si total_cost es un string no numérico, debe ser coercionado a 0."""
        events = pd.DataFrame([
            {
                "event_type": "inbound_order_created",
                "location_id": "medellin-centro",
                "country": "CO",
                "total_cost": "not-a-number",
            },
        ])

        result = compute_kpis(events, date(2026, 8, 31))
        row = result.iloc[0]

        assert row["total_purchase_cost"] == 0

    def test_empty_country_defaults_to_usd(self):
        """Si country está vacío, la moneda por defecto debe ser USD."""
        events = pd.DataFrame([
            _make_event_row("inbound_order_created", "unknown-local", "", 100_000),
        ])

        result = compute_kpis(events, date(2026, 8, 31))
        row = result.iloc[0]

        assert row["currency"] == "USD"


# ========================================================================
# Tests para build_upsert_sql
# ========================================================================


class TestBuildUpsertSql:
    """Verifica que la sentencia SQL generada sea válida y contenga
    los elementos esenciales para un upsert idempotente."""

    def test_returns_non_empty_string(self):
        sql = build_upsert_sql()
        assert isinstance(sql, str)
        assert len(sql) > 0

    def test_contains_upsert_keywords(self):
        sql = build_upsert_sql()
        assert "INSERT INTO reporting.weekly_location_performance" in sql
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    def test_contains_unique_key(self):
        sql = build_upsert_sql()
        assert "location_id" in sql
        assert "week_start" in sql

    def test_contains_all_kpi_columns(self):
        sql = build_upsert_sql()
        kpi_columns = [
            "total_purchase_cost",
            "total_waste_cost",
            "waste_ratio",
            "stockout_events_count",
            "price_alert_events_count",
            "currency",
        ]
        for col in kpi_columns:
            assert col in sql, f"Columna KPI '{col}' faltante en el upsert"