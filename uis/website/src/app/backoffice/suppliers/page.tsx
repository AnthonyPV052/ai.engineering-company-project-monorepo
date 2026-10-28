"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { authenticatedApiFetch } from "@/lib/auth";

const VALID_CATEGORIES = [
  "carne",
  "verduras_y_hortalizas",
  "salsas_y_condimentos",
  "bebidas",
  "packaging",
  "productos_limpieza",
  "lacteos",
  "carbon_y_combustible",
] as const;

type SupplierStatus = "active" | "suspended";
type SupplierCountry = "Colombia" | "USA";
type SupplierCurrency = "COP" | "USD";

interface Supplier {
  id: number;
  name: string;
  country: SupplierCountry;
  categories: string[];
  rate_per_unit: number;
  currency: SupplierCurrency;
  updated_at: string;
  status: SupplierStatus;
  contact_email?: string | null;
  notes?: string | null;
}

interface SupplierCreateForm {
  name: string;
  country: SupplierCountry;
  categories: string[];
  rate_per_unit: string;
  currency: SupplierCurrency;
  status: SupplierStatus;
  contact_email: string;
  notes: string;
}

const EMPTY_FORM: SupplierCreateForm = {
  name: "",
  country: "Colombia",
  categories: ["carne"],
  rate_per_unit: "",
  currency: "COP",
  status: "active",
  contact_email: "",
  notes: "",
};

