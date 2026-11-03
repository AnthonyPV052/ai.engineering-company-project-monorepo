"use client";

/* ========================================================================
   Cliente WebSocket del chat en vivo — Brasaland BackOffice
   ========================================================================
   Parte 2 — Sistemas en Tiempo Real (streaming de chat por WebSocket).

   Conecta la MISMA conversación que ya servía `POST /api/knowledge/query`
   contra el canal persistente `GET /chat/ws` del Manager support agent
   (`services/api/chat/ws.py`). No hay app paralela ni carpeta de entrega:
   es el cliente de la ruta extendida.

   Contrato del wire (ver services/api/chat/events.py y docs/chat-websocket.es.md):

       {"event": "<nombre>", "data": { ... }}

   Servidor → cliente: session_snapshot, generation_started, token_chunk,
   generation_interrupted, generation_completed, generation_failed,
   user_message, pong, error.
   Cliente → servidor: auth, user_message, interrupt_requested, ping.

   Decisiones relevantes:

   - **JWT**: los navegadores no pueden poner `Authorization` en el handshake.
     Por defecto se envía un primer frame `auth` (el token no queda en la URL
     ni en los logs de acceso); `authMode: "query"` usa `?token=` en su lugar.
   - **Typewriter**: cada `token_chunk` se APPENDEA al mensaje en curso. Nunca
     se reemplaza el contenido previo, que es lo que produce el efecto de
     escritura progresiva.
   - **Interrupción**: si el encargado escribe mientras el agente responde, se
     envía `interrupt_requested` con `new_input`. El servidor aborta el stream
     del modelo, marca el mensaje parcial como `interrupted` y abre un turno
     nuevo. El mensaje interrumpido se queda visible tal cual.
   - **Reconexión**: backoff exponencial progresivo (500 ms → ×2 → 15 s) con el
     MISMO `session_id` (= `thread_id` de LangGraph). Al reconectar el servidor
     manda `session_snapshot` con el historial, así que la conversación se
     rehidrata antes de aceptar tokens nuevos.
   ======================================================================== */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getStoredToken } from "./auth";

// ---------------------------------------------------------------------------
// Tipos del contrato (mismos nombres que el backend)
// ---------------------------------------------------------------------------

export type ChatEventName =
  | "session_snapshot"
  | "generation_started"
  | "token_chunk"
  | "generation_interrupted"
  | "generation_completed"
  | "generation_failed"
  | "user_message"
  | "pong"
  | "error";

export type MessageRole = "user" | "assistant";
export type MessageStatus = "streaming" | "interrupted" | "completed" | "failed";

/** Mensaje tal y como lo entrega el transcript del servidor. */
export interface ChatMessage {
  message_id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  sequence: number;
  created_at: string;
}

/** Payload de `session_snapshot` — rehidratación al (re)conectar. */
export interface SessionSnapshot {
  session_id: string;
  agent_id: string;
  user_id: string | null;
  location_id: string | null;
  status: string;
  created_at: string;
  /** LangGraph: `thread_id === session_id`. */
  thread_id: string;
  messages: ChatMessage[];
}

export interface TokenChunkPayload {
  session_id: string;
  agent_id: string;
  message_id: string;
  token: string;
  /** Índice del token DENTRO de la generación (empieza en 1). */
  sequence: number;
}

export interface GenerationEventPayload {
  session_id: string;
  agent_id: string;
  message_id: string;
  status: MessageStatus;
  content_length?: number;
  reason?: string;
  new_input?: string;
}

export interface UserMessagePayload {
  session_id: string;
  message_id: string;
  text: string;
}

export type ChatConnectionState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "unauthorized";

export interface ChatSocketHandlers {
  onSnapshot?: (snapshot: SessionSnapshot) => void;
  onGenerationStarted?: (payload: GenerationEventPayload) => void;
  onTokenChunk?: (payload: TokenChunkPayload) => void;
  onGenerationInterrupted?: (payload: GenerationEventPayload) => void;
  onGenerationCompleted?: (payload: GenerationEventPayload) => void;
  onGenerationFailed?: (payload: GenerationEventPayload) => void;
  onUserMessage?: (payload: UserMessagePayload) => void;
  onError?: (payload: { code: string; message: string }) => void;
  onStateChange?: (state: ChatConnectionState) => void;
}

// ---------------------------------------------------------------------------
// Configuración
// ---------------------------------------------------------------------------

