"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { BRANCHES, CATEGORIES, ORIGINS, STATUSES, branchLabels, categoryLabels, originLabels, statusLabels } from "@/lib/incidents-manager";

const IncidentCreateForm = dynamic(() => import("@/components/IncidentCreateForm"), {
  loading: () => (
    <section className="rounded-2xl border border-orange-300/25 bg-slate-900 p-5 sm:p-6">
      <p className="text-sm text-slate-400">Cargando formulario de registro…</p>
    </section>
  ),
});

type Status = (typeof STATUSES)[number][0];
type Origin = (typeof ORIGINS)[number][0];
type Branch = (typeof BRANCHES)[number][0];
type Category = (typeof CATEGORIES)[number][0];
type Incident = { id: string; title: string; description: string; category: Category; status: Status; origin: Origin; branch: Branch; created_at: string; updated_at: string };
type Summary = { by_status: Record<string, number>; by_category: Record<string, number>; by_origin: Record<string, number>; by_branch: Record<string, number> };

const NEXT: Record<Status, Status[]> = { open: ["in_progress", "discarded"], in_progress: ["resolved", "discarded"], resolved: [], discarded: [] };

async function json(response: Response): Promise<unknown> {
  try { return await response.json(); } catch { return null; }
}

function Badge({ value }: { value: Status }) {
  const tones: Record<Status, string> = {
    open: "bg-amber-300/10 text-amber-100 border-amber-300/40",
    in_progress: "bg-cyan-300/10 text-cyan-100 border-cyan-300/40",
    resolved: "bg-emerald-300/10 text-emerald-100 border-emerald-300/40",
    discarded: "bg-slate-300/10 text-slate-200 border-slate-400/40",
  };
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-bold ${tones[value]}`}>{statusLabels[value]}</span>;
}

export default function IncidentsBackofficePage() {
  const [items, setItems] = useState<Incident[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [filters, setFilters] = useState<{ status: "" | Status; origin: "" | Origin; branch: "" | Branch }>({ status: "", origin: "", branch: "" });
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [updating, setUpdating] = useState<string | null>(null);
  const query = useMemo(() => {
    const p = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value) p.set(key, value); });
    return p.toString();
  }, [filters]);

  const loadList = useCallback(async () => {
    setLoading(true); setListError(null);
    try {
      const response = await fetch(`/api/incidents${query ? `?${query}` : ""}`);
      const payload = await json(response);
      if (!response.ok || !Array.isArray(payload)) throw new Error();
      setItems(payload as Incident[]);
    } catch {
      setListError("No se pudo cargar el listado de incidencias. Comprueba la conexión y vuelve a intentarlo.");
    } finally { setLoading(false); }
  }, [query]);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true); setSummaryError(null);
    try {
      const response = await fetch("/api/incidents/summary");
      const payload = await json(response);
      if (!response.ok || !payload || typeof payload !== "object") throw new Error();
      setSummary(payload as Summary);
    } catch {
      setSummaryError("No se pudieron cargar las métricas. Puedes reintentarlo sin perder el listado.");
    } finally { setSummaryLoading(false); }
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => void loadList(), 0); return () => window.clearTimeout(timer); }, [loadList]);
  useEffect(() => { const timer = window.setTimeout(() => void loadSummary(), 0); return () => window.clearTimeout(timer); }, [loadSummary]);

  async function changeStatus(item: Incident, next: Status) {
    const previous = item.status;
    setUpdating(item.id);
    setUpdateError(null);
    setItems((all) => all.map((current) => current.id === item.id ? { ...current, status: next } : current));
    try {
      const response = await fetch(`/api/incidents/${item.id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      if (!response.ok) throw new Error();
      await loadSummary();
    } catch {
      setItems((all) => all.map((current) => current.id === item.id ? { ...current, status: previous } : current));
      setUpdateError("No se pudo actualizar el estado. La incidencia conserva su estado anterior.");
    } finally { setUpdating(null); }
  }

  const groups = summary
    ? [["Por estado", summary.by_status, statusLabels], ["Por categoría", summary.by_category, categoryLabels], ["Por origen", summary.by_origin, originLabels], ["Por sede", summary.by_branch, branchLabels]] as const
    : [];
  const fieldClass = "mt-1 min-h-12 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 text-slate-100 focus:border-orange-300 focus:outline-none";

  return (
    <main className="space-y-7 pb-12">
      <section className="relative overflow-hidden rounded-3xl border border-orange-300/25 bg-gradient-to-br from-slate-950 via-orange-950 to-slate-900 p-7 sm:p-10">
        <div className="absolute inset-x-0 bottom-0 h-1 bg-gradient-to-r from-amber-300 via-orange-500 to-rose-500" />
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-orange-200">Operaciones · Brasaland</p>
        <h1 className="mt-3 max-w-3xl text-3xl font-black tracking-tight text-white sm:text-5xl">Incidencias, a la vista antes de que se enfríen.</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-200 sm:text-base">Registra lo que ocurre en cada sede y mueve cada caso por su ciclo de resolución desde una misma consola.</p>
      </section>

      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-5 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-orange-200">Pulso operativo</p>
            <h2 className="mt-1 text-xl font-bold text-white">Resumen de incidencias</h2>
          </div>
          <button type="button" onClick={() => void loadSummary()} disabled={summaryLoading} className="rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 hover:border-orange-300 disabled:opacity-60">
            Actualizar métricas
          </button>
        </div>
        {summaryLoading ? (
          <p className="mt-5 text-sm text-slate-300">Cargando métricas operativas…</p>
        ) : summaryError ? (
          <div className="mt-5 rounded-xl border border-rose-400/30 bg-rose-950/30 p-3 text-sm text-rose-100">
            <p>{summaryError}</p>
            <button type="button" onClick={() => void loadSummary()} className="mt-2 font-bold underline">Reintentar</button>
          </div>
        ) : (
          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {groups.map(([title, values, labels]) => (
              <article key={title} className="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
                <h3 className="text-sm font-bold text-white">{title}</h3>
                <dl className="mt-3 space-y-2">
                  {Object.entries(values).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-3 text-xs">
                      <dt className="text-slate-300">{labels[key] ?? key}</dt>
                      <dd className="font-mono font-bold text-orange-200">{value}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-orange-200">Cola de trabajo</p>
            <h2 className="mt-1 text-xl font-bold text-white">Listado de incidencias</h2>
          </div>
          <button type="button" onClick={() => void loadList()} className="rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 hover:border-orange-300">Reintentar carga</button>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <label className="text-sm font-semibold text-slate-200">
            Estado
            <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value as "" | Status }))} className={fieldClass}>
              <option value="">Todos los estados</option>
              {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="text-sm font-semibold text-slate-200">
            Origen
            <select value={filters.origin} onChange={(e) => setFilters((f) => ({ ...f, origin: e.target.value as "" | Origin }))} className={fieldClass}>
              <option value="">Todos los orígenes</option>
              {ORIGINS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="text-sm font-semibold text-slate-200">
            Sede
            <select value={filters.branch} onChange={(e) => setFilters((f) => ({ ...f, branch: e.target.value as "" | Branch }))} className={fieldClass}>
              <option value="">Todas las sedes</option>
              {BRANCHES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        </div>
        {updateError && <p role="alert" className="mt-4 rounded-xl border border-rose-400/30 bg-rose-950/30 p-3 text-sm text-rose-100">{updateError}</p>}
        {loading ? (
          <p className="mt-6 text-sm text-slate-300">Cargando incidencias…</p>
        ) : listError ? (
          <div className="mt-6 rounded-xl border border-rose-400/30 bg-rose-950/30 p-4 text-sm text-rose-100">
            <p>{listError}</p>
            <button type="button" onClick={() => void loadList()} className="mt-2 font-bold underline">Reintentar</button>
          </div>
        ) : (
          <ul className="mt-6 space-y-3">
            {items.map((item) => (
              <li key={item.id} className="rounded-xl border border-slate-700 bg-slate-800/80 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-bold text-white">{item.title}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      {item.description.length > 120 ? `${item.description.slice(0, 120)}…` : item.description}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge value={item.status} />
                      <span className="text-xs text-slate-400">{categoryLabels[item.category]}</span>
                      <span className="text-xs text-slate-400">{originLabels[item.origin] ?? item.origin}</span>
                      <span className="text-xs text-slate-400">{branchLabels[item.branch] ?? item.branch}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {NEXT[item.status].map((next) => (
                      <button
                        key={next}
                        type="button"
                        disabled={updating === item.id}
                        onClick={() => void changeStatus(item, next)}
                        className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-100 transition hover:border-orange-300 disabled:opacity-60"
                      >
                        {statusLabels[next]}
                      </button>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <IncidentCreateForm onCreated={() => { void loadList(); void loadSummary(); }} />
    </main>
  );
}