function StatusBadge({ status }: { status: SupplierStatus }) {
  return (
    <span
      className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${
        status === "active"
          ? "bg-emerald-300/20 text-emerald-200"
          : "bg-rose-300/20 text-rose-200"
      }`}
    >
      {status}
    </span>
  );
}

export default function SuppliersDirectoryPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [countryFilter, setCountryFilter] = useState<"" | SupplierCountry>("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [form, setForm] = useState<SupplierCreateForm>(EMPTY_FORM);
  const [rateDrafts, setRateDrafts] = useState<Record<number, string>>({});

  const filteredPath = useMemo(() => {
    const params = new URLSearchParams();
    if (countryFilter) params.set("country", countryFilter);
    if (categoryFilter) params.set("category", categoryFilter);
    const query = params.toString();
    return query ? `/suppliers?${query}` : "/suppliers";
  }, [countryFilter, categoryFilter]);

  async function loadSuppliers(showLoading = true) {
    setLoading(true);
    setError(null);
    try {
      const data = await authenticatedApiFetch<Supplier[]>(filteredPath);
      setSuppliers(data);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Error al cargar proveedores.");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function fetchOnFilterChange() {
      try {
        const data = await authenticatedApiFetch<Supplier[]>(filteredPath);
        if (!cancelled) {
          setSuppliers(data);
          setError(null);
        }
      } catch (caughtError) {
        if (!cancelled) {
          setError(caughtError instanceof Error ? caughtError.message : "Error al cargar proveedores.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchOnFilterChange();

    return () => {
      cancelled = true;
    };
  }, [filteredPath]);

  const onCreateSupplier = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setMessage(null);

    try {
      const payload = {
        ...form,
        rate_per_unit: Number(form.rate_per_unit),
        contact_email: form.contact_email.trim() || null,
        notes: form.notes.trim() || null,
      };

      await authenticatedApiFetch<Supplier>("/supplier", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setMessage("Proveedor creado correctamente.");
      setForm({ ...EMPTY_FORM, country: form.country, currency: form.currency });
      await loadSuppliers();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Error al crear proveedor.");
    }
  };

  const onUpdateRate = async (supplier: Supplier) => {
    const draftValue = rateDrafts[supplier.id];
    if (!draftValue) {
      setError("Debes indicar una tarifa válida antes de actualizar.");
      return;
    }

    setError(null);
    setMessage(null);

    try {
      await authenticatedApiFetch<Supplier>(`/suppliers/${supplier.id}/rate`, {
        method: "PATCH",
        body: JSON.stringify({ rate_per_unit: Number(draftValue) }),
      });
      setMessage(`Tarifa actualizada para ${supplier.name}.`);
      await loadSuppliers();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Error al actualizar tarifa.");
    }
  };

  const onToggleStatus = async (supplier: Supplier) => {
    const nextStatus: SupplierStatus = supplier.status === "active" ? "suspended" : "active";

    setError(null);
    setMessage(null);
    try {
      await authenticatedApiFetch<Supplier>(`/suppliers/${supplier.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus }),
      });
      setMessage(`Estado de ${supplier.name} actualizado a ${nextStatus}.`);
      await loadSuppliers();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Error al cambiar estado.");
    }
  };

  return (
    <main className="space-y-8 pb-10">
      <section className="rounded-3xl border border-cyan-300/20 bg-gradient-to-br from-slate-900 via-cyan-950 to-orange-900 p-8">
        <p className="inline-flex rounded-full border border-cyan-200/40 bg-cyan-200/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100">
          Procurement Directory
        </p>
        <h1 className="mt-4 text-4xl font-black text-white">Directorio de proveedores</h1>
        <p className="mt-3 max-w-3xl text-sm text-slate-200">
          Fuente de verdad única para el equipo de compras: registro, filtrado y actualización de proveedores con trazabilidad.
        </p>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <article className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
          <h2 className="text-xl font-bold text-white">Filtros</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="text-sm text-slate-200">
              País
              <select
                value={countryFilter}
                onChange={(event) => setCountryFilter(event.target.value as "" | SupplierCountry)}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
              >
                <option value="">Todos</option>
                <option value="Colombia">Colombia</option>
                <option value="USA">USA</option>
              </select>
            </label>

            <label className="text-sm text-slate-200">
              Categoría
              <select
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
              >
                <option value="">Todas</option>
                {VALID_CATEGORIES.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </article>

        <article className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
          <h2 className="text-xl font-bold text-white">Estado de carga</h2>
          <p className="mt-3 text-sm text-slate-300">{loading ? "Cargando proveedores..." : `Resultados: ${suppliers.length}`}</p>
          {message && <p className="mt-3 rounded-lg bg-emerald-300/20 px-3 py-2 text-sm text-emerald-100">{message}</p>}
          {error && <p className="mt-3 rounded-lg bg-rose-300/20 px-3 py-2 text-sm text-rose-100">{error}</p>}
        </article>
      </section>

      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
        <h2 className="text-xl font-bold text-white">Listado de proveedores</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full table-auto text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left text-slate-300">
                <th className="px-3 py-2">Nombre</th>
                <th className="px-3 py-2">País</th>
                <th className="px-3 py-2">Categorías</th>
                <th className="px-3 py-2">Tarifa</th>
                <th className="px-3 py-2">Estado</th>
                <th className="px-3 py-2">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((supplier) => (
                <tr key={supplier.id} className="border-b border-slate-800 align-top">
                  <td className="px-3 py-3 text-slate-100">
                    <p className="font-semibold">{supplier.name}</p>
                    <p className="text-xs text-slate-400">ID: {supplier.id}</p>
                  </td>
                  <td className="px-3 py-3 text-slate-200">{supplier.country}</td>
                  <td className="px-3 py-3 text-slate-200">{supplier.categories.join(", ")}</td>
                  <td className="px-3 py-3 text-slate-200">
                    {supplier.rate_per_unit} {supplier.currency}
                    <p className="mt-1 text-xs text-slate-400">Actualizado: {new Date(supplier.updated_at).toLocaleString()}</p>
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={supplier.status} />
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex min-w-[260px] flex-col gap-2">
                      <div className="flex gap-2">
                        <input
                          type="number"
                          step="0.01"
                          min="0.01"
                          placeholder="Nueva tarifa"
                          value={rateDrafts[supplier.id] ?? ""}
                          onChange={(event) => {
                            setRateDrafts((prev) => ({ ...prev, [supplier.id]: event.target.value }));
                          }}
                          className="w-full rounded-md border border-slate-600 bg-slate-950 px-2 py-1 text-xs"
                        />
                        <button
                          type="button"
                          onClick={() => void onUpdateRate(supplier)}
                          className="rounded-md bg-cyan-300 px-2 py-1 text-xs font-semibold text-slate-900"
                        >
                          Tarifa
                        </button>
                      </div>

                      <button
                        type="button"
                        onClick={() => void onToggleStatus(supplier)}
                        className="rounded-md border border-slate-500 px-2 py-1 text-xs font-semibold text-slate-100"
                      >
                        {supplier.status === "active" ? "Suspender" : "Activar"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
        <h2 className="text-xl font-bold text-white">Registrar nuevo proveedor</h2>
        <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={(event) => void onCreateSupplier(event)}>
          <label className="text-sm text-slate-200">
            Nombre
            <input
              required
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-200">
            País
            <select
              value={form.country}
              onChange={(event) => {
                const country = event.target.value as SupplierCountry;
                setForm((prev) => ({
                  ...prev,
                  country,
                  currency: country === "Colombia" ? "COP" : "USD",
                }));
              }}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            >
              <option value="Colombia">Colombia</option>
              <option value="USA">USA</option>
            </select>
          </label>

          <label className="text-sm text-slate-200">
            Categoría principal
            <select
              value={form.categories[0]}
              onChange={(event) => setForm((prev) => ({ ...prev, categories: [event.target.value] }))}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            >
              {VALID_CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm text-slate-200">
            Tarifa por unidad
            <input
              type="number"
              required
              min="0.01"
              step="0.01"
              value={form.rate_per_unit}
              onChange={(event) => setForm((prev) => ({ ...prev, rate_per_unit: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-200">
            Moneda
            <select
              value={form.currency}
              onChange={(event) => setForm((prev) => ({ ...prev, currency: event.target.value as SupplierCurrency }))}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            >
              <option value="COP">COP</option>
              <option value="USD">USD</option>
            </select>
          </label>

          <label className="text-sm text-slate-200">
            Estado
            <select
              value={form.status}
              onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value as SupplierStatus }))}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            >
              <option value="active">active</option>
              <option value="suspended">suspended</option>
            </select>
          </label>

          <label className="text-sm text-slate-200 sm:col-span-2">
            Contact email
            <input
              type="email"
              value={form.contact_email}
              onChange={(event) => setForm((prev) => ({ ...prev, contact_email: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-200 sm:col-span-2">
            Notas
            <textarea
              value={form.notes}
              onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))}
              className="mt-1 min-h-24 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
            />
          </label>

          <div className="sm:col-span-2">
            <button
              type="submit"
              className="rounded-xl bg-emerald-300 px-5 py-2.5 text-sm font-bold uppercase tracking-wide text-slate-900"
            >
              Crear proveedor
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
