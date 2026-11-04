"use client";

/* ========================================================================
   Cliente SSE para tickets de RFP — Brasaland Dashboard en tiempo real
   ========================================================================
   Parte 1 — Sistemas en Tiempo Real.

   Consume GET /api/rfp/events/stream usando fetch + ReadableStream en lugar
   de EventSource: necesitamos mandar el JWT del BackOffice en un header
   `Authorization: Bearer …`, y EventSource no permite headers de auth
   personalizados de forma limpia.

   Estrategia de recuperación (documentada en docs/sse-notifications.es.md):
   - El servidor emite cada evento con `id: <ticket_id>` y mantiene un replay
     corto (ring buffer). Al reconectar enviamos el header estándar SSE
     `Last-Event-ID` con el último ticket procesado, de modo que el servidor
     re-emite los eventos perdidos mientras estábamos desconectados.
   - Al reconectar (backoff exponencial) el consumidor también dispara un
     refetch de la lista de tickets como red de seguridad.
   - La UI deduplica por `ticket_id``: un ticket re-emitido o ya presente en
     la lista no aparece dos veces.
   ======================================================================== */

import { useCallback, useEffect, useRef, useState } from "react";
import { getStoredToken } from "./auth";

// ---------------------------------------------------------------------------
// Tipos (misma nomenclatura que el backend / systema de RFPs)
// ---------------------------------------------------------------------------

/** Evento SSE `rfp_ticket_created` — payload directo (sin sobre anidado). */
export interface RfpTicketCreatedEvent {
  ticket_id: string;
  status: string;
  created_at: string;
  client_name?: string | null;
  location?: string | null;
  service_type?: string | null;
  scope?: string | null;
  deadline?: string | null;
  budget_range?: string | null;
  departments_needed?: string[];
}

/** Frames ya parseados del wire SSE. */
export interface SseParsedEvent {
  event: string | null;
  id: string | null;
  data: string;
}

export type RfpSseConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "closed";

// ---------------------------------------------------------------------------
// Parseo del framing SSE
// ---------------------------------------------------------------------------

export function parseSseFrames(raw: string): SseParsedEvent[] {
  const frames: SseParsedEvent[] = [];
  let currentEvent: string | null = null;
  let currentId: string | null = null;
  const dataLines: string[] = [];

  const flush = () => {
    if (dataLines.length > 0 || currentEvent !== null) {
      frames.push({
        event: currentEvent,
        id: currentId,
        data: dataLines.join("\n"),
      });
    }
    dataLines.length = 0;
    currentId = null;
    currentEvent = null;
  };

  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (trimmed === "") {
      flush();
      continue;
    }
    if (trimmed.startsWith(":")) {
      continue; // comentario keep-alive del servidor
    }
    if (line.startsWith("event:")) {
      currentEvent = line.slice("event:".length).trim();
    } else if (line.startsWith("id:")) {
      currentId = line.slice("id:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (dataLines.length > 0 || currentEvent !== null) {
    flush();
  }

  return frames;
}

// ---------------------------------------------------------------------------
// Configuración del cliente
// ---------------------------------------------------------------------------

const LAST_EVENT_ID_KEY = "brasaland.rfp.sse.lastEventId";
const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 15_000;
const EVENT_ID_FIELD = "rfp_ticket_created";

export interface SseRfpClientOptions {
  /** URL del stream (por defecto /api/rfp/events/stream con rewrites de Next). */
  url?: string;
  /** Callback ante cada evento de ticket nuevo. */
  onTicketCreated?: (event: RfpTicketCreatedEvent) => void;
  /** Callback cuando el stream queda establecido (replay entregado). */
  onConnected?: (replayCount: number) => void;
  /** Callback cuando la conexión cae (backoff disparado). */
  onReconnecting?: (attempt: number) => void;
  /** Callback de cambios de estado (para la UI). */
  onStateChange?: (state: RfpSseConnectionState) => void;
}

function getLastEventId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(LAST_EVENT_ID_KEY);
}

function rememberLastEventId(id: string | null): void {
  if (typeof window === "undefined" || !id) return;
  window.localStorage.setItem(LAST_EVENT_ID_KEY, id);
}

function clearLastEventId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(LAST_EVENT_ID_KEY);
}

// ---------------------------------------------------------------------------
// Cliente SSE con fetch + ReadableStream
// ---------------------------------------------------------------------------

export class SseRfpClient {
  private options: SseRfpClientOptions;
  private controller: AbortController | null = null;
  private stopped = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastEventId = getLastEventId();

  constructor(options: SseRfpClientOptions) {
    this.options = options;
  }

  start(): void {
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
    this.options.onStateChange?.("closed");
  }

  /** Devuelve el último ticket_id procesado (para diagnóstico/UI). */
  getLastEventId(): string | null {
    return this.lastEventId;
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;

    const token = getStoredToken();
    if (!token) {
      // Sin token no hay stream; el guard de la página redirigirá al login.
      this.options.onStateChange?.("closed");
      return;
    }

    const url =
      this.options.url ?? "/api/rfp/events/stream";
    const controller = new AbortController();
    this.controller = controller;

    const headers: Record<string, string> = {
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
    };
    if (this.lastEventId) {
      headers["Last-Event-ID"] = this.lastEventId;
    }

    this.options.onStateChange?.(
      this.reconnectAttempt > 0 ? "reconnecting" : "connecting",
    );

    try {
      const response = await fetch(url, {
        method: "GET",
        headers,
        signal: controller.signal,
        cache: "no-store",
      });

      if (!response.ok) {
        if (response.status === 401) {
          // Sesión caducada: no reintentar en bucle; la página limpiará el
          // token y redirigirá al login.
          this.options.onStateChange?.("closed");
          return;
        }
        throw new Error(`SSE HTTP ${response.status}`);
      }

      if (!response.body) {
        throw new Error("SSE: la respuesta no tiene body de stream");
      }

      // Stream establecido: el backoff se reinicia en el callback connected.
      this.reconnectAttempt = 0;
      await this.readStream(response.body, controller);
    } catch (caught) {
      if (this.stopped) return;
      if (controller.signal.aborted) return;
      this.scheduleReconnect();
      return;
    }

    // El stream se cerró limpiamente (server desconectó): reconectar.
    if (!this.stopped) {
      this.scheduleReconnect();
    }
  }

