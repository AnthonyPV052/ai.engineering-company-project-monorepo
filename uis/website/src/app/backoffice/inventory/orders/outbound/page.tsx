"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { fetchProducts, fetchProductById, createOutboundOrder } from "@/lib/inventory";
import type { IngredientResponse } from "@/lib/inventory";
import { telemetry } from "@/services/telemetry";

// ============================================================================
// Mapa de ubicaciones (location_id 1‑14)
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
// Motivos de salida
// ============================================================================

const REASONS: { value: "consumption" | "waste"; label: string }[] = [
  { value: "consumption", label: "Consumo (preparación de platos)" },
  { value: "waste", label: "Merma (desperdicio o caducidad)" },
];

// ============================================================================
// Estado del formulario
// ============================================================================

interface FormState {
  productId: string;
  quantity: string;
  reason: "" | "consumption" | "waste";
  locationId: string;
}

const EMPTY_FORM: FormState = {
  productId: "",
  quantity: "",
  reason: "",
  locationId: "",
};

// ============================================================================
// Página
// ============================================================================

export default function OutboundOrderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [products, setProducts] = useState<IngredientResponse[]>([]);
  const [productsLoading, setProductsLoading] = useState(true);
  const [selectedProduct, setSelectedProduct] = useState<IngredientResponse | null>(null);
  const [stockLoading, setStockLoading] = useState(false);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quantityFieldError, setQuantityFieldError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Rastrear apertura del formulario de salida
  useEffect(() => {
    telemetry.track("inventory_outbound_form_opened", {
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

  // ======================================================================
  // Obtener stock actual cuando cambia la selección de producto
  // ======================================================================

  useEffect(() => {
    let cancelled = false;

    const productId = Number(form.productId);
    if (!productId) {
      setSelectedProduct(null);
      return;
    }

    setStockLoading(true);

    async function refreshStock() {
      try {
        const product = await fetchProductById(productId);
        if (!cancelled) {
          setSelectedProduct(product);
        }
      } catch {
        if (!cancelled) {
          setSelectedProduct(null);
        }
      } finally {
        if (!cancelled) setStockLoading(false);
      }
    }

    void refreshStock();

    return () => {
      cancelled = true;
    };
  }, [form.productId]);

  // ======================================================================
  // Advertencia de stock insuficiente (validación client‑side)
  // ======================================================================

  const quantityExceedsStock = useMemo<boolean>(() => {
    if (!selectedProduct || !form.quantity) return false;
    const qty = Number(form.quantity);
    return !Number.isNaN(qty) && qty > selectedProduct.current_stock;
  }, [selectedProduct, form.quantity]);

  // Actualizar campo individual
  function updateField<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError(null);
    setSuccess(null);
    setQuantityFieldError(null);
  }

  // Enviar formulario
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setSuccess(null);
      setQuantityFieldError(null);

      // Validaciones del lado del cliente
      const productId = Number(form.productId);
      if (!productId || !products.find((p) => p.id === productId)) {
        setError("Selecciona un producto de la lista.");
        return;
      }

      const quantity = Number(form.quantity);
      if (!quantity || quantity <= 0) {
        setQuantityFieldError("La cantidad debe ser un número positivo.");
        return;
      }

      if (form.reason !== "consumption" && form.reason !== "waste") {
        setError("Selecciona un motivo de salida.");
        return;
      }

      const locationId = Number(form.locationId);
      if (!locationId || locationId < 1 || locationId > 14) {
        setError("Selecciona una ubicación válida.");
        return;
      }

      setSubmitting(true);
      try {
        await createOutboundOrder({
          ingredient_id: productId,
          quantity,
          reason: form.reason,
          location_id: locationId,
        });
        // Rastrear evento de negocio según el motivo
        const product = products.find((p) => p.id === productId);
        const eventType = form.reason === "waste" ? "stock_waste_registered" : "outbound_order_created";
        const wasteReason = form.reason === "waste" ? "kitchen_error" : undefined;
        telemetry.track(eventType, {
          location_id: locationId,
          country: product?.country ?? "",
          product_id: productId,
          product_category: product?.category ?? "",
          quantity,
          unit: product?.unit ?? "",
          currency: locationId >= 11 ? "USD" : "COP",
          ...(wasteReason ? { reason: wasteReason } : {}),
        });
        // Si el formulario muestra advertencia de stock pero el usuario envía igualmente
        if (quantityExceedsStock) {
          telemetry.track("outbound_stock_warning_triggered", {
            product_id: productId,
            requested_quantity: quantity,
            available_stock: selectedProduct?.current_stock ?? 0,
            location_id: locationId,
          });
        }
        setForm(EMPTY_FORM);
        setSelectedProduct(null);
        setSuccess(
          `Salida registrada correctamente: ${quantity} unidades de ${products.find((p) => p.id === productId)?.name ?? "producto"}.`,
        );
      } catch (caught) {
        const message =
          caught instanceof Error ? caught.message : "Error al registrar la salida.";

        // Si el error viene de la API por stock insuficiente, se muestra
        // inline junto al campo de cantidad
        if (
          message.toLowerCase().includes("stock") &&
          message.toLowerCase().includes("insufficient")
        ) {
          setQuantityFieldError(message);
        } else {
          setError(message);
        }
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
          Orden de salida
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Registra un consumo o merma de ingrediente.
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

      {/* Mensaje de error global */}
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
        {/* ================================================================ */}
        {/* Producto */}
        {/* ================================================================ */}
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

        {/* ================================================================ */}
        {/* Stock actual del producto seleccionado */}
        {/* ================================================================ */}
        {form.productId && (
          <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3">
            {stockLoading ? (
              <p className="text-xs text-slate-500">Consultando stock…</p>
            ) : selectedProduct ? (
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Stock actual
                </span>
                <span
                  className={`text-sm font-bold ${
                    selectedProduct.current_stock <= 0
                      ? "text-rose-400"
                      : selectedProduct.current_stock <= 10
                        ? "text-amber-400"
                        : selectedProduct.current_stock <= 50
                          ? "text-sky-400"
                          : "text-emerald-400"
                  }`}
                >
                  {selectedProduct.current_stock}{" "}
                  <span className="text-xs font-normal text-slate-400">
                    {selectedProduct.unit}
                  </span>
                </span>
              </div>
            ) : (
              <p className="text-xs text-rose-400">No se pudo obtener el stock.</p>
            )}
          </div>
        )}

        {/* ================================================================ */}
        {/* Cantidad */}
        {/* ================================================================ */}
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
            placeholder="p. ej. 10"
            value={form.quantity}
            onChange={(e) => updateField("quantity", e.target.value)}
            required
            className={`w-full rounded-lg border px-4 py-2.5 text-sm text-slate-100 transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 ${
              quantityFieldError
                ? "border-rose-500 bg-rose-900/20"
                : quantityExceedsStock
                  ? "border-amber-500 bg-amber-900/20"
                  : "border-slate-700 bg-slate-800"
            }`}
          />
          {/* Advertencia client‑side: cantidad supera el stock */}
          {quantityExceedsStock && !quantityFieldError && (
            <p className="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-amber-300">
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4 shrink-0"
              >
                <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
                <circle cx="12" cy="12" r="10" />
              </svg>
              La cantidad ingresada ({form.quantity}) supera el stock disponible (
              {selectedProduct?.current_stock ?? "?"} {selectedProduct?.unit ?? ""}
              ). La API rechazará la operación si el stock es insuficiente.
            </p>
          )}
          {/* Error inline de la API por stock insuficiente */}
          {quantityFieldError && (
            <p className="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-rose-300">
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4 shrink-0"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="M12 8v4M12 16h.01" strokeLinecap="round" />
              </svg>
              {quantityFieldError}
            </p>
          )}
        </div>

        {/* ================================================================ */}
        {/* Motivo */}
        {/* ================================================================ */}
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Motivo *
          </legend>
          <div className="space-y-2">
            {REASONS.map((r) => (
              <label
                key={r.value}
                className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-2.5 text-sm transition ${
                  form.reason === r.value
                    ? "border-orange-500/50 bg-orange-500/10 text-orange-100"
                    : "border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500"
                }`}
              >
                <input
                  type="radio"
                  name="reason"
                  value={r.value}
                  checked={form.reason === r.value}
                  onChange={(e) =>
                    updateField("reason", e.target.value as FormState["reason"])
                  }
                  className="h-4 w-4 accent-orange-400"
                />
                {r.label}
              </label>
            ))}
          </div>
        </fieldset>

        {/* ================================================================ */}
        {/* Ubicación */}
        {/* ================================================================ */}
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

        {/* ================================================================ */}
        {/* Botones */}
        {/* ================================================================ */}
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
            className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-6 py-2.5 text-xs font-bold uppercase tracking-wider text-white transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-40"
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
              "Registrar salida"
            )}
          </button>
        </div>
      </form>
    </section>
  );
}