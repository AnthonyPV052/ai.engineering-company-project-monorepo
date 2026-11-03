"use client";

/* ========================================================================
   Asistente de conocimiento — chat en vivo por WebSocket (Parte 2)
   ========================================================================
   Esta página ya existía y hablaba con `POST /api/knowledge/query` en
   petición/respuesta. Ahora usa el canal persistente que extiende esa MISMA
   ruta (`/chat/ws`, ver services/api/chat/ws.py), así que:

   - la respuesta aparece token a token (efecto máquina de escribir) en lugar
     de esperar a que el agente termine;
   - se puede interrumpir a mitad de respuesta: el mensaje parcial queda
     visible marcado como «interrumpida» y lo que el encargado escriba se
     convierte en un turno nuevo;
   - al recargar / reconectar se rehidrata la conversación con el mismo
     `session_id` (que es el `thread_id` de LangGraph) en vez de empezar vacío.
   ======================================================================== */

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { type ChatBubble, type ChatConnectionState, useChatSocket } from "@/lib/chatSocket";

const SESSION_STORAGE_KEY = "brasaland-knowledge-chat-session";

const SUGGESTIONS = [
  "¿Qué alérgenos tiene la Ensalada Tropical?",
  "¿Cómo se maneja la merma no explicada?",
];

const CONNECTION_LABELS: Record<ChatConnectionState, string> = {
  connecting: "Conectando…",
  open: "En vivo",
  reconnecting: "Reconectando…",
  closed: "Desconectado",
  unauthorized: "Sesión caducada",
};

const CONNECTION_STYLES: Record<ChatConnectionState, { dot: string; text: string }> = {
  connecting: { dot: "bg-amber-300", text: "text-amber-200" },
  open: { dot: "bg-emerald-300", text: "text-emerald-200" },
  reconnecting: { dot: "bg-amber-300 animate-pulse", text: "text-amber-200" },
  closed: { dot: "bg-rose-400", text: "text-rose-200" },
  unauthorized: { dot: "bg-rose-400", text: "text-rose-200" },
};

function createSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `knowledge-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function StatusBadge({ message }: { message: ChatBubble }) {
  if (message.role !== "assistant") return null;
  if (message.status === "interrupted") {
    return (
      <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-[11px] font-semibold text-amber-200">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-300" aria-hidden="true" />
        Interrumpida · respuesta parcial
      </span>
    );
  }
  if (message.status === "failed") {
    return (
      <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-rose-400/40 bg-rose-400/10 px-2 py-0.5 text-[11px] font-semibold text-rose-200">
        Error de generación
      </span>
    );
  }
  return null;
}

export default function KnowledgePage() {
  const [question, setQuestion] = useState("");
  // El `session_id` (= `thread_id` de LangGraph) vive en sessionStorage, así que
  // se resuelve antes del primer render del cliente: la reconexión y el refresco
  // reutilizan el mismo hilo en lugar de abrir una conversación vacía.
  const [sessionId, setSessionId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    try {
      const stored = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
      if (stored) return stored;
      const created = createSessionId();
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, created);
      return created;
    } catch {
      return createSessionId();
    }
  });
  const conversationEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { messages, connectionState, isGenerating, error, send, interrupt, clearError, reconnectNow } = useChatSocket({
    sessionId,
  });

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const canSend = Boolean(sessionId) && connectionState === "open";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || !canSend) return;

    // Si el agente está respondiendo, `send` manda `interrupt_requested` con
    // `new_input`: el parcial se queda visible como «interrumpido» y el texto
    // nuevo arranca un turno distinto sobre el mismo hilo.
    send(trimmed);
    setQuestion("");
    clearError();
    inputRef.current?.focus();
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
    setQuestion("");
    clearError();
    inputRef.current?.focus();
  }

  const connectionLabel = CONNECTION_LABELS[connectionState];
  const connectionStyle = CONNECTION_STYLES[connectionState];
  const lastMessage = messages[messages.length - 1];

  return (
    <main className="mx-auto max-w-5xl space-y-6 pb-8">
      <section className="relative overflow-hidden rounded-3xl border border-violet-300/25 bg-gradient-to-br from-slate-950 via-violet-950 to-cyan-950 p-6 sm:p-8">
        <div
          className="absolute -right-16 -top-20 h-56 w-56 rounded-full bg-violet-400/15 blur-3xl"
          aria-hidden="true"
        />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-violet-200">Conocimiento Brasaland</p>
            <h1 className="mt-3 text-3xl font-black text-white sm:text-4xl">Asistente de conocimiento</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-200">
              Pregunta sobre operaciones y continúa la conversación: el asistente conserva el contexto de este chat y
              responde en streaming. Puedes interrumpirle en cualquier momento.
            </p>
          </div>
          <button
            type="button"
            onClick={startNewConversation}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-violet-200/30 bg-slate-950/40 px-4 py-2.5 text-sm font-bold text-violet-100 transition hover:border-violet-200/60 hover:bg-violet-200/10"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="h-4 w-4"
            >
              <path d="M12 5v14M5 12h14" strokeLinecap="round" />
            </svg>
            Nueva conversación
          </button>
        </div>
      </section>

      <section className="flex min-h-[60vh] flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 shadow-xl shadow-slate-950/30 sm:min-h-[68vh]">
        <div className="flex items-center justify-between gap-3 border-b border-slate-700/80 px-5 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 text-cyan-200">
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                className="h-5 w-5"
              >
                <path d="M12 3.5a8.5 8.5 0 0 0-7.2 13l-.8 4 4-1A8.5 8.5 0 1 0 12 3.5Z" strokeLinejoin="round" />
                <path d="M8.5 12h.01M12 12h.01M15.5 12h.01" strokeLinecap="round" strokeWidth="2.5" />
              </svg>
            </span>
            <div>
              <p className="text-sm font-bold text-white">Chat de operaciones</p>
              <p className="text-xs text-slate-400">Documentación interna y memorias confirmadas</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {isGenerating && (
              <button
                type="button"
                onClick={interrupt}
                aria-label="Interrumpir la respuesta en curso"
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300/40 bg-amber-300/10 px-2.5 py-1.5 text-xs font-bold text-amber-100 transition hover:border-amber-200/70 hover:bg-amber-300/20"
              >
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3.5 w-3.5"
                >
                  <rect x="7" y="7" width="10" height="10" rx="1.5" />
                </svg>
                Interrumpir
              </button>
            )}
            <span
              role="status"
              aria-live="polite"
              className={`inline-flex items-center gap-2 text-xs ${connectionStyle.text}`}
            >
              <span className={`h-2 w-2 rounded-full ${connectionStyle.dot}`} aria-hidden="true" />
              <span className="hidden sm:inline">{connectionLabel}</span>
            </span>
          </div>
        </div>

        <div
          aria-live="polite"
          aria-label="Conversación"
          className="flex-1 space-y-6 overflow-y-auto px-4 py-6 sm:px-6"
        >
          {messages.length === 0 ? (
            <div className="flex min-h-[34vh] flex-col items-center justify-center px-4 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl border border-violet-300/20 bg-violet-300/10 text-violet-200">
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  className="h-7 w-7"
                >
                  <path
                    d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v9a2.5 2.5 0 0 1-2.5 2.5H11l-5 4v-4.3A2.5 2.5 0 0 1 4 14.5z"
                    strokeLinejoin="round"
                  />
                  <path d="M8 8h8M8 12h5" strokeLinecap="round" />
                </svg>
              </span>
              <h2 className="mt-5 text-lg font-bold text-white">¿En qué te puedo ayudar?</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">
                Consulta procedimientos, alérgenos, proveedores o fidelización. Puedes hacer preguntas de seguimiento sin
                perder el hilo.
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((suggestion) => (
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
              <article
                key={message.message_id}
                className={`flex gap-3 ${message.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {message.role === "assistant" && (
                  <span
                    aria-label="Asistente"
                    className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-200"
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      className="h-4 w-4"
                    >
                      <path d="M12 3.5a8.5 8.5 0 0 0-7.2 13l-.8 4 4-1A8.5 8.5 0 1 0 12 3.5Z" strokeLinejoin="round" />
                    </svg>
                  </span>
                )}
                <div
                  className={`max-w-[88%] rounded-2xl px-4 py-3 sm:max-w-[78%] ${
                    message.role === "user"
                      ? "rounded-br-md bg-violet-300 text-slate-950"
                      : message.status === "failed"
                        ? "rounded-bl-md border border-rose-400/30 bg-rose-950/30 text-rose-100"
                        : message.status === "interrupted"
                          ? "rounded-bl-md border border-amber-300/30 bg-amber-950/20 text-amber-50"
                          : "rounded-bl-md border border-slate-700 bg-slate-950/80 text-slate-100"
                  }`}
                >
                  <p className="whitespace-pre-wrap text-sm leading-7">
                    {message.content}
                    {message.streaming && (
                      <span
                        aria-hidden="true"
                        className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-cyan-200/80"
                      />
                    )}
                  </p>
                  <StatusBadge message={message} />
                </div>
                {message.role === "user" && (
                  <span
                    aria-label="Tú"
                    className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-orange-200/20 bg-orange-200/10 text-[10px] font-black text-orange-100"
                  >
                    TÚ
                  </span>
                )}
              </article>
            ))
          )}

          {isGenerating && lastMessage?.role === "user" && (
            <div className="flex items-start gap-3" role="status" aria-label="El asistente está respondiendo">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10">
                <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-200" />
              </span>
              <div className="rounded-2xl rounded-bl-md border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-400">
                Buscando en la documentación y preparando la respuesta…
              </div>
            </div>
          )}

          {connectionState === "reconnecting" && (
            <p role="status" className="text-center text-xs text-amber-200/80">
              Conexión perdida. Reintentando con el mismo hilo de conversación…
            </p>
          )}

          <div ref={conversationEndRef} />
        </div>

        {error && (
          <div
            role="alert"
            className="mx-4 mb-3 flex items-start justify-between gap-3 rounded-xl border border-rose-400/40 bg-rose-950/30 p-3 text-sm text-rose-100 sm:mx-6"
          >
            <span>
              <span className="font-bold">Error de conexión:</span> {error}
            </span>
            <button
              type="button"
              onClick={() => (connectionState === "open" ? clearError() : reconnectNow())}
              className="shrink-0 rounded-lg border border-rose-300/40 px-2 py-1 text-xs font-bold text-rose-100 hover:bg-rose-300/10"
            >
              {connectionState === "open" ? "Descartar" : "Reconectar"}
            </button>
          </div>
        )}

        <form onSubmit={submit} className="border-t border-slate-700/80 bg-slate-900/95 p-4 sm:p-5">
          <label htmlFor="knowledge-question" className="sr-only">
            Escribe tu mensaje
          </label>
          <div className="flex items-end gap-3 rounded-2xl border border-slate-600 bg-slate-950 p-2 transition focus-within:border-violet-300/70">
            <textarea
              ref={inputRef}
              id="knowledge-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={
                isGenerating
                  ? "Escribe para interrumpir y preguntar otra cosa…"
                  : "Escribe tu pregunta… (Enter envía, Shift+Enter nueva línea)"
              }
              rows={2}
              className="max-h-40 min-h-12 flex-1 resize-y bg-transparent px-2 py-2 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500"
            />
            <button
              type="submit"
              disabled={!question.trim() || !canSend}
              aria-label={isGenerating ? "Interrumpir y enviar" : "Enviar mensaje"}
              className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40 ${
                isGenerating
                  ? "bg-amber-300 text-slate-950 hover:bg-amber-200 focus-visible:outline-amber-200"
                  : "bg-violet-300 text-slate-950 hover:bg-violet-200 focus-visible:outline-violet-200"
              }`}
            >
              {isGenerating ? (
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-4 w-4"
                >
                  <rect x="7" y="7" width="10" height="10" rx="1.5" />
                </svg>
              ) : (
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-5 w-5"
                >
                  <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-2 text-center text-[11px] text-slate-500">
            Enviar mientras el asistente responde interrumpe la respuesta en curso; el texto parcial se conserva marcado
            como interrumpido.
          </p>
        </form>
      </section>
    </main>
  );
}
