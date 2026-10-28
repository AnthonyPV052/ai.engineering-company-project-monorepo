"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { fetchProducts } from "@/lib/inventory";
import type { IngredientResponse } from "@/lib/inventory";

// ============================================================================
// Umbrales de nivel de stock
//
// Los valores se interpretan en la unidad propia de cada ingrediente (kg, L,
// unidad). Se definen aquí porque el backend no almacena un "stock máximo"
// ni un "punto de reorden";
//
//   0             → Agotado       (rojo)
//   1 – 10        → Bajo          (ámbar)
//   11 – 50       → Moderado      (azul)
//   > 50          → Saludable     (verde)
//
// Estos umbrales son razonables para un restaurante con volumen diario:
// carnes (kg), salsas (L) y empaques (unidades). Pueden ajustarse según
// la operación de cada sede.
// ============================================================================

type StockLevel = "agotado" | "bajo" | "moderado" | "saludable";

function computeStockLevel(stock: number): StockLevel {
  if (stock <= 0) return "agotado";
  if (stock <= 10) return "bajo";
  if (stock <= 50) return "moderado";
  return "saludable";
}

const STOCK_LEVEL_CONFIG: Record<StockLevel, { label: string; bg: string; text: string; dot: string }> = {
  agotado: {
    label: "Agotado",
    bg: "bg-rose-500/10",
    text: "text-rose-200",
    dot: "bg-rose-400",
  },
  bajo: {
    label: "Bajo",
    bg: "bg-amber-500/10",
    text: "text-amber-200",
    dot: "bg-amber-400",
  },
  moderado: {
    label: "Moderado",
    bg: "bg-sky-500/10",
    text: "text-sky-200",
    dot: "bg-sky-400",
  },
  saludable: {
    label: "Saludable",
    bg: "bg-emerald-500/10",
    text: "text-emerald-200",
    dot: "bg-emerald-400",
  },
};

function StockBadge({ stock }: { stock: number }) {
  const level = computeStockLevel(stock);
  const cfg = STOCK_LEVEL_CONFIG[level];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${cfg.bg} ${cfg.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} aria-hidden="true" />
      {stock} · {cfg.label}
    </span>
  );
}

// ============================================================================
// Página principal
// ============================================================================

export default function InventoryProductsPage() {
  const [products, setProducts] = useState<IngredientResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [countryFilter, setCountryFilter] = useState<string>("");

  const loadProducts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchProducts(countryFilter || undefined);
      setProducts(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al cargar los productos.");
    } finally {
      setLoading(false);
    }
  }, [countryFilter]);

  useEffect(() => {
    void loadProducts();
  }, [loadProducts]);

  return (
    <section className="space-y-6">
      {/* Encabezado */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-orange-200">
            Brasaland · Inventario
          </p>
          <h1 className="text-2xl font-black text-white sm:text-3xl">Productos</h1>
        </div>
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          País
        </label>
        <select
          value={countryFilter}
          onChange={(e) => setCountryFilter(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
        >
          <option value="">Todos</option>
          <option value="CO">Colombia</option>
          <option value="US">Estados Unidos</option>
        </select>
      </div>

      {/* Estado: carga */}
      {loading && (
        <p className="py-12 text-center text-sm text-slate-400">Cargando productos…</p>
      )}

      {/* Estado: error */}
      {!loading && error && (
        <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-5 py-4">
          <p className="text-sm font-medium text-rose-200">{error}</p>
          <button
            type="button"
            onClick={() => void loadProducts()}
            className="mt-2 text-xs font-semibold uppercase tracking-wider text-rose-300 underline underline-offset-2 transition hover:text-rose-100"
          >
            Reintentar
          </button>
        </div>
      )}

      {/* Estado: sin datos */}
      {!loading && !error && products.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-12 text-center">
          <p className="text-sm text-slate-400">
            {countryFilter
              ? `No hay productos para el país «${countryFilter}».`
              : "No hay productos registrados en el inventario."}
          </p>
        </div>
      )}

      {/* Tabla de productos */}
      {!loading && !error && products.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900 text-xs font-semibold uppercase tracking-wider text-slate-400">
                <th className="px-4 py-3 sm:px-5">SKU</th>
                <th className="px-4 py-3 sm:px-5">Nombre</th>
                <th className="px-4 py-3 sm:px-5">Unidad</th>
                <th className="px-4 py-3 sm:px-5">Categoría</th>
                <th className="px-4 py-3 sm:px-5">País</th>
                <th className="px-4 py-3 sm:px-5">Stock actual</th>
                <th className="px-4 py-3 sm:px-5">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {products.map((product) => (
                <tr
                  key={product.id}
                  className="transition hover:bg-slate-800/40"
                >
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-300 sm:px-5">
                    {product.sku}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-white sm:px-5">
                    {product.name}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-300 sm:px-5">
                    {product.unit}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-300 sm:px-5">
                    <span className="rounded-md bg-slate-700/60 px-2 py-0.5 text-xs text-slate-300">
                      {product.category}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 sm:px-5">
                    <span className="font-semibold text-slate-300">
                      {product.country === "CO" ? "🇨🇴 CO" : "🇺🇸 US"}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 sm:px-5">
                    <StockBadge stock={product.current_stock} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 sm:px-5">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/backoffice/inventory/orders/inbound?productId=${product.id}`}
                        className="inline-flex items-center gap-1 rounded-lg border border-emerald-600/50 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-200 transition hover:border-emerald-400 hover:bg-emerald-500/10"
                      >
                        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                          <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                        </svg>
                        Entrada
                      </Link>
                      <Link
                        href={`/backoffice/inventory/orders/outbound?productId=${product.id}`}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-600/50 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-rose-200 transition hover:border-rose-400 hover:bg-rose-500/10"
                      >
                        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                          <path d="M5 12h14" strokeLinecap="round" />
                        </svg>
                        Salida
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}