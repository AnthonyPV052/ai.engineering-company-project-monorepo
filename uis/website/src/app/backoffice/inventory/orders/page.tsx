"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchOrders } from "@/lib/inventory";
import type { IngredientOrderEntry } from "@/lib/inventory";

// ============================================================================
// Página de historial de órdenes (solo lectura)
// ============================================================================

export default function OrdersHistoryPage() {
  const [orders, setOrders] = useState<IngredientOrderEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOrders();
      setOrders(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al cargar las órdenes.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOrders();
  }, [loadOrders]);

  // ======================================================================
  // Formateo de fecha
  // ======================================================================

  function formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString("es-CO", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  // ======================================================================
  // Icono de tipo de orden
  // ======================================================================

  function OrderTypeBadge({ type }: { type: "entry" | "exit" }) {
    if (type === "entry") {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-emerald-200">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
            <path d="M3 12h18M12 3l9 9-9 9" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Entrada
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-rose-200">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
          <path d="M3 12h18M12 21l9-9-9-9" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Salida
      </span>
    );
  }

  return (
    <section className="space-y-6">
      {/* Encabezado */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-orange-200">
          Brasaland · Inventario
        </p>
        <h1 className="text-2xl font-black text-white sm:text-3xl">
          Historial de órdenes
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Todas las entradas y salidas de inventario, ordenadas de más reciente a más antigua.
        </p>
      </div>

      {/* Estado: carga */}
      {loading && (
        <p className="py-12 text-center text-sm text-slate-400">Cargando órdenes…</p>
      )}

      {/* Estado: error */}
      {!loading && error && (
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/20 bg-rose-500/10 px-5 py-4">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mt-0.5 h-5 w-5 shrink-0 text-rose-300">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" strokeLinecap="round" />
          </svg>
          <div className="flex-1">
            <p className="text-sm font-medium text-rose-200">{error}</p>
          </div>
          <button
            type="button"
            onClick={() => void loadOrders()}
            className="shrink-0 text-xs font-semibold uppercase tracking-wider text-rose-300 underline underline-offset-2 transition hover:text-rose-100"
          >
            Reintentar
          </button>
        </div>
      )}

      {/* Estado: sin datos */}
      {!loading && !error && orders.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-800/50 px-5 py-12 text-center">
          <p className="text-sm text-slate-400">
            No hay órdenes registradas en el inventario.
          </p>
        </div>
      )}

      {/* Tabla de órdenes */}
      {!loading && !error && orders.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900 text-xs font-semibold uppercase tracking-wider text-slate-400">
                <th className="px-4 py-3 sm:px-5">Tipo</th>
                <th className="px-4 py-3 sm:px-5">Producto</th>
                <th className="px-4 py-3 sm:px-5">SKU</th>
                <th className="px-4 py-3 sm:px-5">Cantidad</th>
                <th className="px-4 py-3 sm:px-5">Detalle</th>
                <th className="px-4 py-3 sm:px-5">Creada por</th>
                <th className="px-4 py-3 sm:px-5">Fecha</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {orders.map((order) => (
                <tr
                  key={`${order.type}-${order.id}`}
                  className={`transition hover:bg-slate-800/40 ${
                    order.type === "entry"
                      ? "border-l-2 border-l-emerald-600/40"
                      : "border-l-2 border-l-rose-600/40"
                  }`}
                >
                  {/* Tipo */}
                  <td className="whitespace-nowrap px-4 py-3 sm:px-5">
                    <OrderTypeBadge type={order.type} />
                  </td>

                  {/* Producto */}
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-white sm:px-5">
                    {order.ingredient_name}
                  </td>

                  {/* SKU */}
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-400 sm:px-5">
                    {order.ingredient_sku}
                  </td>

                  {/* Cantidad */}
                  <td className="whitespace-nowrap px-4 py-3 sm:px-5">
                    <span className="font-semibold tabular-nums">
                      {order.quantity}
                    </span>
                  </td>

                  {/* Detalle (proveedor o motivo) */}
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400 sm:px-5">
                    {order.type === "entry" ? (
                      order.supplier_name ? (
                        <span className="text-emerald-300/80">
                          Proveedor: {order.supplier_name}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )
                    ) : (
                      <span
                        className={
                          order.reason === "consumption"
                            ? "text-amber-300/80"
                            : "text-rose-300/80"
                        }
                      >
                        {order.reason === "consumption" ? "Consumo" : "Merma"}
                      </span>
                    )}
                  </td>

                  {/* user_uuid (truncado) */}
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-500 sm:px-5" title={order.user_uuid}>
                    {order.user_uuid.length > 8
                      ? `${order.user_uuid.slice(0, 8)}…`
                      : order.user_uuid}
                  </td>

                  {/* Fecha */}
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400 sm:px-5">
                    {formatDate(order.created_at)}
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