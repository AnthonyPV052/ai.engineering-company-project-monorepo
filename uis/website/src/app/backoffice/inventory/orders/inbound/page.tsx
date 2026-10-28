"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { fetchProducts, createInboundOrder } from "@/lib/inventory";
import type { IngredientResponse } from "@/lib/inventory";
import { telemetry } from "@/services/telemetry";

// ============================================================================
// Mapa de ubicaciones (location_id 1‑14)
// Los ids coinciden con la validación del backend (ge=1, le=14).
// ============================================================================

const LOCATIONS: { id: number; name: string }[] = [
  { id: 1, name: "Central (Medellín / Miami)" },
  { id: 2, name: "Medellín Centro" },
  { id: 3, name: "Medellín Laureles" },
  { id: 4, name: "Medellín Envigado" },
  { id: 5, name: "Medellín Bello" },
  { id: 6, name: "Medellín Itagüí" },
  { id: 7, name: "Bogotá Chapinero" },
  { id: 8, name: "Bogotá Usaquén" },
  { id: 9, name: "Cali Granada" },
  { id: 10, name: "Barranquilla Norte" },
  { id: 11, name: "Miami Doral" },
  { id: 12, name: "Miami Hialeah" },
  { id: 13, name: "Miami Kendall" },
  { id: 14, name: "Orlando International Drive" },
];

// ============================================================================
// Estado del formulario
// ============================================================================

interface FormState {
  productId: string;
  quantity: string;
  supplierName: string;
  locationId: string;
}

const EMPTY_FORM: FormState = {
  productId: "",
  quantity: "",
  supplierName: "",
  locationId: "",
};

// ============================================================================
// Página
// ============================================================================

