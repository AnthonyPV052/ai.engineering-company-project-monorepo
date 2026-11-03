"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import dynamic from "next/dynamic";
import { getStoredToken, clearToken } from "@/lib/auth";
import {
  useRfpSse,
  type RfpTicketCreatedEvent,
  type RfpNotificationItem,
} from "@/lib/sseRfp";
import RFPDetailPanel from "./RFPDetailPanel";

/* Usamos /api para que Next.js rewrites (next.config.ts) enruten al backend.
   API_UPSTREAM_URL=http://172.17.0.1:8020 definido en docker-compose.yml.
   Nunca apuntar directo a 127.0.0.1:8020 dentro del contenedor. */
const API_BASE = "/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TicketStatus =
  | "analizando"
  | "descartado"
  | "analisis_completo"
  | "generando_borrador"
  | "en_evaluacion"
  | "needs_human_review"
  | "esperando_aprobacion"
  | "terminado";

interface TicketListItem {
  ticket_id: string;
  status: TicketStatus;
  client_name: string | null;
  service_type: string | null;
  departments_count: number;
  created_at: string | null;
  updated_at: string | null;
}

interface DepartmentSection {
  id: number | null;
  department_id: string;
  key_aspects: string | null;
  approval_status: string;
}

interface TicketMetadata {
  client_name: string | null;
  location: string | null;
  service_type: string | null;
  scope: string | null;
  deadline: string | null;
  budget_range: string | null;
  annual_estimated_usd: number | null;
  departments_needed: string[];
  flesch_reading_ease: number | null;
  flesch_kincaid_grade: number | null;
  gunning_fog: number | null;
  word_count: number | null;
  classifier_confidence: number | null;
  classification_reason: string | null;
}

interface TicketEvent {
  event: string;
  detail: string | null;
  created_at: string | null;
}

