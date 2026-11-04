"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getStoredToken, clearToken } from "@/lib/auth";

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

interface DepartmentSection {
  id: number | null;
  department_id: string;
  key_aspects: string | null;
  draft_content: string | null;
  evaluation_results: Record<string, unknown> | null;
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

interface Part2Result {
  ticket_id: string;
  status: TicketStatus;
  part2_payload: Record<string, unknown> | null;
  department_sections: DepartmentSection[];
}

interface TraceEntry {
  id: number;
  node_name: string;
  agent: string;
  department_id: string | null;
  input_snapshot: string | null;
  output_snapshot: string | null;
  created_at: string | null;
}

interface FinalDocument {
  id: number;
  ticket_id: string;
  content: string;
  total_estimated_value_cop: number | null;
  total_estimated_value_usd: number | null;
  ceo_approval_required: boolean;
  ceo_approved: boolean;
  ceo_approved_at: string | null;
  generated_at: string;
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

const APPROVAL_LABELS: Record<string, string> = {
  pendiente: "Pendiente",
  aprobado: "Aprobado",
  rechazado: "Rechazado",
  request_changes: "Solicita cambios",
};

const APPROVAL_TONES: Record<string, string> = {
  pendiente: "bg-slate-300/10 text-slate-300 border-slate-500/40",
  aprobado: "bg-emerald-300/10 text-emerald-100 border-emerald-300/40",
  rechazado: "bg-rose-300/10 text-rose-100 border-rose-300/40",
  request_changes: "bg-amber-300/10 text-amber-100 border-amber-300/40",
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (init?.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });

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

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RFPDetailPanelProps {
  ticketId: string;
  onBack: () => void;
  onTicketChanged: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RFPDetailPanel({ ticketId, onBack, onTicketChanged }: RFPDetailPanelProps) {
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [part2Result, setPart2Result] = useState<Part2Result | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [traceEntries, setTraceEntries] = useState<TraceEntry[] | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const [finalDoc, setFinalDoc] = useState<FinalDocument | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch ticket detail
  const fetchTicket = useCallback(async () => {
    try {
      const data = await apiFetch<TicketDetail>(`/api/rfp/tickets/${ticketId}`);
      setTicket(data);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error al cargar ticket");
    } finally {
      setLoading(false);
    }
  }, [ticketId]);

  // Fetch Part 2 results
  const fetchPart2 = useCallback(async () => {
    try {
      const data = await apiFetch<Part2Result>(`/api/rfp/tickets/${ticketId}/part2`);
      setPart2Result(data);
    } catch {
      // Part 2 not ready yet — ignore
    }
  }, [ticketId]);

  useEffect(() => {
    fetchTicket();
  }, [fetchTicket]);

  // Poll when in progress
  useEffect(() => {
    if (ticket && (ticket.status === "analizando" || ticket.status === "generando_borrador" || ticket.status === "en_evaluacion")) {
      pollingRef.current = setInterval(async () => {
        await fetchTicket();
        await fetchPart2();
      }, 3000);
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [ticket?.status, fetchTicket, fetchPart2]);

  // Trigger Part 2
  const onGenerate = async () => {
    setActionLoading("generate");
    setActionError(null);
    try {
      await apiFetch(`/api/rfp/tickets/${ticketId}/generate`, { method: "POST" });
      await fetchTicket();
      onTicketChanged();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Error al generar borradores");
    } finally {
      setActionLoading(null);
    }
  };

  // Trigger Part 3
  const onStartApproval = async () => {
    setActionLoading("approve");
    setActionError(null);
    try {
      await apiFetch(`/api/rfp/tickets/${ticketId}/approve`, { method: "POST" });
      await fetchTicket();
      onTicketChanged();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Error al iniciar aprobación");
    } finally {
      setActionLoading(null);
    }
  };

  // Department approval action
  const onDepartmentAction = async (department: string, action: string) => {
    setActionLoading(`dept-${department}`);
    setActionError(null);
    try {
      await apiFetch(`/api/rfp/tickets/${ticketId}/approve/${department}`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      await fetchTicket();
      onTicketChanged();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Error al procesar decisión");
    } finally {
      setActionLoading(null);
    }
  };

  // CEO approval
  const onCEOApproval = async (approved: boolean) => {
    setActionLoading("ceo");
    setActionError(null);
    try {
      await apiFetch(`/api/rfp/tickets/${ticketId}/ceo-approve`, {
        method: "POST",
        body: JSON.stringify({ approved }),
      });
      await fetchTicket();
      onTicketChanged();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Error al registrar decisión del CEO");
    } finally {
      setActionLoading(null);
    }
  };

  // Load trace
  const onLoadTrace = async () => {
    setShowTrace(!showTrace);
    if (!traceEntries) {
      try {
        const data = await apiFetch<TraceEntry[]>(`/api/rfp/tickets/${ticketId}/trace`);
        setTraceEntries(data);
      } catch {
        setTraceEntries([]);
      }
    }
  };

  // Load final document
  const onLoadFinalDoc = async () => {
    try {
      const data = await apiFetch<FinalDocument>(`/api/rfp/tickets/${ticketId}/final-document`);
      setFinalDoc(data);
    } catch {
      setFinalDoc(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-slate-400">
        Cargando detalle del ticket…
      </div>
    );
  }

  if (error && !ticket) {
    return (
      <div className="rounded-2xl border border-rose-700/50 bg-rose-950/30 p-6 text-center">
        <p className="text-rose-200">{error}</p>
        <button type="button" onClick={onBack} className="mt-4 rounded-lg bg-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-600">
          Volver al listado
        </button>
      </div>
    );
  }

  if (!ticket) return null;

  const needsPart2 = ticket.status === "analisis_completo";
  const needsPart3 = ticket.status === "needs_human_review" || ticket.status === "generando_borrador" || ticket.status === "en_evaluacion";
  const waitingApproval = ticket.status === "esperando_aprobacion";
  const isTerminado = ticket.status === "terminado";

  // Determine which departments are still pending approval
  const pendingDepartments = ticket.department_sections.filter(
    (s) => s.approval_status === "pendiente" || s.approval_status === "request_changes"
  );

  // Estimate annual value for CEO threshold
  const annualUsd = ticket.metadata?.annual_estimated_usd ?? null;
  const ceoNeeded = annualUsd !== null && annualUsd > 50000;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button
            type="button"
            onClick={onBack}
            className="mb-3 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-orange-300 transition"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5m7-7-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Volver al listado
          </button>
          <h2 className="text-lg font-bold text-white">
            Ticket: <span className="font-mono text-orange-200">{ticket.ticket_id.slice(0, 8)}…</span>
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            {ticket.created_at ? new Date(ticket.created_at).toLocaleString("es-CO") : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onLoadTrace}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:border-orange-300/70 hover:text-orange-200"
          >
            {showTrace ? "Ocultar traza" : "Ver traza"}
          </button>
          <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-bold ${STATUS_TONES[ticket.status]}`}>
            {STATUS_LABELS[ticket.status]}
          </span>
        </div>
      </div>

      {actionError && (
        <div className="rounded-xl border border-rose-700/50 bg-rose-950/30 p-3 text-sm text-rose-200">
          ⚠️ {actionError}
        </div>
      )}

      {/* Metadata Cards */}
      {ticket.metadata && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <InfoCard label="Cliente" value={ticket.metadata.client_name} />
          <InfoCard label="Ubicación" value={ticket.metadata.location} />
          <InfoCard label="Servicio" value={ticket.metadata.service_type} />
          <InfoCard label="Alcance" value={ticket.metadata.scope} />
          <InfoCard label="Fecha límite" value={ticket.metadata.deadline} />
          <InfoCard label="Presupuesto" value={ticket.metadata.budget_range} />
          <InfoCard label="Valor estimado (USD)" value={ticket.metadata.annual_estimated_usd ? `$${ticket.metadata.annual_estimated_usd.toLocaleString()}` : null} />
          <InfoCard label="Confianza" value={ticket.metadata.classifier_confidence ? `${(ticket.metadata.classifier_confidence * 100).toFixed(0)}%` : null} />
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex flex-wrap gap-3">
        {needsPart2 && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={actionLoading === "generate"}
            className="flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {actionLoading === "generate" ? (
              <><Spinner /> Generando…</>
            ) : (
              "🚀 Generar borradores (Parte 2)"
            )}
          </button>
        )}

        {needsPart3 && (
          <button
            type="button"
            onClick={onStartApproval}
            disabled={actionLoading === "approve"}
            className="flex items-center gap-2 rounded-lg bg-orange-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {actionLoading === "approve" ? (
              <><Spinner /> Iniciando…</>
            ) : (
              "✅ Iniciar aprobación (Parte 3)"
            )}
          </button>
        )}
      </div>

      {/* Part 2 Results */}
      {ticket.status !== "analizando" && ticket.status !== "analisis_completo" && ticket.status !== "descartado" && (
        <Part2ResultsSection ticketId={ticketId} />
      )}

      {/* Department Sections */}
      {ticket.department_sections.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            Departamentos
          </h3>
          <div className="space-y-4">
            {ticket.department_sections.map((section) => {
              const deptId = section.department_id;
              const isPending = section.approval_status === "pendiente" || section.approval_status === "request_changes";
              return (
                <div key={section.id ?? deptId} className="rounded-xl border border-slate-700 bg-slate-800/50 p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h4 className="font-semibold text-orange-200">
                      {DEPARTMENT_LABELS[deptId] ?? deptId}
                    </h4>
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${APPROVAL_TONES[section.approval_status] || APPROVAL_TONES.pendiente}`}>
                      {APPROVAL_LABELS[section.approval_status] ?? section.approval_status}
                    </span>
                  </div>

                  {section.key_aspects && (
                    <div className="prose prose-invert prose-sm max-w-none text-slate-300">
                      <ReactMarkdown>{section.key_aspects}</ReactMarkdown>
                    </div>
                  )}

                  {section.draft_content && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-300">
                        Borrador
                      </summary>
                      <div className="mt-2 rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-200">
                        <ReactMarkdown>{section.draft_content}</ReactMarkdown>
                      </div>
                    </details>
                  )}

                  {/* Department Approval Actions */}
                  {(waitingApproval || isPending) && (
                    <DepartmentApprovalActions
                      department={deptId}
                      onAction={(action) => onDepartmentAction(deptId, action)}
                      loading={actionLoading === `dept-${deptId}`}
                      currentStatus={section.approval_status}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* CEO Approval Section */}
      {waitingApproval && ceoNeeded && (
        <CEOApprovalSection onApprove={(approved) => onCEOApproval(approved)} loading={actionLoading === "ceo"} />
      )}

      {/* Final Document */}
      {isTerminado && (
        <FinalDocumentSection ticketId={ticketId} onLoad={onLoadFinalDoc} finalDoc={finalDoc} />
      )}

      {/* Events */}
      {ticket.events.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
            Historial de Eventos
          </h3>
          <div className="space-y-1">
            {ticket.events.map((evt, i) => (
              <div key={i} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-orange-400" />
                <span className="font-mono text-xs text-slate-400">
                  {evt.created_at ? new Date(evt.created_at).toLocaleTimeString("es-CO") : ""}
                </span>
                <span className="text-slate-200">{evt.event}</span>
                {evt.detail && <span className="text-slate-400">— {evt.detail}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trace */}
      {showTrace && (
        <TraceSection entries={traceEntries} ticketId={ticketId} />
      )}

      {/* Rejection reason */}
      {ticket.status === "descartado" && ticket.metadata?.classification_reason && (
        <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-4">
          <p className="text-sm text-slate-300">
            ⛔ Documento descartado. Razón: {ticket.metadata.classification_reason}
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function InfoCard({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-1 text-sm text-slate-100">{value ?? "—"}</p>
    </div>
  );
}

function InfoBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-700/50 bg-cyan-950/30 px-3 py-1 text-xs font-medium text-cyan-200">
      <span className="text-cyan-400">{label}:</span> {value}
    </span>
  );
}

// -- Part 2 Results Section --

function Part2ResultsSection({ ticketId }: { ticketId: string }) {
  const [data, setData] = useState<Part2Result | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const result = await apiFetch<Part2Result>(`/api/rfp/tickets/${ticketId}/part2`);
        if (!cancelled) setData(result);
      } catch {
        // Not available yet
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [ticketId]);

  if (loading || !data) return null;

  const sectionsWithDrafts = data.department_sections.filter((s) => s.draft_content);

  if (sectionsWithDrafts.length === 0) return null;

  return (
    <div className="rounded-2xl border border-cyan-700/30 bg-cyan-950/20 p-5">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-cyan-300">
        📝 Borradores generados (Parte 2)
      </h3>
      <div className="space-y-4">
        {sectionsWithDrafts.map((section) => {
          const evalRes = section.evaluation_results;
          const passed = evalRes && typeof evalRes === "object" && (evalRes as Record<string, unknown>).overall_pass === true;
          return (
            <div key={section.id ?? section.department_id} className="rounded-xl border border-slate-700 bg-slate-800/40 p-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="font-semibold text-orange-200">
                  {DEPARTMENT_LABELS[section.department_id] ?? section.department_id}
                </span>
                {passed !== null && (
                  <span className={`text-xs font-bold ${passed ? "text-emerald-300" : "text-amber-300"}`}>
                    {passed ? "✅ PASS" : "⚠️ EVAL"}
                  </span>
                )}
              </div>
              {section.draft_content && (
                <div className="mb-2 max-h-60 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-200">
                  <ReactMarkdown>{section.draft_content}</ReactMarkdown>
                </div>
              )}
              {evalRes && typeof evalRes === "object" && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-300">
                    Resultados de evaluación
                  </summary>
                  <pre className="mt-2 overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-400">
                    {JSON.stringify(evalRes, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// -- Department Approval Actions --

interface DeptApprovalProps {
  department: string;
  onAction: (action: string) => void;
  loading: boolean;
  currentStatus: string;
}

function DepartmentApprovalActions({ department, onAction, loading, currentStatus }: DeptApprovalProps) {
  return (
    <div className={`mt-3 flex flex-wrap items-center gap-2 rounded-lg border p-3 ${
      currentStatus === "pendiente"
        ? "border-orange-700/40 bg-orange-950/20"
        : currentStatus === "request_changes"
        ? "border-amber-700/40 bg-amber-950/20"
        : "border-slate-700 bg-slate-800/30"
    }`}>
      <span className="mr-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Acción:</span>
      <button
        type="button"
        onClick={() => onAction("approve")}
        disabled={loading}
        className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-50"
      >
        ✅ Aprobar
      </button>
      <button
        type="button"
        onClick={() => onAction("request_changes")}
        disabled={loading}
        className="rounded-md bg-amber-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-amber-600 disabled:opacity-50"
      >
        📝 Solicitar cambios
      </button>
      <button
        type="button"
        onClick={() => onAction("reject")}
        disabled={loading}
        className="rounded-md bg-rose-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-rose-600 disabled:opacity-50"
      >
        ❌ Rechazar
      </button>
      {loading && <Spinner />}
    </div>
  );
}

// -- CEO Approval Section --

interface CEOProps {
  onApprove: (approved: boolean) => void;
  loading: boolean;
}

function CEOApprovalSection({ onApprove, loading }: CEOProps) {
  return (
    <div className="rounded-xl border border-yellow-600/50 bg-yellow-950/20 p-5">
      <h3 className="mb-2 font-semibold text-yellow-200">
        👑 Aprobación del CEO — Mariana Restrepo
      </h3>
      <p className="mb-3 text-sm text-slate-300">
        El valor estimado supera los $50,000 USD. Se requiere la aprobación del CEO para continuar.
      </p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => onApprove(true)}
          disabled={loading}
          className="rounded-lg bg-emerald-700 px-5 py-2 text-sm font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-50"
        >
          {loading ? <><Spinner /> Procesando…</> : "✅ Aprobar"}
        </button>
        <button
          type="button"
          onClick={() => onApprove(false)}
          disabled={loading}
          className="rounded-lg bg-rose-700 px-5 py-2 text-sm font-semibold text-white transition hover:bg-rose-600 disabled:opacity-50"
        >
          {loading ? <><Spinner /> Procesando…</> : "❌ Rechazar"}
        </button>
      </div>
    </div>
  );
}

// -- Final Document Section --

function FinalDocumentSection({ ticketId, onLoad, finalDoc }: { ticketId: string; onLoad: () => void; finalDoc: FinalDocument | null }) {
  const [loaded, setLoaded] = useState(false);

  const handleLoad = () => {
    onLoad();
    setLoaded(true);
  };

  return (
    <div className="rounded-2xl border border-emerald-700/30 bg-emerald-950/20 p-5">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-emerald-300">
        📄 Documento Final
      </h3>
      {!loaded ? (
        <button
          type="button"
          onClick={handleLoad}
          className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-600"
        >
          Cargar documento final
        </button>
      ) : finalDoc ? (
        <div className="space-y-3">
          <div className="prose prose-invert prose-sm max-w-none max-h-96 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900/50 p-4 text-slate-200">
            <ReactMarkdown>{finalDoc.content}</ReactMarkdown>
          </div>
          <div className="flex flex-wrap gap-4 text-xs text-slate-400">
            {finalDoc.total_estimated_value_cop != null && (
              <span>COP: ${finalDoc.total_estimated_value_cop.toLocaleString()}</span>
            )}
            {finalDoc.total_estimated_value_usd != null && (
              <span>USD: ${finalDoc.total_estimated_value_usd.toLocaleString()}</span>
            )}
            {finalDoc.ceo_approval_required && (
              <span className={finalDoc.ceo_approved ? "text-emerald-300" : "text-amber-300"}>
                CEO: {finalDoc.ceo_approved ? "✅ Aprobado" : "⏳ Pendiente"}
              </span>
            )}
            <span>Generado: {new Date(finalDoc.generated_at).toLocaleString("es-CO")}</span>
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-400">Documento no disponible aún.</p>
      )}
    </div>
  );
}

// -- Trace Section --

function TraceSection({ entries, ticketId }: { entries: TraceEntry[] | null; ticketId: string }) {
  if (!entries) {
    return <div className="text-sm text-slate-400">Cargando traza…</div>;
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4">
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">🔍 Traza de ejecución</h3>
        <p className="text-sm text-slate-400">No hay registros de traza para este ticket.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">🔍 Traza de ejecución</h3>
      <div className="space-y-2">
        {entries.map((entry) => (
          <div key={entry.id} className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="font-mono text-orange-300">{entry.node_name}</span>
              <span className="text-slate-400">→</span>
              <span className="text-slate-300">{entry.agent}</span>
              {entry.department_id && (
                <span className="rounded bg-slate-700 px-1.5 py-0.5 text-slate-300">{entry.department_id}</span>
              )}
              <span className="ml-auto text-slate-500">
                {entry.created_at ? new Date(entry.created_at).toLocaleTimeString("es-CO") : ""}
              </span>
            </div>
            {entry.output_snapshot && (
              <details className="mt-1">
                <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wider text-slate-500 hover:text-slate-400">
                  Output
                </summary>
                <pre className="mt-1 max-h-32 overflow-y-auto rounded bg-slate-950 p-2 text-[10px] text-slate-500">
                  {entry.output_snapshot.length > 500
                    ? entry.output_snapshot.slice(0, 500) + "\n... [truncated]"
                    : entry.output_snapshot}
                </pre>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}