"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, getStoredToken } from "@/lib/auth";

/* ========================================================================
   Tipos específicos del dominio "Reporte Semanal de Costo y Merma por Local"
   (pipeline-context.md secciones 2, 4, 6)
   ======================================================================== */

interface LocationKpi {
  location_id: string;
  country: string;
  total_purchase_cost: number;
  total_waste_cost: number;
  waste_ratio: number;
  stockout_events_count: number;
  price_alert_events_count: number;
  currency: string;
}

interface WeeklyReport {
  week_start: string;
  locations: LocationKpi[];
}

interface PipelineRun {
  id: string;
  pipeline_name: string;
  week_start: string;
  status: string;
  started_at: string;
  finished_at: string;
  rows_upserted: number;
  error_message: string | null;
}

/* ========================================================================
   Helpers
   ======================================================================== */

function currencySymbol(currency: string): string {
  if (currency === "USD") return "$";
  if (currency === "COP") return "$";
  return currency;
}

function formatCost(value: number, currency: string): string {
  const sym = currencySymbol(currency);
  if (currency === "COP") {
    return `${sym} ${value.toLocaleString("es-CO")}`;
  }
  return `${sym} ${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatRatio(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("es-CO", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function locationLabel(id: string): string {
  const labels: Record<string, string> = {
    "medellin-centro": "Medellín Centro",
    "medellin-envigado": "Medellín Envigado",
    "medellin-poblado": "Medellín Poblado",
    "bogota-norte": "Bogotá Norte",
    "bogota-sur": "Bogotá Sur",
    "cali": "Cali",
    "barranquilla": "Barranquilla",
    "cartagena": "Cartagena",
    "miami-brickell": "Miami Brickell",
    "miami-southbeach": "Miami South Beach",
    "miami-downtown": "Miami Downtown",
    "orlando": "Orlando",
    "newyork-midtown": "New York Midtown",
    "newyork-brooklyn": "New York Brooklyn",
  };
  return labels[id] ?? id;
}

/* ========================================================================
   Componente: Tarjeta de resumen de un KPI
   ======================================================================== */

function KpiCard({
  title,
  value,
  subtitle,
  color,
}: {
  title: string;
  value: string;
  subtitle?: string;
  color: "orange" | "red" | "cyan" | "amber" | "rose";
}) {
  const borderColor: Record<string, string> = {
    orange: "border-orange-300/30",
    red: "border-red-300/30",
    cyan: "border-cyan-300/30",
    amber: "border-amber-300/30",
    rose: "border-rose-300/30",
  };
  const textColor: Record<string, string> = {
    orange: "text-orange-200",
    red: "text-red-200",
    cyan: "text-cyan-200",
    amber: "text-amber-200",
    rose: "text-rose-200",
  };

  return (
    <div className={`rounded-xl border ${borderColor[color]} bg-slate-900/60 p-5`}>
      <p className={`text-xs font-semibold uppercase tracking-wide ${textColor[color]}`}>
        {title}
      </p>
      <p className="mt-2 text-2xl font-black text-white">{value}</p>
      {subtitle && <p className="mt-1 text-xs text-slate-400">{subtitle}</p>}
    </div>
  );
}

/* ========================================================================
   Componente: Tabla de locales
   ======================================================================== */

function LocationsTable({ locations }: { locations: LocationKpi[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-700/50">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-700 bg-slate-800/50">
          <tr>
            <th className="px-4 py-3 font-semibold text-slate-300">Local</th>
            <th className="px-4 py-3 font-semibold text-slate-300">País</th>
            <th className="px-4 py-3 text-right font-semibold text-slate-300">Costo de compra</th>
            <th className="px-4 py-3 text-right font-semibold text-slate-300">Costo de merma</th>
            <th className="px-4 py-3 text-right font-semibold text-slate-300">Ratio de merma</th>
            <th className="px-4 py-3 text-right font-semibold text-slate-300">Quiebres de stock</th>
            <th className="px-4 py-3 text-right font-semibold text-slate-300">Alertas de precio</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {locations.map((loc) => (
            <tr key={loc.location_id} className="transition hover:bg-slate-800/40">
              <td className="px-4 py-3 font-medium text-white">{locationLabel(loc.location_id)}</td>
              <td className="px-4 py-3 text-slate-300">{loc.country === "CO" ? "🇨🇴 Colombia" : "🇺🇸 USA"}</td>
              <td className="px-4 py-3 text-right font-mono text-slate-200">
                {formatCost(loc.total_purchase_cost, loc.currency)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-slate-200">
                {formatCost(loc.total_waste_cost, loc.currency)}
              </td>
              <td className="px-4 py-3 text-right font-mono" style={{ color: loc.waste_ratio > 0.02 ? "#fca5a5" : loc.waste_ratio > 0 ? "#fbbf24" : "#6ee7b7" }}>
                {formatRatio(loc.waste_ratio)}
              </td>
              <td className="px-4 py-3 text-right font-mono" style={{ color: loc.stockout_events_count > 0 ? "#fca5a5" : "#6ee7b7" }}>
                {loc.stockout_events_count}
              </td>
              <td className="px-4 py-3 text-right font-mono" style={{ color: loc.price_alert_events_count > 0 ? "#fca5a5" : "#6ee7b7" }}>
                {loc.price_alert_events_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ========================================================================
   Página principal: Reporte Semanal de Costo y Merma por Local
   ======================================================================== */

export default function ReportingDashboardPage() {
  const [report, setReport] = useState<WeeklyReport | null>(null);
  const [pipelineRun, setPipelineRun] = useState<PipelineRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    const token = getStoredToken();
    if (!token) {
      setError("No hay sesión activa. Inicia sesión para ver el reporte.");
      setLoading(false);
      return;
    }

    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };

    try {
      const [kpisRes, runRes] = await Promise.all([
        fetch(`${API_BASE}/reporting/weekly-location-performance`, { headers }),
        fetch(`${API_BASE}/reporting/pipeline-runs/latest`, { headers }),
      ]);

      if (!kpisRes.ok) {
        const errText = await kpisRes.text().catch(() => "");
        throw new Error(`KPIs: HTTP ${kpisRes.status} — ${errText || kpisRes.statusText}`);
      }

      const kpisData: WeeklyReport = await kpisRes.json();

      let runData: PipelineRun | null = null;
      if (runRes.ok) {
        runData = await runRes.json();
      }

      setReport(kpisData);
      setPipelineRun(runData);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  /* ---- Estado: cargando ---- */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-slate-400">
        Cargando reporte semanal de costo y merma…
      </div>
    );
  }

  /* ---- Estado: error ---- */
  if (error) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-red-400/30 bg-red-950/20 p-6 text-sm text-red-300">
          Error al cargar el reporte: {error}
        </div>
        <button
          onClick={fetchData}
          className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 transition hover:border-orange-300 hover:text-orange-200"
        >
          Reintentar
        </button>
      </div>
    );
  }

  /* ---- Estado: sin datos ---- */
  if (!report || !report.locations || report.locations.length === 0) {
    return (
      <div className="rounded-xl border border-yellow-400/30 bg-yellow-950/20 p-6 text-sm text-yellow-300">
        No hay datos disponibles. Ejecuta el pipeline desde CLI o desde{" "}
        <code className="text-yellow-100">POST /reporting/pipeline-runs</code>.
      </div>
    );
  }

  /* ---- Totales para las tarjetas de resumen ---- */
  const totalPurchase = report.locations.reduce((s, l) => s + l.total_purchase_cost, 0);
  const totalWaste = report.locations.reduce((s, l) => s + l.total_waste_cost, 0);
  const totalStockouts = report.locations.reduce((s, l) => s + l.stockout_events_count, 0);
  const totalPriceAlerts = report.locations.reduce((s, l) => s + l.price_alert_events_count, 0);
  const avgWasteRatio = totalPurchase > 0 ? totalWaste / totalPurchase : 0;
  const copLocations = report.locations.filter((l) => l.currency === "COP");
  const usdLocations = report.locations.filter((l) => l.currency === "USD");

  return (
    <div className="space-y-8">
      {/* ── Encabezado ─────────────────────────────────────────────── */}
      <div>
        <p className="inline-flex rounded-full border border-orange-200/40 bg-orange-200/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-orange-100">
          Desempeño de negocio — Costo y Merma
        </p>
        <h1 className="mt-3 text-3xl font-black text-white">Reporte Semanal de Costo y Merma por Local</h1>
        <p className="mt-1 text-sm text-slate-400">
          Semana que comienza:{" "}
          <span className="font-mono text-orange-300">{formatDate(report.week_start)}</span>
          {" · "}
          <span className="text-slate-500">{report.locations.length} locales reportados</span>
        </p>
        {pipelineRun && (
          <p className="mt-0.5 text-xs text-slate-500">
            Pipeline:{" "}
            <span className={pipelineRun.status === "completed" ? "text-emerald-400" : "text-red-400"}>
              {pipelineRun.status}
            </span>
            {" · "}
            {pipelineRun.finished_at && `Actualizado: ${formatDate(pipelineRun.finished_at)}`}
            {" · "}
            {pipelineRun.rows_upserted} filas upserted
          </p>
        )}
      </div>

      <hr className="border-slate-800" />

      {/* ── Tarjetas de resumen: KPIs globales ─────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard
          title="Costo de compra por local"
          value={formatCost(totalPurchase, "COP")}
          subtitle={`${copLocations.length} locales COP + ${usdLocations.length} locales USD`}
          color="orange"
        />
        <KpiCard
          title="Costo de merma por local"
          value={formatCost(totalWaste, "COP")}
          subtitle={`${((totalWaste / (totalPurchase || 1)) * 100).toFixed(2)}% del costo de compra`}
          color="red"
        />
        <KpiCard
          title="Ratio de merma"
          value={formatRatio(avgWasteRatio)}
          subtitle="Promedio ponderado entre todos los locales"
          color="cyan"
        />
        <KpiCard
          title="Frecuencia de quiebre de stock"
          value={String(totalStockouts)}
          subtitle={`${report.locations.filter((l) => l.stockout_events_count > 0).length} locales afectados`}
          color="amber"
        />
        <KpiCard
          title="Frecuencia de alertas de precio"
          value={String(totalPriceAlerts)}
          subtitle={`${report.locations.filter((l) => l.price_alert_events_count > 0).length} locales afectados`}
          color="rose"
        />
      </div>

      {/* ── Tabla detallada por local ──────────────────────────────── */}
      <section>
        <h2 className="mb-4 text-xl font-bold text-white">Detalle por local</h2>
        <LocationsTable locations={report.locations} />
      </section>

      {/* ── Nota sobre monedas ──────────────────────────────────────── */}
      <footer className="rounded-lg border border-slate-700/50 bg-slate-900/40 p-4 text-xs text-slate-500">
        Los valores en COP y USD se reportan por separado, lado a lado. No se mezclan monedas en una misma fila agregada.
        Los costos en USD no se convierten a COP — eso es una mejora planificada para v2 del pipeline.
      </footer>
    </div>
  );
}