export default function InboundOrderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [products, setProducts] = useState<IngredientResponse[]>([]);
  const [productsLoading, setProductsLoading] = useState(true);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Rastrear apertura del formulario de entrada
  useEffect(() => {
    telemetry.track("inventory_inbound_form_opened", {
      location_id_preselected: "",
      product_id_preselected: searchParams.get("productId") ?? "",
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Cargar lista de productos al montar y pre‑seleccionar si viene ?productId=
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setProductsLoading(true);
      try {
        const data = await fetchProducts();
        if (cancelled) return;
        setProducts(data);

        const preselectedId = searchParams.get("productId");
        if (preselectedId && data.some((p) => p.id === Number(preselectedId))) {
          setForm((prev) => ({ ...prev, productId: preselectedId }));
        }
      } catch (caught) {
        if (!cancelled) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Error al cargar los productos.",
          );
        }
      } finally {
        if (!cancelled) setProductsLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  // Actualizar campo individual
  function updateField<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError(null);
    setSuccess(null);
  }

  // Enviar formulario
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setSuccess(null);

      // Validaciones del lado del cliente
      const productId = Number(form.productId);
      if (!productId || !products.find((p) => p.id === productId)) {
        setError("Selecciona un producto de la lista.");
        return;
      }

      const quantity = Number(form.quantity);
      if (!quantity || quantity <= 0) {
        setError("La cantidad debe ser un número positivo.");
        return;
      }

      if (!form.supplierName.trim()) {
        setError("El nombre del proveedor es obligatorio.");
        return;
      }

      const locationId = Number(form.locationId);
      if (!locationId || locationId < 1 || locationId > 14) {
        setError("Selecciona una ubicación válida.");
        return;
      }

      setSubmitting(true);
      try {
        await createInboundOrder({
          ingredient_id: productId,
          quantity,
          supplier_name: form.supplierName.trim(),
          location_id: locationId,
        });
        // Rastrear evento de negocio: inbound_order_created
        const product = products.find((p) => p.id === productId);
        telemetry.track("inbound_order_created", {
          location_id: locationId,
          country: product?.country ?? "",
          product_id: productId,
          product_category: product?.category ?? "",
          quantity,
          unit: product?.unit ?? "",
          currency: locationId >= 11 ? "USD" : "COP",
          supplier_name: form.supplierName.trim(),
        });
        setForm(EMPTY_FORM);
        setSuccess(
          `Entrada registrada correctamente: ${quantity} unidades de ${products.find((p) => p.id === productId)?.name ?? "producto"}.`,
        );
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : "Error al registrar la entrada.",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [form, products],
  );

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      {/* Encabezado */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-orange-200">
          Brasaland · Inventario
        </p>
        <h1 className="text-2xl font-black text-white sm:text-3xl">
          Orden de entrada
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Registra una entrega de ingrediente recibida de un proveedor.
        </p>
      </div>

      {/* Mensaje de éxito */}
      {success && (
        <div className="flex items-start gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-4">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300"
          >
            <path d="M22 11.1V12a10 10 0 1 1-6-9.2" strokeLinecap="round" />
            <path d="M16 6 9 13l-3-3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="flex-1">
            <p className="text-sm font-medium text-emerald-200">{success}</p>
          </div>
          <button
            type="button"
            onClick={() => setSuccess(null)}
            className="shrink-0 text-emerald-300/60 transition hover:text-emerald-200"
            aria-label="Descartar mensaje"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
              <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      {/* Mensaje de error */}
      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/20 bg-rose-500/10 px-5 py-4">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="mt-0.5 h-5 w-5 shrink-0 text-rose-300"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" strokeLinecap="round" />
          </svg>
          <div className="flex-1">
            <p className="text-sm font-medium text-rose-200">{error}</p>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="shrink-0 text-rose-300/60 transition hover:text-rose-200"
            aria-label="Descartar mensaje"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
              <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      {/* Formulario */}
      <form
        onSubmit={handleSubmit}
        className="space-y-5 rounded-xl border border-slate-800 bg-slate-900/50 p-6"
      >
        {/* Producto */}
        <div>
          <label
            htmlFor="productId"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400"
          >
            Producto *
          </label>
          {productsLoading ? (
            <p className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-slate-500">
              Cargando productos…
            </p>
          ) : (
            <select
              id="productId"
              value={form.productId}
              onChange={(e) => updateField("productId", e.target.value)}
              required
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-slate-100 transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
            >
              <option value="">— Selecciona un producto —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.sku}) — {p.country === "CO" ? "🇨🇴" : "🇺🇸"}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Cantidad */}
        <div>
          <label
            htmlFor="quantity"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400"
          >
            Cantidad *
          </label>
          <input
            id="quantity"
            type="number"
            step="any"
            min="0.01"
            placeholder="p. ej. 25.5"
            value={form.quantity}
            onChange={(e) => updateField("quantity", e.target.value)}
            required
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-slate-100 transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
          />
        </div>

        {/* Proveedor */}
        <div>
          <label
            htmlFor="supplierName"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400"
          >
            Proveedor *
          </label>
          <input
            id="supplierName"
            type="text"
            placeholder="p. ej. Carnes del Valle S.A."
            value={form.supplierName}
            onChange={(e) => updateField("supplierName", e.target.value)}
            required
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-slate-100 transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
          />
        </div>

        {/* Ubicación */}
        <div>
          <label
            htmlFor="locationId"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400"
          >
            Ubicación (local) *
          </label>
          <select
            id="locationId"
            value={form.locationId}
            onChange={(e) => updateField("locationId", e.target.value)}
            required
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-slate-100 transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
          >
            <option value="">— Selecciona un local —</option>
            {LOCATIONS.map((loc) => (
              <option key={loc.id} value={loc.id}>
                {loc.name}
              </option>
            ))}
          </select>
        </div>

        {/* Botón de envío */}
        <div className="flex items-center justify-between pt-2">
          <button
            type="button"
            onClick={() => router.back()}
            className="rounded-lg border border-slate-700 px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
          >
            Volver
          </button>
          <button
            type="submit"
            disabled={submitting || productsLoading}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-6 py-2.5 text-xs font-bold uppercase tracking-wider text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? (
              <>
                <svg
                  aria-hidden="true"
                  className="h-4 w-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    className="opacity-25"
                  />
                  <path
                    fill="currentColor"
                    className="opacity-75"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Registrando…
              </>
            ) : (
              "Registrar entrada"
            )}
          </button>
        </div>
      </form>
    </section>
  );
}