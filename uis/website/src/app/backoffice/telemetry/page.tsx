"use client";

import { useEffect, useState } from "react";

/* Next.js rewrites /api/:path* → API_UPSTREAM_URL (ver next.config.ts).
  Usamos /api/ para evitar CORS y aprovechar
   el proxy del servidor Next.js. */
const API_BASE = "/api";

/* ========================================================================
   Tipos
   ======================================================================== */

interface Period {
  from: string;
  to: string;
}

interface EventsPerDayRow {
  date: string;
  event_type: string;
  count: number;
}

interface ErrorRateRow {
  error_type: string;
  count: number;
  rate: number;
}

interface AuthFailureRow {
  date: string;
  attempts: number;
  failures: number;
  failure_rate: number;
}

interface Report {
  period: Period;
  metrics: {
    events_per_day: EventsPerDayRow[];
    error_rate_by_type: ErrorRateRow[];
    auth_failure_rate: AuthFailureRow[];
  };
}

/* ========================================================================
   Componentes internos — barras inline
   ======================================================================== */

function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-right text-xs text-slate-400">{label}</span>
      <div className="h-3 w-full max-w-xs rounded-full bg-slate-700">
        <div
          className="h-full rounded-full bg-cyan-400 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-16 text-right text-xs font-mono text-slate-200">{value}</span>
    </div>
  );
}

/* ========================================================================
   Página principal
   ======================================================================== */

export default function TelemetryDashboardPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchReport() {
      try {
        const res = await fetch(`${API_BASE}/telemetry/report`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        const data: Report = await res.json();
        if (!cancelled) setReport(data);
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchReport();
    return () => {
      cancelled = true;
    };
  }, []);

  /* ---- Estado de carga / error ---- */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-slate-400">
        Cargando reporte de telemetría…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-400/30 bg-red-950/20 p-6 text-sm text-red-300">
        Error al cargar el reporte: {error}
      </div>
    );
  }

  if (!report) {
    return (
      <div className="rounded-xl border border-yellow-400/30 bg-yellow-950/20 p-6 text-sm text-yellow-300">
        No hay datos de reporte disponibles.
      </div>
    );
  }

  const { period, metrics } = report;

  /* ---- Maximos para escala de barras ---- */
  const maxEvents = Math.max(1, ...metrics.events_per_day.map((r) => r.count));
  const maxErrors = Math.max(1, ...metrics.error_rate_by_type.map((r) => r.count));

  return (
    <div className="space-y-8">
      {/* Encabezado */}
      <div>
        <p className="inline-flex rounded-full border border-cyan-200/40 bg-cyan-200/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100">
          Radar operacional — Ingeniería
        </p>
        <h1 className="mt-3 text-3xl font-black text-white">Reporte de telemetría</h1>
        <p className="mt-1 text-sm text-slate-400">
          Período: <span className="font-mono text-cyan-300">{period.from}</span>
          {" → "}
          <span className="font-mono text-cyan-300">{period.to}</span>
        </p>
      </div>

      <hr className="border-slate-800" />

      {/* events_per_day */}
      <section>
        <h2 className="text-lg font-bold text-white">Eventos por día</h2>
        <p className="mb-3 text-xs text-slate-400">
          Volumen diario de eventos desglosado por tipo.
        </p>

        {metrics.events_per_day.length === 0 ? (
          <p className="text-sm text-slate-500">Sin datos en este período.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-700 bg-slate-900/60">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs uppercase text-slate-400">
                  <th className="px-4 py-3 font-medium">Fecha</th>
                  <th className="px-4 py-3 font-medium">Tipo de evento</th>
                  <th className="px-4 py-3 font-medium text-right">Conteo</th>
                  <th className="px-4 py-3 font-medium">Barra</th>
                </tr>
              </thead>
              <tbody>
                {metrics.events_per_day.map((row, i) => (
                  <tr
                    key={`${row.date}-${row.event_type}-${i}`}
                    className="border-b border-slate-800 last:border-0 hover:bg-slate-800/40"
                  >
                    <td className="px-4 py-2 font-mono text-xs text-slate-300">{row.date}</td>
                    <td className="px-4 py-2 text-slate-100">{row.event_type}</td>
                    <td className="px-4 py-2 text-right font-mono text-cyan-300">{row.count}</td>
                    <td className="px-4 py-2">
                      <div className="h-3 w-32 rounded-full bg-slate-700">
                        <div
                          className="h-full rounded-full bg-cyan-400 transition-all"
                          style={{ width: `${(row.count / maxEvents) * 100}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <hr className="border-slate-800" />

      {/* error_rate_by_type */}
      <section>
        <h2 className="text-lg font-bold text-white">Distribución de errores de API</h2>
        <p className="mb-3 text-xs text-slate-400">
          Proporción de cada tipo de error sobre el total de eventos
          <code className="mx-1 rounded bg-slate-800 px-1.5 py-0.5 font-mono text-orange-300">api_error_occurred</code>
        </p>

        {metrics.error_rate_by_type.length === 0 ? (
          <p className="text-sm text-slate-500">Sin errores registrados en este período.</p>
        ) : (
          <div className="space-y-2">
            {metrics.error_rate_by_type.map((row, i) => (
              <Bar
                key={`err-${row.error_type}-${i}`}
                label={row.error_type}
                value={row.count}
                max={maxErrors}
              />
            ))}
            <div className="mt-2 flex items-center gap-4 text-xs text-slate-400">
              <span>
                Total: <span className="font-mono text-white">{metrics.error_rate_by_type.reduce((a, r) => a + r.count, 0)}</span>
              </span>
            </div>
          </div>
        )}
      </section>

      <hr className="border-slate-800" />

      {/* auth_failure_rate */}
      <section>
        <h2 className="text-lg font-bold text-white">Tasa de fallo de autenticación</h2>
        <p className="mb-3 text-xs text-slate-400">
          Intentos de login fallidos / totales por día.
        </p>

        {metrics.auth_failure_rate.length === 0 ? (
          <p className="text-sm text-slate-500">Sin eventos de autenticación en este período.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-700 bg-slate-900/60">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs uppercase text-slate-400">
                  <th className="px-4 py-3 font-medium">Fecha</th>
                  <th className="px-4 py-3 font-medium text-right">Intentos</th>
                  <th className="px-4 py-3 font-medium text-right">Fallos</th>
                  <th className="px-4 py-3 font-medium text-right">Tasa</th>
                  <th className="px-4 py-3 font-medium">Barra</th>
                </tr>
              </thead>
              <tbody>
                {metrics.auth_failure_rate.map((row, i) => {
                  const pct = row.failure_rate * 100;
                  return (
                    <tr
                      key={`auth-${row.date}-${i}`}
                      className="border-b border-slate-800 last:border-0 hover:bg-slate-800/40"
                    >
                      <td className="px-4 py-2 font-mono text-xs text-slate-300">{row.date}</td>
                      <td className="px-4 py-2 text-right font-mono text-slate-100">{row.attempts}</td>
                      <td className="px-4 py-2 text-right font-mono text-red-400">{row.failures}</td>
                      <td className="px-4 py-2 text-right font-mono text-orange-300">
                        {pct.toFixed(1)}%
                      </td>
                      <td className="px-4 py-2">
                        <div className="h-3 w-32 rounded-full bg-slate-700">
                          <div
                            className={`h-full rounded-full transition-all ${
                              pct > 50 ? "bg-red-500" : pct > 10 ? "bg-orange-400" : "bg-emerald-400"
                            }`}
                            style={{ width: `${Math.min(pct, 100)}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}