  private async readStream(
    body: ReadableStream<Uint8Array>,
    controller: AbortController,
  ): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let chunkIndex: number;
        while ((chunkIndex = buffer.indexOf("\n\n")) !== -1) {
          const frameText = buffer.slice(0, chunkIndex);
          buffer = buffer.slice(chunkIndex + 2);
          this.dispatchFrames(parseSseFrames(frameText));
        }
      }
    } finally {
      reader.releaseLock();
      // Abortar el fetch para liberar la conexión al terminar la lectura.
      if (!controller.signal.aborted) {
        controller.abort();
      }
    }
  }

  private dispatchFrames(frames: SseParsedEvent[]): void {
    for (const frame of frames) {
      if (!frame.event) continue;

      if (frame.event === "connected") {
        let replayCount = 0;
        try {
          const payload = JSON.parse(frame.data) as { replay_count?: number };
          replayCount = payload.replay_count ?? 0;
        } catch {
          // payload de control no-JSON: ignorar campos de control
        }
        this.options.onConnected?.(replayCount);
        continue;
      }

      if (frame.event === EVENT_ID_FIELD) {
        try {
          const payload = JSON.parse(frame.data) as RfpTicketCreatedEvent;
          if (!payload?.ticket_id) continue;
          const eventId = frame.id ?? payload.ticket_id;
          this.lastEventId = eventId;
          rememberLastEventId(eventId);
          this.options.onTicketCreated?.(payload);
        } catch {
          // frame malformado: ignorar
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;

    const delay = Math.min(
      INITIAL_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    );
    this.reconnectAttempt += 1;
    this.options.onStateChange?.("reconnecting");
    this.options.onReconnecting?.(this.reconnectAttempt);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }
}

// ---------------------------------------------------------------------------
// Hook React: uso del dashboard
// ---------------------------------------------------------------------------

export interface RfpNotificationItem {
  ticket_id: string;
  status: string;
  created_at: string;
  client_name?: string | null;
  service_type?: string | null;
  location?: string | null;
  scope?: string | null;
  deadline?: string | null;
  budget_range?: string | null;
  departments_needed?: string[];
  received_at: number;
}

export interface UseRfpSseOptions {
  url?: string;
  /** Cache de ticket ids ya conocidos (para deduplicar en la UI). */
  knownTicketIds: { current: Set<string> };
  /** Se llama al recibir un ticket nuevo NO duplicado. */
  onNewTicket?: (event: RfpTicketCreatedEvent) => void;
  /** Se llama tras (re)conectar el stream — ideal para refetch de la lista. */
  onReconnected?: () => void;
  /** Se llama cuando el stream cae (disparo del backoff). */
  onReconnecting?: () => void;
}

export function useRfpSse(options: UseRfpSseOptions): {
  connectionState: RfpSseConnectionState;
  reconnectAttempts: number;
  notifications: RfpNotificationItem[];
  clearNotifications: () => void;
  restart: () => void;
} {
  const [connectionState, setConnectionState] =
    useState<RfpSseConnectionState>("connecting");
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [notifications, setNotifications] = useState<RfpNotificationItem[]>([]);

  const optionsRef = useRef(options);
  optionsRef.current = options;
  const seenTicketIds = useRef<Set<string>>(new Set());
  const clientRef = useRef<SseRfpClient | null>(null);

  const createClient = useCallback((): SseRfpClient => {
    const client = new SseRfpClient({
      url: optionsRef.current.url,
      onStateChange: setConnectionState,
      onReconnecting: (attempt) => {
        setReconnectAttempts(attempt);
        optionsRef.current.onReconnecting?.();
      },
      onConnected: (replayCount) => {
        setReconnectAttempts(0);
        setConnectionState("connected");
        // Tras (re)conectarnos, refetch de la lista para reconciliar.
        optionsRef.current.onReconnected?.();
      },
      onTicketCreated: (event) => {
        const known = optionsRef.current.knownTicketIds.current;
        if (
          seenTicketIds.current.has(event.ticket_id) ||
          known.has(event.ticket_id)
        ) {
          // Duplicado (replay o ya presente en la lista): no pintar dos veces.
          return;
        }
        seenTicketIds.current.add(event.ticket_id);
        setNotifications((prev) => [
          {
            ...event,
            received_at: Date.now(),
          },
          ...prev,
        ]);
        optionsRef.current.onNewTicket?.(event);
      },
    });
    return client;
  }, []);

  useEffect(() => {
    const client = createClient();
    clientRef.current = client;
    client.start();

    return () => {
      client.stop();
      clientRef.current = null;
    };
  }, [createClient]);

  const restart = useCallback(() => {
    setNotifications([]);
    seenTicketIds.current.clear();
    clientRef.current?.stop();
    setReconnectAttempts(0);
    // Reactiva la conexión desde cero.
    const client = createClient();
    clientRef.current = client;
    client.start();
  }, [createClient]);

  return {
    connectionState,
    reconnectAttempts,
    notifications,
    clearNotifications: () => setNotifications([]),
    restart,
  };
}