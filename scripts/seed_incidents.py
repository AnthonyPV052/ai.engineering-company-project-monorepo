#!/usr/bin/env python3
"""Carga el histórico CSV en el almacén TinyDB del gestor de incidencias."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
DEFAULT_CSV_PATH = ROOT / "incidents-brasaland.csv"
REQUIRED_COLUMNS = ("incident_id", "date", "category", "description", "status")

CATEGORY_MAP = {
    "CUSTOMER_COMPLAINT": "customer_complaint",
    "EQUIPMENT": "equipment_failure",
    "SUPPLY": "supply_issue",
    "FOOD_QUALITY": "customer_complaint",
    "STAFF": "staff_issue",
}
STATUS_MAP = {"OPEN": "open", "CLOSED": "resolved", "DISCARDED": "discarded"}
BRANCH_MAP = {
    "COL-01": "medellin_centro", "COL-02": "medellin_laureles", "COL-03": "medellin_envigado",
    "COL-04": "medellin_bello", "COL-05": "medellin_itagui", "COL-06": "bogota_chapinero",
    "COL-07": "bogota_usaquen", "COL-08": "cali_granada", "COL-09": "barranquilla_norte",
    "COL-10": "central", "FLA-01": "miami_doral", "FLA-02": "miami_hialeah",
    "FLA-03": "miami_kendall", "FLA-04": "orlando_international",
}


@dataclass(frozen=True)
class InvalidRow:
    line_number: int
    incident_id: str
    reasons: tuple[str, ...]


def value(row: dict[str, str | None], field: str) -> str:
    return (row.get(field) or "").strip()


def transform_row(row: dict[str, str | None], line_number: int) -> tuple[dict | None, InvalidRow | None]:
    reasons = [f"campo_obligatorio_faltante:{field}" for field in REQUIRED_COLUMNS if not value(row, field)]
    incident_id = value(row, "incident_id")
    description = value(row, "description")
    category = CATEGORY_MAP.get(value(row, "category").upper())
    status = STATUS_MAP.get(value(row, "status").upper())
    try:
        created_at = datetime.strptime(value(row, "date"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        created_at = None

    if value(row, "category") and category is None:
        reasons.append("categoria_no_permitida")
    if value(row, "status") and status is None:
        reasons.append("estado_no_permitido")
    if value(row, "date") and created_at is None:
        reasons.append("fecha_invalida")
    if reasons:
        return None, InvalidRow(line_number, incident_id, tuple(reasons))

    assert category is not None and status is not None and created_at is not None
    # El identificador del CSV sólo controla duplicados: el id del modelo es estable y no lo expone.
    deduplication_key = incident_id or f"{description}|{created_at.isoformat()}"
    return {
        "id": str(uuid5(NAMESPACE_URL, f"brasaland-incident:{deduplication_key}")),
        "title": description[:120].strip(),
        "description": description,
        "category": category,
        "status": status,
        "origin": "customer",
        "branch": BRANCH_MAP.get(value(row, "location_id").upper(), "central"),
        "created_at": created_at,
        "updated_at": created_at,
    }, None


def read_payloads(csv_path: Path) -> tuple[list[dict], list[InvalidRow]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [field for field in REQUIRED_COLUMNS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"El CSV no contiene las columnas requeridas: {', '.join(missing)}")
        payloads, invalid_rows = [], []
        for line_number, row in enumerate(reader, start=2):
            payload, invalid = transform_row(row, line_number)
            if invalid is not None:
                invalid_rows.append(invalid)
            elif payload is not None:
                payloads.append(payload)
    return payloads, invalid_rows


def seed_incidents(csv_path: Path = DEFAULT_CSV_PATH, *, validate_only: bool = False) -> tuple[int, int, list[InvalidRow]]:
    """Inserta el histórico de manera idempotente y devuelve insertadas, omitidas e inválidas."""
    payloads, invalid_rows = read_payloads(csv_path)
    if validate_only:
        return 0, 0, invalid_rows
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))
    from database import get_incidents_db
    from incident_models import IncidentStored
    from tinydb import Query

    db = get_incidents_db()
    query = Query()
    inserted = skipped = 0
    for payload in payloads:
        if db.contains(query.id == payload["id"]):
            skipped += 1
            continue
        db.insert(IncidentStored(**payload).model_dump(mode="json"))
        inserted += 1
    db.close()
    return inserted, skipped, invalid_rows


def print_report(inserted: int, skipped: int, invalid_rows: list[InvalidRow]) -> None:
    print(f"Incidencias insertadas: {inserted}\nIncidencias existentes (omitidas): {skipped}\nRegistros inválidos: {len(invalid_rows)}")
    for row in invalid_rows:
        print(f"- Línea {row.line_number} [{row.incident_id or '(sin incident_id)'}]: {', '.join(row.reasons)}")
    if invalid_rows:
        totals = Counter(reason for row in invalid_rows for reason in row.reasons)
        print("Totales por motivo: " + ", ".join(f"{reason}={count}" for reason, count in sorted(totals.items())))


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga el histórico CSV en services/api/data/incidents.json.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        print_report(*seed_incidents(args.csv, validate_only=args.validate_only))
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
