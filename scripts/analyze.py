#!/usr/bin/env python3
"""Script principal de analisis de incidencias CSV (Fase 1)."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT = ROOT / "data" / "process" / "incidencias_contexto.json"
DEFAULT_EXPECTED = ROOT / "data" / "eval" / "incidencias_expected.json"

DEFAULT_RULES = {
	"required_fields": ["incidente_id", "cliente_id", "categoria", "estado", "fecha_creacion"],
	"allowed_categories": ["queja", "solicitud", "fallo_operativo"],
	"allowed_states": ["abierto", "en_proceso", "resuelto", "cerrado"],
}

FIELD_ALIASES: dict[str, list[str]] = {
	"incidente_id": ["incidente_id", "incident_id"],
	"cliente_id": ["cliente_id", "customer_id"],
	"categoria": ["categoria", "category"],
	"estado": ["estado", "status"],
	"fecha_creacion": ["fecha_creacion", "date"],
	"tiempo_resolucion_horas": ["tiempo_resolucion_horas", "resolution_time_hours"],
}

CATEGORY_NORMALIZATION: dict[str, str] = {
	"queja": "queja",
	"customer_complaint": "queja",
	"food_quality": "queja",
	"solicitud": "solicitud",
	"request": "solicitud",
	"service_request": "solicitud",
	"fallo_operativo": "fallo_operativo",
	"supply": "fallo_operativo",
	"equipment": "fallo_operativo",
	"staff": "fallo_operativo",
}

STATE_NORMALIZATION: dict[str, str] = {
	"abierto": "abierto",
	"open": "abierto",
	"en_proceso": "en_proceso",
	"in_progress": "en_proceso",
	"resuelto": "resuelto",
	"resolved": "resuelto",
	"cerrado": "cerrado",
	"closed": "cerrado",
	"descartado": "descartado",
	"discarded": "descartado",
}


def load_json_if_exists(path: Path) -> dict[str, Any] | None:
	if not path.exists():
		return None
	with path.open("r", encoding="utf-8") as file:
		return json.load(file)


def parse_float(value: str) -> float | None:
	text = (value or "").strip()
	if not text:
		return None
	try:
		return float(text)
	except ValueError:
		return None


def is_valid_iso_date(value: str) -> bool:
	try:
		datetime.strptime(value, "%Y-%m-%d")
		return True
	except ValueError:
		return False


def get_rules(context_path: Path) -> dict[str, list[str]]:
	context = load_json_if_exists(context_path)
	if not context:
		return DEFAULT_RULES

	return {
		"required_fields": context.get("required_fields", DEFAULT_RULES["required_fields"]),
		"allowed_categories": context.get("allowed_categories", DEFAULT_RULES["allowed_categories"]),
		"allowed_states": context.get("allowed_states", DEFAULT_RULES["allowed_states"]),
	}


def get_satisfaction_field(headers: list[str]) -> str | None:
	candidates = [
		"indice_satisfaccion",
		"satisfaccion",
		"puntuacion_satisfaccion",
		"score_satisfaccion",
		"satisfaction_score",
	]
	lowered = {header.lower(): header for header in headers}
	for candidate in candidates:
		if candidate in lowered:
			return lowered[candidate]
	return None


def resolve_schema(headers: list[str]) -> dict[str, str | None]:
	header_lookup = {header.strip().lower(): header for header in headers}
	resolved: dict[str, str | None] = {}
	for canonical, aliases in FIELD_ALIASES.items():
		resolved[canonical] = None
		for alias in aliases:
			if alias.lower() in header_lookup:
				resolved[canonical] = header_lookup[alias.lower()]
				break
	return resolved


def row_value(row: dict[str, str], resolved_schema: dict[str, str | None], canonical: str) -> str:
	field_name = resolved_schema.get(canonical)
	if field_name is None:
		return ""
	return (row.get(field_name) or "").strip()


def normalize_category(value: str) -> str:
	normalized = value.strip().lower()
	return CATEGORY_NORMALIZATION.get(normalized, normalized)


def normalize_state(value: str) -> str:
	normalized = value.strip().lower()
	return STATE_NORMALIZATION.get(normalized, normalized)


def analyze(csv_path: Path, rules: dict[str, list[str]]) -> dict[str, Any]:
	required_fields = rules["required_fields"]
	allowed_categories = set(rules["allowed_categories"])
	allowed_states = set(rules["allowed_states"])

	with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
		reader = csv.DictReader(file)
		headers = reader.fieldnames or []
		rows = list(reader)

	satisfaction_field = get_satisfaction_field(headers)
	resolved_schema = resolve_schema(headers)
	optional_required_fields: set[str] = set()
	if resolved_schema.get("cliente_id") == "customer_id":
		# En el esquema Brasaland customer_id puede venir vacío por anonimización.
		optional_required_fields.add("cliente_id")

	invalid_rows: list[dict[str, Any]] = []
	valid_rows: list[dict[str, str]] = []
	invalid_reason_counter: Counter[str] = Counter()
	allowed_states = set(allowed_states) | {"descartado"}

	for line_number, row in enumerate(rows, start=2):
		reasons: list[str] = []

		for field in required_fields:
			if field in optional_required_fields:
				continue
			if not row_value(row, resolved_schema, field):
				reasons.append(f"campo_faltante:{field}")

		category = normalize_category(row_value(row, resolved_schema, "categoria"))
		state = normalize_state(row_value(row, resolved_schema, "estado"))
		creation_date = row_value(row, resolved_schema, "fecha_creacion")

		if category and category not in allowed_categories:
			reasons.append("categoria_fuera_de_rango")

		if state and state not in allowed_states:
			reasons.append("estado_fuera_de_rango")

		if creation_date and not is_valid_iso_date(creation_date):
			reasons.append("fecha_creacion_invalida")

		resolution_raw = row_value(row, resolved_schema, "tiempo_resolucion_horas")
		if resolution_raw:
			parsed = parse_float(resolution_raw)
			if parsed is None:
				reasons.append("tiempo_resolucion_no_numerico")
			elif parsed < 0:
				reasons.append("tiempo_resolucion_fuera_de_rango")

		if satisfaction_field is not None:
			satisfaction_raw = (row.get(satisfaction_field) or "").strip()
			if satisfaction_raw:
				score = parse_float(satisfaction_raw)
				if score is None:
					reasons.append("satisfaccion_no_numerica")
				elif score < 0 or score > 10:
					reasons.append("satisfaccion_fuera_de_rango")

		if reasons:
			invalid_rows.append(
				{
					"linea_csv": line_number,
					"incidente_id": row_value(row, resolved_schema, "incidente_id"),
					"motivos": reasons,
				}
			)
			invalid_reason_counter.update(reasons)
		else:
			row["__categoria_normalizada"] = category
			row["__estado_normalizado"] = state
			valid_rows.append(row)

	by_category = Counter((row.get("__categoria_normalizada") or "").strip() for row in valid_rows)
	by_state = Counter((row.get("__estado_normalizado") or "").strip() for row in valid_rows)

	target_states = ["abierto", "cerrado", "descartado"]
	state_totals = {state: by_state.get(state, 0) for state in target_states}

	satisfaction_values: list[float] = []
	if satisfaction_field is not None:
		for row in valid_rows:
			if (row.get("__estado_normalizado") or "").strip() != "cerrado":
				continue
			value = parse_float(row.get(satisfaction_field, ""))
			if value is not None:
				satisfaction_values.append(value)

	satisfaction_mean = (
		round(sum(satisfaction_values) / len(satisfaction_values), 2)
		if satisfaction_values
		else None
	)

	# Métrica legacy para compatibilidad con expected previos.
	resolution_values: list[float] = []
	for row in valid_rows:
		state = (row.get("__estado_normalizado") or "").strip()
		if state not in {"cerrado", "resuelto"}:
			continue
		value = parse_float(row_value(row, resolved_schema, "tiempo_resolucion_horas"))
		if value is not None:
			resolution_values.append(value)

	summary = {
		"total_procesados": len(rows),
		"registros_validos": len(valid_rows),
		"registros_invalidos": len(invalid_rows),
		"total_por_categoria": dict(by_category),
		"total_por_estado": state_totals,
		"total_por_estado_completo": dict(by_state),
		"indice_satisfaccion_medio_cerrados": satisfaction_mean,
		"tiempo_promedio_resolucion_horas": round(sum(resolution_values) / len(resolution_values), 2)
		if resolution_values
		else None,
	}

	return {
		"rules": rules,
		"summary": summary,
		"invalid_reasons": dict(invalid_reason_counter),
		"invalid_rows": invalid_rows,
		"satisfaction_field_detected": satisfaction_field,
	}


def compare_expected(summary: dict[str, Any], expected: dict[str, Any]) -> list[str]:
	mismatches: list[str] = []
	alias_map = {
		"total_registros": "total_procesados",
		"registros_validos": "registros_validos",
		"registros_invalidos": "registros_invalidos",
		"incidencias_por_categoria": "total_por_categoria",
		"incidencias_por_estado": "total_por_estado_completo",
		"tiempo_promedio_resolucion_horas": "tiempo_promedio_resolucion_horas",
	}

	for key, expected_value in expected.items():
		summary_key = alias_map.get(key, key)
		actual_value = summary.get(summary_key)
		if actual_value != expected_value:
			mismatches.append(
				f"{key}: esperado={expected_value!r} | actual={actual_value!r}"
			)
	return mismatches


def print_table(title: str, rows: list[tuple[str, str]]) -> None:
	if not rows:
		return
	width = max(len(key) for key, _ in rows)
	print(f"\n{title}")
	print("-" * (width + 28))
	for key, value in rows:
		print(f"{key.ljust(width)} : {value}")


def print_summary(result: dict[str, Any], csv_path: Path, mismatches: list[str]) -> None:
	summary = result["summary"]

	print("=" * 72)
	print("RESUMEN DE ANALISIS DE INCIDENCIAS")
	print("=" * 72)
	print(f"Archivo analizado : {csv_path}")

	rows = [
		("Total procesados", str(summary["total_procesados"])),
		("Registros validos", str(summary["registros_validos"])),
		("Registros invalidos", str(summary["registros_invalidos"])),
	]
	print_table("Totales", rows)

	invalid_rows = [
		(reason, str(count)) for reason, count in sorted(result["invalid_reasons"].items())
	]
	print_table("Registros invalidos por tipo de problema", invalid_rows)

	print("\nDetalle de registros invalidos")
	print("-" * 72)
	if not result["invalid_rows"]:
		print("No se detectaron registros invalidos.")
	else:
		for row in result["invalid_rows"]:
			motivos = ", ".join(row["motivos"])
			incidente = row["incidente_id"] or "(sin incidente_id)"
			print(f"Linea {row['linea_csv']}: {incidente} -> {motivos}")

	category_rows = [
		(category, str(count))
		for category, count in sorted(summary["total_por_categoria"].items())
	]
	print_table("Total por categoria de incidencia", category_rows)

	state_rows = [
		(state, str(count))
		for state, count in summary["total_por_estado"].items()
	]
	print_table("Total por estado (abierto, cerrado, descartado)", state_rows)

	satisfaction_value = summary["indice_satisfaccion_medio_cerrados"]
	print_table(
		"Indice de satisfaccion medio (estado cerrado con puntuacion)",
		[
			(
				"Indice medio",
				"N/A" if satisfaction_value is None else str(satisfaction_value),
			)
		],
	)

	print("\nValidacion contra valores esperados del CONTEXT")
	print("-" * 72)
	if not mismatches:
		print("Resultado: COINCIDE exactamente con los valores esperados.")
	else:
		print("Resultado: NO COINCIDE con los valores esperados.")
		for diff in mismatches:
			print(f"- {diff}")

	print("=" * 72)


def rows_for_export(result: dict[str, Any], mismatches: list[str]) -> list[tuple[str, str]]:
	summary = result["summary"]
	rows: list[tuple[str, str]] = [
		("total_procesados", str(summary["total_procesados"])),
		("registros_validos", str(summary["registros_validos"])),
		("registros_invalidos", str(summary["registros_invalidos"])),
		(
			"indice_satisfaccion_medio_cerrados",
			"" if summary["indice_satisfaccion_medio_cerrados"] is None else str(summary["indice_satisfaccion_medio_cerrados"]),
		),
	]

	for category, count in sorted(summary["total_por_categoria"].items()):
		rows.append((f"categoria:{category}", str(count)))

	for state, count in summary["total_por_estado"].items():
		rows.append((f"estado:{state}", str(count)))

	for reason, count in sorted(result["invalid_reasons"].items()):
		rows.append((f"invalido:{reason}", str(count)))

	rows.append(("coincide_con_expected", "si" if not mismatches else "no"))
	return rows


def export_results_csv(path: Path, rows: list[tuple[str, str]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8", newline="") as file:
		writer = csv.writer(file)
		writer.writerow(["metrica", "valor"])
		writer.writerows(rows)


def build_api_payload(result: dict[str, Any], mismatches: list[str]) -> dict[str, Any]:
	summary = result["summary"]
	return {
		"contexto": {
			"required_fields": result["rules"]["required_fields"],
			"allowed_categories": result["rules"]["allowed_categories"],
			"allowed_states": result["rules"]["allowed_states"],
		},
		"resumen": summary,
		"invalidos_por_tipo": result["invalid_reasons"],
		"invalidos": result["invalid_rows"],
		"validacion_esperada": {
			"coincide": not mismatches,
			"diferencias": mismatches,
		},
	}


def main() -> int:
	parser = argparse.ArgumentParser(description="Analiza incidencias de un archivo CSV")
	parser.add_argument("csv_path", type=Path, help="Ruta al fichero CSV")
	parser.add_argument(
		"--context",
		type=Path,
		default=DEFAULT_CONTEXT,
		help="Ruta al contexto (JSON con campos/categorias/estados)",
	)
	parser.add_argument(
		"--expected",
		type=Path,
		default=DEFAULT_EXPECTED,
		help="Ruta al expected (JSON con metricas esperadas)",
	)
	parser.add_argument(
		"--json-output",
		type=Path,
		default=None,
		help="Ruta para guardar salida JSON estructurada",
	)
	parser.add_argument(
		"--export-csv-path",
		type=Path,
		default=None,
		help="Ruta de exportacion CSV en modo no interactivo",
	)
	parser.add_argument(
		"--no-prompt",
		action="store_true",
		help="No pedir confirmacion interactiva al final",
	)
	args = parser.parse_args()

	if not args.csv_path.exists():
		print(f"Error: no existe el archivo CSV: {args.csv_path}")
		return 1

	rules = get_rules(args.context)
	result = analyze(args.csv_path, rules)

	expected_payload = load_json_if_exists(args.expected) or {}
	# Soporta expected plano o expected anidado como {"summary": {...}}
	expected_summary = expected_payload.get("summary", expected_payload)
	mismatches = compare_expected(result["summary"], expected_summary) if expected_summary else []
	payload = build_api_payload(result, mismatches)

	print_summary(result, args.csv_path, mismatches)

	if args.json_output is not None:
		args.json_output.parent.mkdir(parents=True, exist_ok=True)
		args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

	if args.no_prompt:
		if args.export_csv_path is not None:
			export_results_csv(args.export_csv_path, rows_for_export(result, mismatches))
			print(f"Resultados exportados en: {args.export_csv_path.resolve()}")
	else:
		choice = input("¿Deseas exportar los resultados a CSV? [s / n] ").strip().lower()
		if choice == "s":
			output_path = Path("results.csv")
			export_results_csv(output_path, rows_for_export(result, mismatches))
			print(f"Resultados exportados en: {output_path.resolve()}")
		else:
			print("Exportacion omitida.")

	return 0 if not mismatches else 2


if __name__ == "__main__":
	raise SystemExit(main())
