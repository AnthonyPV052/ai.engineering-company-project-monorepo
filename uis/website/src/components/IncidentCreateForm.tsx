"use client";

import { FormEvent, useState } from "react";
import { BRANCHES, CATEGORIES, ORIGINS, STATUSES } from "@/lib/incidents-manager";

type Status = (typeof STATUSES)[number][0];
type Origin = (typeof ORIGINS)[number][0];
type Branch = (typeof BRANCHES)[number][0];
type Category = (typeof CATEGORIES)[number][0];
type IncidentForm = {
  title: string;
  description: string;
  category: Category;
  status: Status;
  origin: Origin;
  branch: Branch;
};

const EMPTY_FORM: IncidentForm = {
  title: "",
  description: "",
  category: "equipment_failure",
  status: "open",
  origin: "branch",
  branch: "central",
};

function errorFrom(payload: unknown): { field?: string; message: string } {
  if (payload && typeof payload === "object") {
    const result = payload as {
      error?: { field?: string; message?: string };
      detail?: { field?: string; message?: string };
    };
    const error = result.error ?? result.detail;
    if (error?.message) return { field: error.field, message: error.message };
  }
  return { message: "No pudimos completar la operación. Inténtalo de nuevo." };
}

async function json(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export default function IncidentCreateForm({
  onCreated,
}: {
  onCreated?: () => void;
}) {
  const [form, setForm] = useState<IncidentForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormErrors({});
    setNotice(null);
    try {
      const response = await fetch("/api/incidents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const payload = await json(response);
      if (!response.ok) {
        const error = errorFrom(payload);
        setFormErrors({ [error.field ?? "form"]: error.message });
        return;
      }
      setForm(EMPTY_FORM);
      setNotice("Incidencia registrada correctamente. Ya está disponible para seguimiento.");
      onCreated?.();
    } catch {
      setFormErrors({
        form: "No pudimos registrar la incidencia. Comprueba la conexión e inténtalo de nuevo.",
      });
    } finally {
      setSaving(false);
    }
  }

  const fieldClass =
    "mt-1 min-h-12 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 text-slate-100 focus:border-orange-300 focus:outline-none";

  return (
    <section className="rounded-2xl border border-orange-300/25 bg-slate-900 p-5 sm:p-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-orange-200">Nuevo reporte</p>
        <h2 className="mt-1 text-xl font-bold text-white">Registrar incidencia</h2>
        <p className="mt-2 text-sm text-slate-300">
          Los campos de identificación y fechas se generan al guardar. Completa la información operativa.
        </p>
      </div>
      {notice && (
        <p role="status" className="mt-4 rounded-xl border border-emerald-300/30 bg-emerald-950/30 p-3 text-sm text-emerald-100">
          {notice}
        </p>
      )}
      {formErrors.form && (
        <p role="alert" className="mt-4 rounded-xl border border-rose-400/30 bg-rose-950/30 p-3 text-sm text-rose-100">
          {formErrors.form}
        </p>
      )}
      <form className="mt-5 grid gap-4 sm:grid-cols-2" onSubmit={(e) => void create(e)}>
        <label className="text-sm font-semibold text-slate-200">
          Título
          <input
            required
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            className={fieldClass}
          />
          {formErrors.title && (
            <span className="mt-1 block text-xs text-rose-200">{formErrors.title}</span>
          )}
        </label>
        <label className="text-sm font-semibold text-slate-200">
          Categoría
          <select
            value={form.category}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value as Category }))}
            className={fieldClass}
          >
            {CATEGORIES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          {formErrors.category && (
            <span className="mt-1 block text-xs text-rose-200">{formErrors.category}</span>
          )}
        </label>
        <label className="sm:col-span-2 text-sm font-semibold text-slate-200">
          Descripción
          <textarea
            required
            rows={4}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-3 text-slate-100 focus:border-orange-300 focus:outline-none"
          />
          {formErrors.description && (
            <span className="mt-1 block text-xs text-rose-200">{formErrors.description}</span>
          )}
        </label>
        <label className="text-sm font-semibold text-slate-200">
          Origen
          <select
            value={form.origin}
            onChange={(e) => setForm((f) => ({ ...f, origin: e.target.value as Origin }))}
            className={fieldClass}
          >
            {ORIGINS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-semibold text-slate-200">
          Sede
          <select
            value={form.branch}
            onChange={(e) => setForm((f) => ({ ...f, branch: e.target.value as Branch }))}
            className={fieldClass}
          >
            {BRANCHES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-xl bg-orange-300 px-6 py-3 text-sm font-bold uppercase tracking-wide text-slate-900 transition hover:bg-orange-200 disabled:opacity-60"
          >
            {saving ? "Guardando…" : "Registrar incidencia"}
          </button>
        </div>
      </form>
    </section>
  );
}