interface TicketDetail {
  ticket_id: string;
  status: TicketStatus;
  raw_pdf_path: string;
  handoff_payload: string | null;
  created_at: string | null;
  updated_at: string | null;
  metadata: TicketMetadata | null;
  department_sections: DepartmentSection[];
  events: TicketEvent[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<TicketStatus, string> = {
  analizando: "Analizando",
  descartado: "Descartado",
  analisis_completo: "Análisis Completo",
  generando_borrador: "Generando Borrador",
  en_evaluacion: "En Evaluación",
  needs_human_review: "Requiere Revisión",
  esperando_aprobacion: "Esperando Aprobación",
  terminado: "Terminado",
};

const STATUS_TONES: Record<TicketStatus, string> = {
  analizando: "bg-amber-300/10 text-amber-100 border-amber-300/40",
  descartado: "bg-slate-300/10 text-slate-200 border-slate-400/40",
  analisis_completo: "bg-emerald-300/10 text-emerald-100 border-emerald-300/40",
  generando_borrador: "bg-cyan-300/10 text-cyan-100 border-cyan-300/40",
  en_evaluacion: "bg-violet-300/10 text-violet-100 border-violet-300/40",
  needs_human_review: "bg-rose-300/10 text-rose-100 border-rose-300/40",
  esperando_aprobacion: "bg-orange-300/10 text-orange-100 border-orange-300/40",
  terminado: "bg-emerald-300/10 text-emerald-100 border-emerald-300/40",
};



async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (response.status === 401) {
    clearToken();
    throw new Error("Tu sesión ha caducado. Vuelve a iniciar sesión.");
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string; error?: string };
      detail = payload.detail ?? payload.error ?? detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

function StatusBadge({ status }: { status: TicketStatus | string }) {
  const label = STATUS_LABELS[status as TicketStatus] ?? status;
  const tone = STATUS_TONES[status as TicketStatus] ?? "bg-slate-300/10 text-slate-200 border-slate-400/40";
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-bold ${tone}`}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Real-time (SSE) helpers
// ---------------------------------------------------------------------------

function formatRfpTimestamp(epochMs: number): string {
  return new Date(epochMs).toLocaleString("es-CO");
}

function ConnectionStateBadge({
  state,
  reconnectAttempts,
}: {
  state: "connecting" | "connected" | "reconnecting" | "closed";
  reconnectAttempts: number;
}) {
  const base =
    "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold";
  if (state === "connected") {
    return (
      <span className={`${base} border-emerald-300/40 bg-emerald-300/10 text-emerald-100`}>
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
        </span>
        En vivo
      </span>
    );
  }
  if (state === "reconnecting") {
    return (
      <span className={`${base} border-amber-300/40 bg-amber-300/10 text-amber-100`}>
        <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Reconectando{reconnectAttempts > 0 ? ` (intento ${reconnectAttempts})` : ""}
      </span>
    );
  }
  if (state === "connecting") {
    return (
      <span className={`${base} border-slate-500/40 bg-slate-500/10 text-slate-200`}>
        Conectando…
      </span>
    );
  }
  return (
    <span className={`${base} border-rose-300/40 bg-rose-300/10 text-rose-100`}>
      Sin conexión en tiempo real
    </span>
  );
}

function RealTimeNotificationBanner({
  notifications,
  onViewTicket,
  onDismiss,
  onRestart,
}: {
  notifications: RfpNotificationItem[];
  onViewTicket: (ticketId: string) => void;
  onDismiss: () => void;
  onRestart: () => void;
}) {
  if (notifications.length === 0) return null;

  const total = notifications.length;
  return (
    <section className="rounded-2xl border border-amber-300/30 bg-gradient-to-br from-amber-950/60 via-slate-900 to-slate-900 p-5 shadow-lg shadow-amber-950/30">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className="inline-flex h-2.5 w-2.5 animate-pulse rounded-full bg-amber-400"
            aria-hidden="true"
          />
          <h2 className="text-sm font-bold uppercase tracking-[0.14em] text-amber-200">
            Llegada de RFP en tiempo real
          </h2>
          <span className="rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-xs font-bold text-amber-100">
            {total} {total === 1 ? "nuevo" : "nuevos"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-slate-600 bg-slate-800/70 px-2.5 py-1 text-xs font-semibold text-slate-200 transition hover:bg-slate-700"
          >
            Descartar avisos
          </button>
          <button
            type="button"
            onClick={onRestart}
            className="rounded-md border border-slate-600 bg-slate-800/70 px-2.5 py-1 text-xs font-semibold text-slate-200 transition hover:bg-slate-700"
          >
            Reconectar
          </button>
        </div>
      </div>

      <ul className="space-y-2">
        {notifications.map((n) => (
          <li
            key={n.ticket_id}
            className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-amber-300/20 bg-slate-900/70 px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-amber-50">
                {n.client_name ?? "Cliente sin identificar"}
              </p>
              <p className="text-xs text-slate-400">
                {n.service_type ?? "Servicio sin clasificar"} ·{" "}
                {formatRfpTimestamp(n.received_at)}
              </p>
            </div>
            <span className="font-mono text-xs text-slate-400">
              {n.ticket_id.slice(0, 8)}…
            </span>
            <StatusBadge status={n.status} />
            <button
              type="button"
              onClick={() => onViewTicket(n.ticket_id)}
              className="rounded-md bg-amber-500 px-3 py-1 text-xs font-semibold text-slate-950 transition hover:bg-amber-400"
            >
              Ver detalle
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function RFPPage() {
  const [tickets, setTickets] = useState<TicketListItem[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cache de ticket ids ya presentes en la lista → la UI no pinta un ticket
  // dos veces si el servidor re-emite un evento (replay tras reconexión).
  const knownTicketIds = useRef<Set<string>>(new Set());

  // Fetch ticket list
  const fetchTickets = useCallback(async () => {
    try {
      const data = await apiFetch<TicketListItem[]>("/api/rfp/tickets");
      setTickets(data);
      // Mantén el cache de ids en sync con la lista para la dedup SSE.
      const ids = new Set<string>(data.map((t) => t.ticket_id));
      knownTicketIds.current = ids;
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al cargar tickets");
    } finally {
      setLoading(false);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Real-time: consume GET /api/rfp/events/stream vía fetch + ReadableStream.
  // La reconexión con backoff reedita el refetch de la lista como red de
  // seguridad; el servidor re-emite los tickets perdidos con Last-Event-ID.
  // ---------------------------------------------------------------------------
  const {
    connectionState,
    reconnectAttempts,
    notifications,
    clearNotifications,
    restart,
  } = useRfpSse({
    knownTicketIds,
    onReconnected: () => {
      void fetchTickets();
    },
    onNewTicket: (_event: RfpTicketCreatedEvent) => {
      // Un ticket llegó en tiempo real (p.ej. subido desde otro navegador).
      // Refresca la lista para que la fila aparezca sin recargar la página
      // (el banner lo gestiona el hook, aquí aseguramos la tabla).
      void fetchTickets();
    },
  });

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  // Poll selected ticket if it's in progress
  useEffect(() => {
    if (selectedTicket && selectedTicket.status === "analizando") {
      pollingRef.current = setInterval(async () => {
        try {
          const updated = await apiFetch<TicketDetail>(
            `/api/rfp/tickets/${selectedTicket.ticket_id}`
          );
          setSelectedTicket(updated);
          // Also refresh list
          const list = await apiFetch<TicketListItem[]>("/api/rfp/tickets");
          setTickets(list);

          if (updated.status !== "analizando") {
            if (pollingRef.current) clearInterval(pollingRef.current);
          }
        } catch {
          // Ignore polling errors
        }
      }, 3000);
    }

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [selectedTicket?.ticket_id, selectedTicket?.status]);

  // Upload handler
  const onUpload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const file = formData.get("file") as File;

    if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
      setError("Selecciona un archivo PDF.");
      return;
    }

    setUploading(true);
    setError(null);
    setUploadMessage(null);

    try {
      const uploadForm = new FormData();
      uploadForm.append("file", file);

      const uploadHeaders: Record<string, string> = {};
      const token = getStoredToken();
      if (token) {
        uploadHeaders["Authorization"] = `Bearer ${token}`;
      }

      const response = await fetch(`${API_BASE}/api/rfp/upload`, {
        method: "POST",
        body: uploadForm,
        headers: uploadHeaders,
      });

      if (response.status === 401) {
        clearToken();
        throw new Error("Tu sesión ha caducado. Vuelve a iniciar sesión.");
      }

      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new Error(payload.detail ?? `HTTP ${response.status}`);
      }

      const result = (await response.json()) as {
        ticket_id: string;
        status: string;
        message: string;
      };
      setUploadMessage(`Ticket creado: ${result.ticket_id}`);
      (event.target as HTMLFormElement).reset();
      await fetchTickets();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al subir archivo");
    } finally {
      setUploading(false);
    }
  };

  // View ticket detail
  const onViewTicket = async (ticketId: string) => {
    try {
      const detail = await apiFetch<TicketDetail>(`/api/rfp/tickets/${ticketId}`);
      setSelectedTicket(detail);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al cargar ticket");
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <section className="relative overflow-hidden rounded-3xl border border-orange-300/20 bg-gradient-to-br from-slate-900 via-orange-950 to-amber-900 p-8 sm:p-12">
        <div className="absolute -right-20 -top-10 h-64 w-64 rounded-full bg-orange-400/20 blur-3xl" aria-hidden="true" />
        <div className="absolute -bottom-16 -left-16 h-64 w-64 rounded-full bg-amber-400/20 blur-3xl" aria-hidden="true" />
        <div className="relative z-10 space-y-4">
          <p className="inline-flex rounded-full border border-orange-200/40 bg-orange-200/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-orange-100">
            Recepción de RFPs
          </p>
          <h1 className="text-3xl font-black leading-tight text-white sm:text-4xl">
            Recepción y Análisis de Solicitudes de Propuesta
          </h1>
          <p className="max-w-2xl text-base text-slate-200">
            Sube una RFP en PDF para que el sistema la clasifique, extraiga metadatos
            y la distribuya a los departamentos correspondientes para su análisis.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <ConnectionStateBadge
              state={connectionState}
              reconnectAttempts={reconnectAttempts}
            />
            <span className="text-xs text-slate-300">
              Los nuevos tickets aparecen en tiempo real, sin recargar la página.
            </span>
          </div>
        </div>
      </section>

      {/* Real-time notifications (SSE) */}
      <RealTimeNotificationBanner
        notifications={notifications}
        onViewTicket={(id) => void onViewTicket(id)}
        onDismiss={clearNotifications}
        onRestart={restart}
      />

      {/* Upload Form */}
      <section className="rounded-2xl border border-orange-300/25 bg-slate-900 p-6">
        <h2 className="mb-4 text-lg font-bold text-white">Subir nueva RFP</h2>
        <form onSubmit={onUpload} className="flex items-end gap-4">
          <div className="flex-1">
            <label htmlFor="rfp-file" className="mb-1 block text-sm font-medium text-slate-300">
              Archivo PDF
            </label>
            <input
              id="rfp-file"
              name="file"
              type="file"
              accept=".pdf"
              required
              className="block w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 file:mr-3 file:rounded file:border-0 file:bg-orange-600 file:px-3 file:py-1 file:text-xs file:font-semibold file:text-white hover:file:bg-orange-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
            />
          </div>
          <button
            type="submit"
            disabled={uploading}
            className="flex h-10 items-center gap-2 rounded-lg bg-orange-600 px-5 text-sm font-semibold text-white transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
          >
            {uploading ? (
              <>
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Subiendo…
              </>
            ) : (
              "Subir RFP"
            )}
          </button>
        </form>
        {uploadMessage && (
          <p className="mt-3 text-sm text-emerald-300">{uploadMessage}</p>
        )}
        {error && (
          <p className="mt-3 text-sm text-rose-300">{error}</p>
        )}
      </section>

      {/* Ticket List */}
      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-4 text-lg font-bold text-white">Tickets de RFP</h2>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-sm text-slate-400">
            Cargando tickets…
          </div>
        ) : tickets.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-600 py-12 text-center text-sm text-slate-400">
            No hay tickets de RFP todavía. Sube un PDF para comenzar.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs uppercase tracking-wider text-slate-400">
                  <th className="pb-3 pr-4 font-semibold">Ticket</th>
                  <th className="pb-3 pr-4 font-semibold">Cliente</th>
                  <th className="pb-3 pr-4 font-semibold">Servicio</th>
                  <th className="pb-3 pr-4 font-semibold">Deptos.</th>
                  <th className="pb-3 pr-4 font-semibold">Estado</th>
                  <th className="pb-3 pr-4 font-semibold">Creado</th>
                  <th className="pb-3 font-semibold">Acción</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((ticket) => (
                  <tr key={ticket.ticket_id} className="border-b border-slate-800 last:border-0">
                    <td className="py-3 pr-4 font-mono text-xs text-slate-300">
                      {ticket.ticket_id.slice(0, 8)}…
                    </td>
                    <td className="py-3 pr-4 text-slate-100">
                      {ticket.client_name ?? "—"}
                    </td>
                    <td className="py-3 pr-4 text-slate-300">
                      {ticket.service_type ?? "—"}
                    </td>
                    <td className="py-3 pr-4 text-slate-300">
                      {ticket.departments_count ?? "—"}
                    </td>
                    <td className="py-3 pr-4">
                      <StatusBadge status={ticket.status} />
                    </td>
                    <td className="py-3 pr-4 text-xs text-slate-400">
                      {ticket.created_at
                        ? new Date(ticket.created_at).toLocaleString("es-CO")
                        : "—"}
                    </td>
                    <td className="py-3">
                      <button
                        type="button"
                        onClick={() => onViewTicket(ticket.ticket_id)}
                        className="rounded-md bg-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 transition hover:bg-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
                      >
                        Ver detalle
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Ticket Detail */}
      {selectedTicket && (
        <RFPDetailPanel
          ticketId={selectedTicket.ticket_id}
          onBack={() => setSelectedTicket(null)}
          onTicketChanged={fetchTickets}
        />
      )}
    </div>
  );
}

