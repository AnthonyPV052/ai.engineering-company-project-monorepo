"""Script de validación del pipeline de desempeño de negocio.

Genera un snapshot esperado de KPIs para la semana especificada y lo compara
con la salida real del pipeline. Se ejecuta manualmente después de una corrida
del pipeline para verificar que los datos son correctos.

Uso:
    python data/eval/validate_pipeline.py --week-start 2026-08-31

Esto:
    1. Lee los KPIs desde ``reporting.weekly_location_performance``.
    2. Exporta un snapshot de validación a ``data/eval/``.
    3. Compara con un snapshot esperado si existe (``*_expected.json``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Permitir importar desde data/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from process.transform import OUTPUT_COLUMNS, compute_kpis  # noqa: E402

logger = logging.getLogger("eval.validation")

EVAL_DIR = Path(__file__).resolve().parent


def validate_pipeline_output(week_start: date) -> dict[str, Any]:
    """Valida la salida del pipeline generando un snapshot de referencia.

    Lee la tabla ``reporting.weekly_location_performance`` y exporta
    un archivo JSON con los KPIs para comparación manual o automatizada.

    Args:
        week_start: Semana ISO a validar.

    Returns:
        Dict con metadata de la validación.
    """
    from sqlalchemy import create_engine, text

    database_url: str = ""
    import os

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        env_path = (
            Path(__file__).resolve().parent.parent
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
        logger.warning("DATABASE_URL no configurada — validación solo estructural")
        return {
            "status": "skipped",
            "message": "DATABASE_URL no configurada. No se puede conectar a la BD.",
            "week_start": week_start.isoformat(),
        }

    engine = create_engine(database_url, echo=False)

    # Leer KPIs desde la tabla destino
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
        WHERE week_start = :week_start
        ORDER BY location_id
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, {"week_start": week_start}).fetchall()

    if not rows:
        logger.warning("No hay datos para semana %s en la tabla destino", week_start)
        return {
            "status": "empty",
            "week_start": week_start.isoformat(),
            "locations_count": 0,
            "locations": [],
        }

    locations = []
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

    # Exportar snapshot
    snapshot = {
        "pipeline": "business_performance_pipeline",
        "week_start": week_start.isoformat(),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "locations_count": len(locations),
        "locations": locations,
    }

    snapshot_path = EVAL_DIR / f"kpis_snapshot_{week_start.isoformat()}.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)

    logger.info(
        "Snapshot de validación exportado a %s (%d locales)",
        snapshot_path,
        len(locations),
    )

    # Comparar con snapshot esperado si existe
    expected_path = EVAL_DIR / f"kpis_expected_{week_start.isoformat()}.json"
    comparison = None
    if expected_path.exists():
        with open(expected_path, encoding="utf-8") as f:
            expected = json.load(f)

        # Comparar estructura y valores
        expected_locations = {(loc["location_id"], loc["country"]): loc for loc in expected.get("locations", [])}
        actual_locations = {(loc["location_id"], loc["country"]): loc for loc in locations}

        mismatches = []
        for key, actual_loc in actual_locations.items():
            expected_loc = expected_locations.get(key)
            if expected_loc is None:
                mismatches.append(f"Local {key} no esperado")
                continue
            for kpi_key in ["total_purchase_cost", "total_waste_cost", "waste_ratio",
                            "stockout_events_count", "price_alert_events_count"]:
                expected_val = expected_loc.get(kpi_key)
                actual_val = actual_loc.get(kpi_key)
                if expected_val is not None and actual_val is not None:
                    if abs(float(expected_val) - float(actual_val)) > 0.01:
                        mismatches.append(
                            f"Local {key}: {kpi_key} esperado={expected_val} actual={actual_val}"
                        )

        comparison = {
            "expected_locations": len(expected.get("locations", [])),
            "actual_locations": len(locations),
            "match": len(mismatches) == 0,
            "mismatches": mismatches,
        }

        status = "passed" if comparison["match"] else "mismatch"
        logger.info("Validación: %s (%d diferencias)", status, len(mismatches))
    else:
        logger.info(
            "No hay snapshot esperado para %s — se usó %s como referencia",
            week_start,
            snapshot_path,
        )
        comparison = {
            "note": "No hay snapshot esperado para comparación. "
            "Este snapshot servirá como referencia futura.",
        }

    return {
        "status": "completed",
        "week_start": week_start.isoformat(),
        "locations_count": len(locations),
        "snapshot_path": str(snapshot_path),
        "comparison": comparison,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida la salida del pipeline de desempeño de negocio"
    )
    parser.add_argument(
        "--week-start",
        type=str,
        required=True,
        help="Lunes de la semana ISO a validar (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Activa logging detallado",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    week_start = date.fromisoformat(args.week_start)
    result = validate_pipeline_output(week_start)

    print("\n" + "=" * 60)
    print("VALIDACION DEL PIPELINE")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()