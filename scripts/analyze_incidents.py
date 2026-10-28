#!/usr/bin/env python3
"""Analiza incidencias de postventa desde un CSV local.

Reglas:
- Registro invalido si falta cualquier campo obligatorio.
- Registro invalido si categoria o estado no estan permitidos.
- Registro invalido si fecha_creacion no es YYYY-MM-DD.
- Registro invalido si tiempo_resolucion_horas no es numerico >= 0 (cuando viene informado).

Los registros invalidos se cuentan y se excluyen del analisis principal.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "raw" / "incidencias_postventa_100.csv"
DEFAULT_CONTEXT = ROOT / "data" / "process" / "incidencias_contexto.json"
DEFAULT_EXPECTED = ROOT / "data" / "eval" / "incidencias_expected.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def parse_float(value: str) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number


def is_valid_date(date_text: str) -> bool:
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def analyze_csv(csv_path: Path, context: dict[str, Any]) -> dict[str, Any]:
    required_fields = context["required_fields"]
    allowed_categories = set(context["allowed_categories"])
    allowed_states = set(context["allowed_states"])

    valid_rows: list[dict[str, str]] = []
    invalid_rows: list[dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    for index, row in enumerate(rows, start=2):
        errors: list[str] = []

        for field in required_fields:
            if not (row.get(field) or "").strip():
                errors.append(f"campo_obligatorio_faltante:{field}")

        category = (row.get("categoria") or "").strip()
        state = (row.get("estado") or "").strip()
        creation_date = (row.get("fecha_creacion") or "").strip()
        resolution_raw = (row.get("tiempo_resolucion_horas") or "").strip()

        if category and category not in allowed_categories:
            errors.append("categoria_no_permitida")

        if state and state not in allowed_states:
            errors.append("estado_no_permitido")

        if creation_date and not is_valid_date(creation_date):
            errors.append("fecha_creacion_invalida")

        if resolution_raw:
            resolution_hours = parse_float(resolution_raw)
            if resolution_hours is None:
                errors.append("tiempo_resolucion_no_numerico")
            elif resolution_hours < 0:
                errors.append("tiempo_resolucion_negativo")

        if errors:
            invalid_rows.append(
                {
                    "linea_csv": index,
                    "incidente_id": row.get("incidente_id", ""),
                    "errores": errors,
                }
            )
        else:
            valid_rows.append(row)

    category_counter = Counter((r.get("categoria") or "").strip() for r in valid_rows)
    state_counter = Counter((r.get("estado") or "").strip() for r in valid_rows)

    resolution_values: list[float] = []
    for row in valid_rows:
        state = (row.get("estado") or "").strip()
        if state not in {"resuelto", "cerrado"}:
            continue
        value = parse_float((row.get("tiempo_resolucion_horas") or "").strip())
        if value is not None:
            resolution_values.append(value)

    total_records = len(valid_rows) + len(invalid_rows)
    avg_resolution = (
        round(sum(resolution_values) / len(resolution_values), 2)
        if resolution_values
        else None
    )

    return {
        "contexto": {
            "required_fields": required_fields,
            "allowed_categories": sorted(allowed_categories),
            "allowed_states": sorted(allowed_states),
        },
        "resumen": {
            "total_registros": total_records,
            "registros_validos": len(valid_rows),
            "registros_invalidos": len(invalid_rows),
            "porcentaje_invalidos": round((len(invalid_rows) / total_records) * 100, 2)
            if total_records
            else 0,
            "incidencias_por_categoria": dict(category_counter),
            "incidencias_por_estado": dict(state_counter),
            "tiempo_promedio_resolucion_horas": avg_resolution,
        },
        "invalidos": invalid_rows,
    }


def compare_expected(summary: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key, expected_value in expected.items():
        actual_value = summary.get(key)
        if actual_value != expected_value:
            mismatches.append(
                f"{key}: esperado={expected_value!r} actual={actual_value!r}"
            )
    return mismatches


def summary_to_csv_rows(summary: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    rows.append(("total_registros", str(summary["total_registros"])))
    rows.append(("registros_validos", str(summary["registros_validos"])))
    rows.append(("registros_invalidos", str(summary["registros_invalidos"])))
    rows.append(("porcentaje_invalidos", str(summary["porcentaje_invalidos"])))
    rows.append(
        (
            "tiempo_promedio_resolucion_horas",
            "" if summary["tiempo_promedio_resolucion_horas"] is None else str(summary["tiempo_promedio_resolucion_horas"]),
        )
    )

    for category, value in summary["incidencias_por_categoria"].items():
        rows.append((f"categoria:{category}", str(value)))

    for state, value in summary["incidencias_por_estado"].items():
        rows.append((f"estado:{state}", str(value)))

    return rows


def write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    rows = summary_to_csv_rows(summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["metrica", "valor"])
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analizador de incidencias de postventa")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Ruta del CSV de entrada")
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT, help="Ruta del JSON de contexto")
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED, help="Ruta del JSON con valores esperados")
    parser.add_argument("--output-json", type=Path, default=None, help="Ruta para guardar el resultado JSON")
    parser.add_argument("--output-csv", type=Path, default=ROOT / "data" / "process" / "incidencias_resumen.csv", help="Ruta para exportar resumen CSV")

    args = parser.parse_args()

    context = load_json(args.context)
    result = analyze_csv(args.input, context)

    expected = load_json(args.expected)
    mismatches = compare_expected(result["resumen"], expected)
    result["validacion_esperada"] = {
        "coincide": len(mismatches) == 0,
        "diferencias": mismatches,
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    print(output_json)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(output_json + "\n", encoding="utf-8")

    write_summary_csv(args.output_csv, result["resumen"])

    return 0 if len(mismatches) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
