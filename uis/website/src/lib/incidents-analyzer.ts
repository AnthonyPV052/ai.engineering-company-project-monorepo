import {
  INCIDENTS_ALLOWED_CATEGORIES,
  INCIDENTS_ALLOWED_STATES,
  INCIDENTS_EXPECTED_SUMMARY,
  INCIDENTS_REQUIRED_FIELDS,
} from "@/lib/incidents-config";

export type IncidentRow = Record<string, string>;

export interface InvalidIncident {
  linea_csv: number;
  incidente_id: string;
  errores: string[];
}

export interface IncidentsSummary {
  total_registros: number;
  registros_validos: number;
  registros_invalidos: number;
  porcentaje_invalidos: number;
  incidencias_por_categoria: Record<string, number>;
  incidencias_por_estado: Record<string, number>;
  tiempo_promedio_resolucion_horas: number | null;
}

export interface IncidentsAnalysisResult {
  contexto: {
    required_fields: readonly string[];
    allowed_categories: readonly string[];
    allowed_states: readonly string[];
  };
  resumen: IncidentsSummary;
  invalidos: InvalidIncident[];
  validacion_esperada: {
    coincide: boolean;
    diferencias: string[];
  };
}

function parseCsvLine(line: string): string[] {
  const values: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];

    if (char === '"') {
      const next = line[i + 1];
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === "," && !inQuotes) {
      values.push(current);
      current = "";
      continue;
    }

    current += char;
  }

  values.push(current);
  return values;
}

export function parseCsv(text: string): IncidentRow[] {
  const lines = text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .filter((line) => line.trim().length > 0);

  if (lines.length < 2) {
    return [];
  }

  const headers = parseCsvLine(lines[0]).map((item) => item.trim());
  const rows: IncidentRow[] = [];

  for (let i = 1; i < lines.length; i += 1) {
    const values = parseCsvLine(lines[i]);
    const row: IncidentRow = {};

    headers.forEach((header, index) => {
      row[header] = (values[index] ?? "").trim();
    });

    rows.push(row);
  }

  return rows;
}

function isValidIsoDate(value: string): boolean {
  const match = /^\d{4}-\d{2}-\d{2}$/.test(value);
  if (!match) {
    return false;
  }

  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

function parsePositiveNumber(value: string): number | null {
  if (!value) {
    return null;
  }

  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    return null;
  }

  return parsed;
}

function countBy(items: string[]): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, current) => {
    acc[current] = (acc[current] ?? 0) + 1;
    return acc;
  }, {});
}

function compareExpectedSummary(summary: IncidentsSummary): string[] {
  const diffs: string[] = [];

  const scalarKeys: Array<keyof typeof INCIDENTS_EXPECTED_SUMMARY> = [
    "total_registros",
    "registros_validos",
    "registros_invalidos",
    "tiempo_promedio_resolucion_horas",
  ];

  scalarKeys.forEach((key) => {
    const expected = INCIDENTS_EXPECTED_SUMMARY[key];
    const actual = summary[key as keyof IncidentsSummary] as unknown;
    if (expected !== actual) {
      diffs.push(`${String(key)}: esperado=${String(expected)} actual=${String(actual)}`);
    }
  });

  Object.entries(INCIDENTS_EXPECTED_SUMMARY.incidencias_por_categoria).forEach(
    ([key, value]) => {
      const actual = summary.incidencias_por_categoria[key] ?? 0;
      if (actual !== value) {
        diffs.push(`incidencias_por_categoria.${key}: esperado=${value} actual=${actual}`);
      }
    },
  );

  Object.entries(INCIDENTS_EXPECTED_SUMMARY.incidencias_por_estado).forEach(
    ([key, value]) => {
      const actual = summary.incidencias_por_estado[key] ?? 0;
      if (actual !== value) {
        diffs.push(`incidencias_por_estado.${key}: esperado=${value} actual=${actual}`);
      }
    },
  );

  return diffs;
}

