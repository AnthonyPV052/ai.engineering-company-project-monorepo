"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const navigationItems = [
  {
    label: "Gestor de incidencias",
    href: "/backoffice/incidents",
    icon: <><path d="M12 8v4l2.5 1.5" /><circle cx="12" cy="12" r="9" /></>,
  },
  {
    label: "Directorio de proveedores",
    href: "/backoffice/suppliers",
    icon: <><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6M9 9h.01M15 9h.01M9 12h.01M15 12h.01" /></>,
  },
  {
    label: "Inventario",
    href: "/backoffice/inventory/products",
    icon: <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="M3 12l9 5 9-5M3 16l9 5 9-5M12 13v8" /></>,
  },
  {
    label: "Historial de órdenes",
    href: "/backoffice/inventory/orders",
    icon: <><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></>,
  },
  {
    label: "Reporte semanal",
    href: "/backoffice/reporting",
    icon: <><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-5 5" /></>,
  },
  {
    label: "Reporte de telemetría",
    href: "/backoffice/telemetry",
    icon: <><path d="M3 12h4l3-8 4 16 3-8h4" /></>,
  },
  {
    label: "Agente de soporte",
    href: "/backoffice/knowledge",
    icon: <><path d="M12 18h.01M9.09 9a3 3 0 0 1 5.82 1c0 2-3 3-3 3" /><circle cx="12" cy="12" r="9" /></>,
  },
];

export default function BackofficeSidebar() {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);

  return (
    <aside
      className={`sticky top-0 z-20 flex h-[calc(100vh-73px)] shrink-0 flex-col border-r border-slate-800 bg-slate-950/95 py-4 transition-[width] duration-200 ${expanded ? "w-64" : "w-[4.5rem]"}`}
    >
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        aria-label={expanded ? "Contraer navegación" : "Expandir navegación"}
        aria-expanded={expanded}
        className={`mx-2 mb-5 inline-flex h-10 items-center rounded-lg border border-slate-700 text-slate-300 transition hover:border-orange-300/70 hover:bg-slate-900 hover:text-orange-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 ${expanded ? "justify-start gap-3 px-3" : "justify-center"}`}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5 shrink-0">
          <path d={expanded ? "M4 6h16M4 12h16M4 18h16" : "M4 6h16M4 12h10M4 18h16"} strokeLinecap="round" />
        </svg>
        {expanded && <span className="text-sm font-semibold">Navegación</span>}
      </button>

      <nav aria-label="Navegación del BackOffice" className="flex-1">
        <ul className="space-y-1 px-2">
          {navigationItems.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  title={expanded ? undefined : item.label}
                  aria-label={item.label}
                  aria-current={active ? "page" : undefined}
                  className={`flex h-11 items-center rounded-lg text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 ${expanded ? "gap-3 px-3" : "justify-center px-0"} ${active ? "bg-orange-300/10 text-orange-200 ring-1 ring-inset ring-orange-300/30" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"}`}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5 shrink-0">
                    {item.icon}
                  </svg>
                  {expanded && <span className="truncate">{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className={`mx-2 mt-4 border-t border-slate-800 pt-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600 ${expanded ? "px-3" : "text-center"}`}>
        {expanded ? "Brasaland · Operaciones" : "B"}
      </div>
    </aside>
  );
}
