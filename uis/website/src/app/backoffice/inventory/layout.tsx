import type { ReactNode } from "react";
import Link from "next/link";

const NAV_ITEMS = [
  { href: "/backoffice/inventory/products", label: "Productos" },
  { href: "/backoffice/inventory/orders", label: "Historial" },
  { href: "/backoffice/inventory/orders/inbound", label: "➕ Entrada" },
  { href: "/backoffice/inventory/orders/outbound", label: "➖ Salida" },
];

export default function InventoryLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      {/* Navegación secundaria */}
      <nav className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-3">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-lg px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
          >
            {item.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}