export function analyzeIncidentRows(rows: IncidentRow[]): IncidentsAnalysisResult {
  const validRows: IncidentRow[] = [];
  const invalidRows: InvalidIncident[] = [];

  rows.forEach((row, index) => {
    const errors: string[] = [];

    INCIDENTS_REQUIRED_FIELDS.forEach((field) => {
      if (!(row[field] ?? "").trim()) {
        errors.push(`campo_obligatorio_faltante:${field}`);
      }
    });

    const category = (row.categoria ?? "").trim();
    const state = (row.estado ?? "").trim();
    const date = (row.fecha_creacion ?? "").trim();
    const resolutionRaw = (row.tiempo_resolucion_horas ?? "").trim();

    if (category && !INCIDENTS_ALLOWED_CATEGORIES.includes(category as (typeof INCIDENTS_ALLOWED_CATEGORIES)[number])) {
      errors.push("categoria_no_permitida");
    }

    if (state && !INCIDENTS_ALLOWED_STATES.includes(state as (typeof INCIDENTS_ALLOWED_STATES)[number])) {
      errors.push("estado_no_permitido");
    }

    if (date && !isValidIsoDate(date)) {
      errors.push("fecha_creacion_invalida");
    }

    if (resolutionRaw) {
      const resolutionHours = parsePositiveNumber(resolutionRaw);
      if (resolutionHours === null) {
        errors.push("tiempo_resolucion_no_numerico");
      } else if (resolutionHours < 0) {
        errors.push("tiempo_resolucion_negativo");
      }
    }

    if (errors.length > 0) {
      invalidRows.push({
        linea_csv: index + 2,
        incidente_id: row.incidente_id ?? "",
        errores: errors,
      });
      return;
    }

    validRows.push(row);
  });

  const categories = validRows.map((row) => row.categoria.trim());
  const states = validRows.map((row) => row.estado.trim());

  const resolutionValues = validRows
    .filter((row) => ["resuelto", "cerrado"].includes(row.estado.trim()))
    .map((row) => parsePositiveNumber((row.tiempo_resolucion_horas ?? "").trim()))
    .filter((value): value is number => value !== null);

  const total = rows.length;
  const invalidCount = invalidRows.length;

  const summary: IncidentsSummary = {
    total_registros: total,
    registros_validos: validRows.length,
    registros_invalidos: invalidCount,
    porcentaje_invalidos:
      total > 0 ? Number(((invalidCount / total) * 100).toFixed(2)) : 0,
    incidencias_por_categoria: countBy(categories),
    incidencias_por_estado: countBy(states),
    tiempo_promedio_resolucion_horas:
      resolutionValues.length > 0
        ? Number(
            (
              resolutionValues.reduce((acc, value) => acc + value, 0) /
              resolutionValues.length
            ).toFixed(2),
          )
        : null,
  };

  const differences = compareExpectedSummary(summary);

  return {
    contexto: {
      required_fields: INCIDENTS_REQUIRED_FIELDS,
      allowed_categories: INCIDENTS_ALLOWED_CATEGORIES,
      allowed_states: INCIDENTS_ALLOWED_STATES,
    },
    resumen: summary,
    invalidos: invalidRows,
    validacion_esperada: {
      coincide: differences.length === 0,
      diferencias: differences,
    },
  };
}

export function summaryToCsv(summary: IncidentsSummary): string {
  const lines: string[] = ["metrica,valor"];

  lines.push(`total_registros,${summary.total_registros}`);
  lines.push(`registros_validos,${summary.registros_validos}`);
  lines.push(`registros_invalidos,${summary.registros_invalidos}`);
  lines.push(`porcentaje_invalidos,${summary.porcentaje_invalidos}`);
  lines.push(
    `tiempo_promedio_resolucion_horas,${
      summary.tiempo_promedio_resolucion_horas ?? ""
    }`,
  );

  Object.entries(summary.incidencias_por_categoria).forEach(([key, value]) => {
    lines.push(`categoria:${key},${value}`);
  });

  Object.entries(summary.incidencias_por_estado).forEach(([key, value]) => {
    lines.push(`estado:${key},${value}`);
  });

  return `${lines.join("\n")}\n`;
}