/** Backoff progresivo: 500 ms, 1 s, 2 s … hasta 15 s. */
export const INITIAL_RECONNECT_DELAY_MS = 500;
export const MAX_RECONNECT_DELAY_MS = 15_000;
/** Ping de aplicación para que proxies no cierren una conexión ociosa. */
export const HEARTBEAT_INTERVAL_MS = 25_000;
/** Códigos de cierre de aplicación del backend. */
const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_CLOSED_PERMANENTLY = 4404;

/**
 * Deriva la URL del WebSocket del chat.
 *
 * Los *rewrites* de Next.js reenvían correctamente el handshake WebSocket
 * porque éste es una petición HTTP GET con header `Upgrade: websocket`.
 * Next.js recibe el upgrade y lo reenvía al destino del rewrite, completando
 * el handshake con el backend.
 *
 * Estrategia (por orden de prioridad):
 * 1. `NEXT_PUBLIC_CHAT_WS_URL` si está definida (ej. `wss://api.brasaland.io`).
 * 2. `NEXT_PUBLIC_API_URL` convertida a `ws(s)://` añadiendo `/chat/ws`.
 * 3. Mismo origen que la página + `/api/chat/ws` (el rewrite de Next.js
 *    lo reenvía a `http://172.17.0.1:8020/chat/ws`). Funciona en localhost,
 *    en Codespaces y en cualquier proxy que tenga Next.js delante.
 */
