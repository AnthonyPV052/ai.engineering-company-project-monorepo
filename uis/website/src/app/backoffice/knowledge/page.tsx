"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

interface KnowledgeResponse {
  answer: string;
  trace_id: string;
  sources: string[];
  execution_order: string[];
  session_id: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  trace?: Pick<KnowledgeResponse, "trace_id" | "sources" | "execution_order">;
  failed?: boolean;
}

const SESSION_STORAGE_KEY = "brasaland-knowledge-chat-session";

function createSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `knowledge-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function KnowledgePage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const conversationEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let storedSessionId = "";
    try {
      storedSessionId = window.sessionStorage.getItem(SESSION_STORAGE_KEY) ?? "";
      if (!storedSessionId) {
        storedSessionId = createSessionId();
        window.sessionStorage.setItem(SESSION_STORAGE_KEY, storedSessionId);
      }
    } catch {
      storedSessionId = createSessionId();
    }
    setSessionId(storedSessionId);
  }, []);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || loading || !sessionId) return;

    const userMessageId = createSessionId();
    setQuestion("");
    setError(null);
    setLoading(true);
    setMessages((current) => [...current, { id: userMessageId, role: "user", content: trimmed }]);

    try {
      const response = await fetch("/api/knowledge/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, session_id: sessionId }),
      });
      const payload = (await response.json().catch(() => null)) as KnowledgeResponse | { detail?: string } | null;
      if (!response.ok || !payload || !("answer" in payload) || typeof payload.answer !== "string") {
        throw new Error(payload && "detail" in payload && payload.detail ? payload.detail : "No se pudo obtener una respuesta.");
      }
      setMessages((current) => [...current, {
        id: payload.trace_id || createSessionId(),
        role: "assistant",
        content: payload.answer,
        trace: {
          trace_id: payload.trace_id,
          sources: payload.sources ?? [],
          execution_order: payload.execution_order ?? [],
        },
      }]);
    } catch (requestError) {
      const message = requestError instanceof Error
        ? requestError.message
        : "No se pudo conectar con el servicio de conocimiento.";
      setError(message);
      setMessages((current) => [...current, {
        id: createSessionId(),
        role: "assistant",
        content: "No pude completar esta consulta. Comprueba la conexión e inténtalo de nuevo.",
        failed: true,
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function startNewConversation() {
    const nextSessionId = createSessionId();
    try {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, nextSessionId);
    } catch {
      // La conversación seguirá funcionando aunque el navegador bloquee storage.
    }
    setSessionId(nextSessionId);
    setMessages([]);
    setQuestion("");
    setError(null);
    inputRef.current?.focus();
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 pb-8">
      <section className="relative overflow-hidden rounded-3xl border border-violet-300/25 bg-gradient-to-br from-slate-950 via-violet-950 to-cyan-950 p-6 sm:p-8">
        <div className="absolute -right-16 -top-20 h-56 w-56 rounded-full bg-violet-400/15 blur-3xl" aria-hidden="true" />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-violet-200">Conocimiento Brasaland</p>
            <h1 className="mt-3 text-3xl font-black text-white sm:text-4xl">Asistente de conocimiento</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-200">
              Pregunta sobre operaciones y continúa la conversación: el asistente conservará el contexto de este chat.
            </p>
          </div>
          <button
            type="button"
            onClick={startNewConversation}
            disabled={loading || !sessionId}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-violet-200/30 bg-slate-950/40 px-4 py-2.5 text-sm font-bold text-violet-100 transition hover:border-violet-200/60 hover:bg-violet-200/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
              <path d="M12 5v14M5 12h14" strokeLinecap="round" />
            </svg>
            Nueva conversación
          </button>
        </div>
      </section>

      <section className="flex min-h-[60vh] flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 shadow-xl shadow-slate-950/30 sm:min-h-[68vh]">
        <div className="flex items-center justify-between border-b border-slate-700/80 px-5 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 text-cyan-200">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                <path d="M12 3.5a8.5 8.5 0 0 0-7.2 13l-.8 4 4-1A8.5 8.5 0 1 0 12 3.5Z" strokeLinejoin="round" />
                <path d="M8.5 12h.01M12 12h.01M15.5 12h.01" strokeLinecap="round" strokeWidth="2.5" />
              </svg>
            </span>
            <div>
              <p className="text-sm font-bold text-white">Chat de operaciones</p>
              <p className="text-xs text-slate-400">Documentación interna y memorias confirmadas</p>
            </div>
          </div>
          <span className="hidden items-center gap-2 text-xs text-emerald-200 sm:inline-flex">
            <span className="h-2 w-2 rounded-full bg-emerald-300" aria-hidden="true" />
            Sesión activa
          </span>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-4 py-6 sm:px-6" aria-live="polite" aria-label="Conversación">
          {messages.length === 0 ? (
            <div className="flex min-h-[34vh] flex-col items-center justify-center px-4 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl border border-violet-300/20 bg-violet-300/10 text-violet-200">
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-7 w-7">
                  <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v9a2.5 2.5 0 0 1-2.5 2.5H11l-5 4v-4.3A2.5 2.5 0 0 1 4 14.5z" strokeLinejoin="round" />
                  <path d="M8 8h8M8 12h5" strokeLinecap="round" />
                </svg>
              </span>
              <h2 className="mt-5 text-lg font-bold text-white">¿En qué te puedo ayudar?</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">
                Consulta procedimientos, alérgenos, proveedores o fidelización. Puedes hacer preguntas de seguimiento sin perder el hilo.
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {["¿Qué alérgenos tiene la Ensalada Tropical?", "¿Cómo se maneja la merma no explicada?"].map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setQuestion(suggestion)}
                    className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-2 text-left text-xs text-slate-300 transition hover:border-violet-300/50 hover:text-violet-100"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`flex gap-3 ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                {message.role === "assistant" && (
                  <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-200" aria-label="Asistente">
                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                      <path d="M12 3.5a8.5 8.5 0 0 0-7.2 13l-.8 4 4-1A8.5 8.5 0 1 0 12 3.5Z" strokeLinejoin="round" />
                    </svg>
                  </span>
                )}
                <div className={`max-w-[88%] rounded-2xl px-4 py-3 sm:max-w-[78%] ${
                  message.role === "user"
                    ? "rounded-br-md border border-violet-200/20 bg-violet-300 text-slate-950"
                    : message.failed
                      ? "rounded-bl-md border border-rose-400/30 bg-rose-950/30 text-rose-100"
                      : "rounded-bl-md border border-slate-700 bg-slate-950/80 text-slate-100"
                }`}>
                  <p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p>
                  {message.trace && (
                    <details className="mt-3 border-t border-slate-700/70 pt-2 text-xs text-slate-400">
                      <summary className="cursor-pointer select-none font-semibold text-cyan-200/80 hover:text-cyan-100">Detalles de la respuesta</summary>
                      <div className="mt-2 space-y-1 break-words">
                        <p><span className="font-semibold text-slate-300">Fuentes:</span> {message.trace.sources.join(" → ") || "Sin fuentes"}</p>
                        <p><span className="font-semibold text-slate-300">Ejecución:</span> {message.trace.execution_order.join(" → ") || "—"}</p>
                        <p><span className="font-semibold text-slate-300">Trace ID:</span> {message.trace.trace_id}</p>
                      </div>
                    </details>
                  )}
                </div>
                {message.role === "user" && (
                  <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-orange-200/20 bg-orange-200/10 text-xs font-black text-orange-100" aria-label="Tú">TÚ</span>
                )}
              </article>
            ))
          )}
          {loading && (
            <div className="flex items-start gap-3" role="status" aria-label="El asistente está respondiendo">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-200">
                <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-200" />
              </span>
              <div className="rounded-2xl rounded-bl-md border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-400">
                Buscando en la documentación y preparando la respuesta…
              </div>
            </div>
          )}
          <div ref={conversationEndRef} />
        </div>

        {error && (
          <div role="alert" className="mx-4 mb-3 rounded-xl border border-rose-400/40 bg-rose-950/30 p-3 text-sm text-rose-100 sm:mx-6">
            <span className="font-bold">Error de conexión:</span> {error}
          </div>
        )}

        <form onSubmit={submit} className="border-t border-slate-700/80 bg-slate-900/95 p-4 sm:p-5">
          <label htmlFor="knowledge-question" className="sr-only">Escribe tu mensaje</label>
          <div className="flex items-end gap-3 rounded-2xl border border-slate-600 bg-slate-950 p-2 transition focus-within:border-violet-300/70">
            <textarea
              ref={inputRef}
              id="knowledge-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Escribe tu pregunta… (Enter para enviar, Shift+Enter para nueva línea)"
              rows={2}
              disabled={loading || !sessionId}
              className="max-h-40 min-h-12 flex-1 resize-y bg-transparent px-2 py-2 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={loading || !question.trim() || !sessionId}
              aria-label="Enviar mensaje"
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-300 text-slate-950 transition hover:bg-violet-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-200 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-950/30 border-t-slate-950" aria-hidden="true" />
              ) : (
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
                  <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-2 text-center text-[11px] text-slate-500">Las respuestas pueden contener errores. Verifica los procedimientos críticos en la documentación oficial.</p>
        </form>
      </section>
    </main>
  );
}
