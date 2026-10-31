"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import dynamic from "next/dynamic";
import { getStoredToken, clearToken } from "@/lib/auth";

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

const DEPARTMENT_LABELS: Record<string, string> = {
  marketing: "Marketing — Camila Ospina",
  operaciones: "Operaciones — Felipe Guerrero",
  procurement: "Procurement — Lucía Fernández",
  training: "Training — Jake Morrison",
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

function StatusBadge({ status }: { status: TicketStatus }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-bold ${STATUS_TONES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
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

  // Fetch ticket list
  const fetchTickets = useCallback(async () => {
    try {
      const data = await apiFetch<TicketListItem[]>("/api/rfp/tickets");
      setTickets(data);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al cargar tickets");
    } finally {
      setLoading(false);
    }
  }, []);

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
        </div>
      </section>

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
        <section className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
          <div className="mb-4 flex items-start justify-between">
            <div>
              <h2 className="text-lg font-bold text-white">
                Ticket: <span className="font-mono text-orange-200">{selectedTicket.ticket_id.slice(0, 8)}…</span>
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                {selectedTicket.created_at
                  ? new Date(selectedTicket.created_at).toLocaleString("es-CO")
                  : ""}
              </p>
            </div>
            <StatusBadge status={selectedTicket.status} />
          </div>

          {/* Metadata */}
          {selectedTicket.metadata && (
            <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <InfoCard label="Cliente" value={selectedTicket.metadata.client_name} />
              <InfoCard label="Ubicación" value={selectedTicket.metadata.location} />
              <InfoCard label="Servicio" value={selectedTicket.metadata.service_type} />
              <InfoCard label="Alcance" value={selectedTicket.metadata.scope} />
              <InfoCard label="Fecha límite" value={selectedTicket.metadata.deadline} />
              <InfoCard label="Presupuesto" value={selectedTicket.metadata.budget_range} />
              <InfoCard
                label="Valor estimado (USD)"
                value={
                  selectedTicket.metadata.annual_estimated_usd
                    ? `$${selectedTicket.metadata.annual_estimated_usd.toLocaleString()}`
                    : null
                }
              />
              <InfoCard
                label="Confianza del clasificador"
                value={
                  selectedTicket.metadata.classifier_confidence
                    ? `${(selectedTicket.metadata.classifier_confidence * 100).toFixed(0)}%`
                    : null
                }
              />
            </div>
          )}

          {/* Readability Metrics */}
          {selectedTicket.metadata &&
            (selectedTicket.metadata.flesch_kincaid_grade != null ||
              selectedTicket.metadata.gunning_fog != null) && (
              <div className="mb-6">
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Métricas de Legibilidad
                </h3>
                <div className="flex flex-wrap gap-3">
                  {selectedTicket.metadata.flesch_kincaid_grade != null && (
                    <MetricBadge
                      label="Flesch-Kincaid"
                      value={String(selectedTicket.metadata.flesch_kincaid_grade)}
                    />
                  )}
                  {selectedTicket.metadata.gunning_fog != null && (
                    <MetricBadge
                      label="Gunning Fog"
                      value={String(selectedTicket.metadata.gunning_fog)}
                    />
                  )}
                  {selectedTicket.metadata.word_count != null && (
                    <MetricBadge
                      label="Palabras"
                      value={String(selectedTicket.metadata.word_count)}
                    />
                  )}
                  {selectedTicket.metadata.flesch_reading_ease != null && (
                    <MetricBadge
                      label="Flesch Reading Ease"
                      value={String(selectedTicket.metadata.flesch_reading_ease)}
                    />
                  )}
                </div>
              </div>
            )}

          {/* Departments */}
          {selectedTicket.department_sections.length > 0 && (
            <div className="mb-6">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                Análisis por Departamento
              </h3>
              <div className="space-y-4">
                {selectedTicket.department_sections.map((section) => (
                  <div
                    key={section.id ?? section.department_id}
                    className="rounded-xl border border-slate-700 bg-slate-800/50 p-4"
                  >
                    <h4 className="mb-2 font-semibold text-orange-200">
                      {DEPARTMENT_LABELS[section.department_id] ?? section.department_id}
                    </h4>
                    {section.key_aspects ? (
                      <div className="prose prose-invert prose-sm max-w-none text-slate-300">
                        <ReactMarkdown>
                          {section.key_aspects}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <p className="text-sm italic text-slate-500">
                        {selectedTicket.status === "analizando"
                          ? "Analizando…"
                          : "No disponible"}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Events */}
          {selectedTicket.events.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                Historial de Eventos
              </h3>
              <div className="space-y-1">
                {selectedTicket.events.map((evt, i) => (
                  <div key={i} className="flex items-start gap-3 text-sm">
                    <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-orange-400" />
                    <span className="font-mono text-xs text-slate-400">
                      {evt.created_at
                        ? new Date(evt.created_at).toLocaleTimeString("es-CO")
                        : ""}
                    </span>
                    <span className="text-slate-200">{evt.event}</span>
                    {evt.detail && (
                      <span className="text-slate-400">— {evt.detail}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Show synthesis link if completed */}
          {selectedTicket.status === "analisis_completo" && (
            <div className="mt-6 rounded-xl border border-emerald-700/50 bg-emerald-950/30 p-4">
              <p className="text-sm text-emerald-200">
                ✅ Análisis completo. El ticket está listo para la Parte 2 (generación de borradores).
              </p>
              <p className="mt-1 text-xs text-emerald-300/70">
                Handoff payload disponible en el detalle del ticket.
              </p>
            </div>
          )}

          {selectedTicket.status === "descartado" && (
            <div className="mt-6 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
              <p className="text-sm text-slate-300">
                ⛔ Documento descartado por el clasificador.
              </p>
              {selectedTicket.metadata?.classification_reason && (
                <p className="mt-1 text-xs text-slate-400">
                  Razón: {selectedTicket.metadata.classification_reason}
                </p>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small presentational components
// ---------------------------------------------------------------------------

function InfoCard({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-1 text-sm text-slate-100">{value ?? "—"}</p>
    </div>
  );
}

function MetricBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-700/50 bg-cyan-950/30 px-3 py-1 text-xs font-medium text-cyan-200">
      <span className="text-cyan-400">{label}:</span> {value}
    </span>
  );
}