export function resolveChatSocketUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_CHAT_WS_URL;
  if (explicit) {
    return explicit.replace(/\/$/, "");
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_SUPPLIERS_API_URL;
  if (apiUrl && /^https?:\/\//.test(apiUrl)) {
    const wsBase = apiUrl
      .replace(/^http/, "ws")
      .replace(/\/suppliers\/?$/, "")
      .replace(/\/$/, "");
    return `${wsBase}/chat/ws`;
  }

  if (typeof window === "undefined") {
    return "ws://127.0.0.1:8020/chat/ws";
  }

  // Usar el mismo origen + la ruta del rewrite de Next.js.
  // El rewrite `/api/:path*` → `http://172.17.0.1:8020/:path*` reenvía
  // correctamente el handshake WebSocket al backend.
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/chat/ws`;
}

export interface ChatSocketOptions extends ChatSocketHandlers {
  sessionId: string;
  /** Local sobre el que pregunta el encargado (`?location_id=`). */
  locationId?: string;
  /** URL del endpoint; por defecto `resolveChatSocketUrl()`. */
  url?: string;
  /**
   * Cómo se envía el JWT: primer frame `auth` (por defecto, no expone el token
   * en la URL) o `?token=` en el handshake.
   */
  authMode?: "frame" | "query";
}

// ---------------------------------------------------------------------------
// Cliente
// ---------------------------------------------------------------------------

/** Reordena/ensambla tokens por `message_id`, tolerante a duplicados. */
export class ChatTokenAssembler {
  private content = new Map<string, string>();
  private seen = new Map<string, Set<number>>();

  append(payload: TokenChunkPayload): string {
    const seenSequences = this.seen.get(payload.message_id) ?? new Set<number>();
    if (seenSequences.has(payload.sequence)) {
      // Reenvío tras reconexión: el token ya está aplicado.
      return this.content.get(payload.message_id) ?? "";
    }
    seenSequences.add(payload.sequence);
    this.seen.set(payload.message_id, seenSequences);
    const next = (this.content.get(payload.message_id) ?? "") + payload.token;
    this.content.set(payload.message_id, next);
    return next;
  }

  get(messageId: string): string {
    return this.content.get(messageId) ?? "";
  }

  /** Carga el contenido ya conocido de un mensaje (rehidratación). */
  hydrate(messageId: string, content: string): void {
    this.content.set(messageId, content);
  }

  reset(): void {
    this.content.clear();
    this.seen.clear();
  }
}

export class ChatSocketClient {
  private options: ChatSocketOptions;
  private socket: WebSocket | null = null;
  private stopped = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  constructor(options: ChatSocketOptions) {
    this.options = options;
  }

  get sessionId(): string {
    return this.options.sessionId;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.socket?.close(1000, "client_stop");
    this.socket = null;
    this.options.onStateChange?.("closed");
  }

  /** Envía un turno del encargado. */
  sendUserMessage(text: string): boolean {
    return this.send("user_message", { text });
  }

  /**
   * Pide abortar la generación en curso.
   *
   * `newInput` abre un turno nuevo con ese texto; el mensaje parcial queda
   * marcado `interrupted` y visible (el servidor no lo borra ni lo sobrescribe).
   */
  sendInterrupt(newInput?: string): boolean {
    const data: Record<string, unknown> = { session_id: this.options.sessionId };
    if (newInput) {
      data.new_input = newInput;
    }
    return this.send("interrupt_requested", data);
  }

  ping(): boolean {
    return this.send("ping", {});
  }

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  // -- internos ----------------------------------------------------------

  private send(event: string, data: Record<string, unknown>): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(
      JSON.stringify({ event, data: { session_id: this.options.sessionId, ...data } }),
    );
    return true;
  }

  private connect(): void {
    if (this.stopped || typeof window === "undefined") return;

    const token = getStoredToken();
    if (!token) {
      // Sin JWT no hay canal: la página redirige al login.
      this.options.onStateChange?.("unauthorized");
      return;
    }

    const baseUrl = (this.options.url ?? resolveChatSocketUrl()).replace(/\/$/, "");
    const params = new URLSearchParams({ session_id: this.options.sessionId });
    if (this.options.locationId) {
      params.set("location_id", this.options.locationId);
    }
    const authMode = this.options.authMode ?? "frame";
    if (authMode === "query") {
      params.set("token", token);
    }

    this.options.onStateChange?.(
      this.reconnectAttempt > 0 ? "reconnecting" : "connecting",
    );

    let socket: WebSocket;
    try {
      socket = new WebSocket(`${baseUrl}?${params.toString()}`);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      // Con `authMode: "frame"` el servidor espera este primer frame antes de
      // enviar cualquier evento de chat (rechaza con 4401 si no llega).
      if (authMode === "frame") {
        socket.send(JSON.stringify({ event: "auth", data: { token } }));
      }
      this.reconnectAttempt = 0;
      this.options.onStateChange?.("open");
      this.startHeartbeat();
    };

    socket.onmessage = (message: MessageEvent<string>) => {
      this.dispatch(message.data);
    };

    socket.onerror = () => {
      // `onclose` hará el trabajo de reconexión.
    };

    socket.onclose = (event: CloseEvent) => {
      this.clearTimers();
      this.socket = null;
      if (this.stopped) {
        this.options.onStateChange?.("closed");
        return;
      }
      if (event.code === CLOSE_UNAUTHORIZED) {
        // Token inválido/caducado: reintentar en bucle no arregla nada.
        this.stopped = true;
        this.options.onStateChange?.("unauthorized");
        return;
      }
      // Cierre limpio (1000) o cierre permanente (4404): no reconectar.
      if (event.code === CLOSE_CLOSED_PERMANENTLY || event.code === 1000) {
        this.stopped = true;
        this.options.onStateChange?.("closed");
        return;
      }
      this.scheduleReconnect();
    };
  }

  private dispatch(raw: string): void {
    let payload: { event?: string; data?: Record<string, unknown> };
    try {
      payload = JSON.parse(raw);
    } catch {
      return;
    }
    const event = payload.event;
    const data = payload.data ?? {};
    if (!event) return;

    switch (event as ChatEventName) {
      case "session_snapshot":
        this.options.onSnapshot?.(data as unknown as SessionSnapshot);
        break;
      case "generation_started":
        this.options.onGenerationStarted?.(data as unknown as GenerationEventPayload);
        break;
      case "token_chunk":
        this.options.onTokenChunk?.(data as unknown as TokenChunkPayload);
        break;
      case "generation_interrupted":
        this.options.onGenerationInterrupted?.(data as unknown as GenerationEventPayload);
        break;
      case "generation_completed":
        this.options.onGenerationCompleted?.(data as unknown as GenerationEventPayload);
        break;
      case "generation_failed":
        this.options.onGenerationFailed?.(data as unknown as GenerationEventPayload);
        break;
      case "user_message":
        this.options.onUserMessage?.(data as unknown as UserMessagePayload);
        break;
      case "error":
        this.options.onError?.(data as unknown as { code: string; message: string });
        break;
      case "pong":
      default:
        break;
    }
  }

  private startHeartbeat(): void {
    this.clearTimers();
    this.heartbeatTimer = setInterval(() => {
      this.ping();
    }, HEARTBEAT_INTERVAL_MS);
  }

  private clearTimers(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;

    // Backoff progresivo con jitter para no sincronizar reintentos.
    const exponential = Math.min(
      INITIAL_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    );
    const delay = exponential + Math.floor(Math.random() * 250);
    this.reconnectAttempt += 1;
    this.options.onStateChange?.("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}

// ---------------------------------------------------------------------------
// Hook React: la conversación del BackOffice
// ---------------------------------------------------------------------------

/** Mensaje renderizable: incluye los que no vinieron del servidor. */
export interface ChatBubble extends ChatMessage {
  /** `true` cuando el texto se está escribiendo token a token. */
  streaming?: boolean;
}

export interface UseChatSocketOptions {
  sessionId: string;
  locationId?: string;
  url?: string;
  authMode?: "frame" | "query";
}

export interface UseChatSocketResult {
  messages: ChatBubble[];
  connectionState: ChatConnectionState;
  reconnectAttempts: number;
  /** `true` mientras el agente está generando (pending de respuesta). */
  isGenerating: boolean;
  error: string | null;
  /** Envía un turno; si el agente está respondiendo, interrumpe y encadena. */
  send: (text: string) => void;
  /** Aborta la generación en curso dejando el parcial visible. */
  interrupt: () => void;
  clearError: () => void;
  reconnectNow: () => void;
}

function upsertMessage(current: ChatBubble[], next: ChatBubble): ChatBubble[] {
  const index = current.findIndex((message) => message.message_id === next.message_id);
  if (index === -1) {
    return [...current, next];
  }
  const copy = current.slice();
  copy[index] = { ...copy[index], ...next };
  return copy;
}

export function useChatSocket(options: UseChatSocketOptions): UseChatSocketResult {
  const [messages, setMessages] = useState<ChatBubble[]>([]);
  const [connectionState, setConnectionState] = useState<ChatConnectionState>("connecting");
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clientRef = useRef<ChatSocketClient | null>(null);
  const assemblerRef = useRef(new ChatTokenAssembler());
  const generatingRef = useRef(false);
  //: Turno que el encargado escribió mientras el agente respondía.
  const queuedInputRef = useRef<string | null>(null);

  // Opciones vigentes para (re)crear el cliente sin volver a declarar los
  // callbacks: se sincroniza en un efecto, nunca durante el render.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const createClient = useCallback((): ChatSocketClient => {
    return new ChatSocketClient({
      sessionId: optionsRef.current.sessionId,
      locationId: optionsRef.current.locationId,
      url: optionsRef.current.url,
      authMode: optionsRef.current.authMode,
      onStateChange: (state) => {
        setConnectionState(state);
        if (state === "open") {
          setReconnectAttempts(0);
        } else if (state === "reconnecting") {
          setReconnectAttempts((attempts) => attempts + 1);
        }
      },

      // Rehidratación: al (re)conectar el servidor manda el transcript
      // completo, incluidos los mensajes `interrupted`. Nunca se arranca con
      // un chat vacío si la sesión ya tenía conversación.
      onSnapshot: (snapshot) => {
        assemblerRef.current.reset();
        const restored: ChatBubble[] = (snapshot.messages ?? []).map((message) => {
          // Rehidrata el ensamblador con lo que el servidor ya mostró.
          assemblerRef.current.hydrate(message.message_id, message.content);
          return {
            ...message,
            // Un mensaje que quedó `streaming` en el servidor significa que el
            // proceso murió a mitad: se muestra como interrumpido, no en bucle.
            status: message.status === "streaming" ? "interrupted" : message.status,
            streaming: false,
          };
        });
        setMessages(restored);
        // Tras una reconexión el servidor retoma el control del turno: la
        // generación en curso (si la hay) llega por `generation_started`.
        generatingRef.current = false;
        setIsGenerating(false);
      },

      onUserMessage: (payload) => {
        setMessages((current) =>
          upsertMessage(current, {
            message_id: payload.message_id,
            role: "user",
            content: payload.text,
            status: "completed",
            sequence: current.length,
            created_at: new Date().toISOString(),
          }),
        );
      },

      onGenerationStarted: (payload) => {
        generatingRef.current = true;
        setIsGenerating(true);
        setMessages((current) =>
          upsertMessage(current, {
            message_id: payload.message_id,
            role: "assistant",
            content: assemblerRef.current.get(payload.message_id),
            status: "streaming",
            sequence: current.length,
            created_at: new Date().toISOString(),
            streaming: true,
          }),
        );
      },

      // Typewriter: se APPENDEA el token. Nunca se reemplaza el contenido.
      onTokenChunk: (payload) => {
        const content = assemblerRef.current.append(payload);
        setMessages((current) =>
          upsertMessage(current, {
            message_id: payload.message_id,
            role: "assistant",
            content,
            status: "streaming",
            sequence: current.length,
            created_at: new Date().toISOString(),
            streaming: true,
          }),
        );
      },

      // El parcial se queda visible y marcado: no se borra ni se sobrescribe.
      onGenerationInterrupted: (payload) => {
        generatingRef.current = false;
        setIsGenerating(false);
        setMessages((current) =>
          upsertMessage(current, {
            message_id: payload.message_id,
            role: "assistant",
            content: assemblerRef.current.get(payload.message_id),
            status: "interrupted",
            sequence: current.length,
            created_at: new Date().toISOString(),
            streaming: false,
          }),
        );
        // El texto redirigido ya viajó como `new_input` dentro del
        // `interrupt_requested`: el servidor abrió el turno nuevo. Reenviarlo
        // aquí lo duplicaría, así que sólo se descarta la marca.
        queuedInputRef.current = null;
      },

      onGenerationCompleted: (payload) => {
        generatingRef.current = false;
        setIsGenerating(false);
        setMessages((current) =>
          upsertMessage(current, {
            message_id: payload.message_id,
            role: "assistant",
            content: assemblerRef.current.get(payload.message_id),
            status: "completed",
            sequence: current.length,
            created_at: new Date().toISOString(),
            streaming: false,
          }),
        );
        queuedInputRef.current = null;
      },

      onGenerationFailed: (payload) => {
        generatingRef.current = false;
        setIsGenerating(false);
        setError("No pude completar la respuesta. Inténtalo de nuevo.");
        setMessages((current) =>
          upsertMessage(current, {
            message_id: payload.message_id,
            role: "assistant",
            content:
              assemblerRef.current.get(payload.message_id) ||
              "No pude completar esta consulta.",
            status: "failed",
            sequence: current.length,
            created_at: new Date().toISOString(),
            streaming: false,
          }),
        );
      },

      onError: (payload) => {
        setError(payload.message);
        if (payload.code === "nothing_to_interrupt") {
          // El turno terminó justo antes de la interrupción: el texto que el
          // encargado escribió no debe perderse, se manda como turno normal.
          const queued = queuedInputRef.current;
          queuedInputRef.current = null;
          if (queued) {
            generatingRef.current = false;
            setIsGenerating(false);
            clientRef.current?.sendUserMessage(queued);
          }
        }
      },
    });
  }, []);

  useEffect(() => {
    if (!options.sessionId) return;
    const client = createClient();
    clientRef.current = client;
    client.start();
    return () => {
      client.stop();
      clientRef.current = null;
    };
    // La sesión identifica el canal: al cambiarla hay que reconectar.
  }, [createClient, options.sessionId]);

  const send = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setError(null);

    if (generatingRef.current) {
      // Escribir mientras el agente responde = interrumpir + nuevo turno.
      // El texto viaja como `new_input`; el servidor abre el turno nuevo.
      queuedInputRef.current = trimmed;
      const asked = clientRef.current?.sendInterrupt(trimmed) ?? false;
      if (!asked) {
        // Canal no disponible: se descarta la marca para no reenviarlo dos veces.
        queuedInputRef.current = null;
        setError("Sin conexión con el asistente. Reintentando…");
      }
      return;
    }

    if (!clientRef.current?.sendUserMessage(trimmed)) {
      setError("Sin conexión con el asistente. Reintentando…");
    }
  }, []);

  const interrupt = useCallback(() => {
    if (!generatingRef.current) return;
    clientRef.current?.sendInterrupt();
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const reconnectNow = useCallback(() => {
    clientRef.current?.stop();
    const client = createClient();
    clientRef.current = client;
    client.start();
  }, [createClient]);

  return useMemo(
    () => ({
      messages,
      connectionState,
      reconnectAttempts,
      isGenerating,
      error,
      send,
      interrupt,
      clearError,
      reconnectNow,
    }),
    [
      messages,
      connectionState,
      reconnectAttempts,
      isGenerating,
      error,
      send,
      interrupt,
      clearError,
      reconnectNow,
    ],
  );
}
