/* ========================================================================
   Servicio de Telemetría — Frontend Brasaland
   ========================================================================
   Único punto de entrada para el envío de eventos desde el frontend.
   Todo el tracking debe pasar por `telemetry.track()`.
   Prohibido usar fetch/axios directamente para telemetría.
   ======================================================================== */

// ---------------------------------------------------------------------------
// Constantes
// ---------------------------------------------------------------------------

const SCHEMA_VERSION = "1.0";
const BATCH_INTERVAL_MS = 10_000;
const BATCH_MAX_SIZE = 20;
const MAX_RETRIES = 3;
const RETRY_DELAYS: readonly number[] = [500, 1_000, 2_000];
const SESSION_STORAGE_KEY = "brasaland.telemetry.sessionId";
const USER_ID_STORAGE_KEY = "brasaland.telemetry.userId";

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------

export interface TelemetryEvent {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string;
  eventType: string;
  schemaVersion: string;
  requestId: string;
  properties: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

function generateUUID(): string {
  return crypto.randomUUID();
}

function getOrCreateSessionId(): string {
  if (typeof sessionStorage === "undefined") return "";
  let sessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!sessionId) {
    sessionId = generateUUID();
    try {
      sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    } catch {
      // sessionStorage puede no estar disponible (entornos restringidos)
    }
  }
  return sessionId;
}

function getStoredUserId(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(USER_ID_STORAGE_KEY) ?? "";
}

// ---------------------------------------------------------------------------
// Servicio
// ---------------------------------------------------------------------------

class TelemetryService {
  private queue: TelemetryEvent[] = [];
  private timerId: ReturnType<typeof setTimeout> | null = null;
  private userId: string = "";
  private sessionId: string = "";
  private endpoint: string = "";

  constructor() {
    if (typeof window === "undefined") return;

    this.endpoint =
      process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT ?? "";

    if (!this.endpoint) {
      console.warn(
        "[Telemetry] NEXT_PUBLIC_TELEMETRY_ENDPOINT no está configurada.",
      );
    }

    this.sessionId = getOrCreateSessionId();
    this.userId = getStoredUserId();

    // Flush confiable con sendBeacon al cerrar / cambiar de pestaña
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden" && this.queue.length > 0) {
        this.flushViaBeacon();
      }
    });
  }

  // -----------------------------------------------------------------------
  // API pública
  // -----------------------------------------------------------------------

  setUserId(id: string): void {
    this.userId = id;
    if (typeof localStorage !== "undefined") {
      try {
        localStorage.setItem(USER_ID_STORAGE_KEY, id);
      } catch {
        // localStorage puede no estar disponible
      }
    }
  }

  /** Lee el userId actual (útil para componentes que lo necesiten). */
  getUserId(): string {
    return this.userId;
  }

  /** Lee el sessionId actual. */
  getSessionId(): string {
    return this.sessionId;
  }

  /**
   * Única función pública para registrar un evento de telemetría.
   * Construye el envelope automáticamente.
   */
  track(
    eventType: string,
    properties: Record<string, unknown> = {},
  ): void {
    const event: TelemetryEvent = {
      eventId: generateUUID(),
      timestamp: new Date().toISOString(),
      sessionId: this.sessionId,
      userId: this.userId,
      eventType,
      schemaVersion: SCHEMA_VERSION,
      requestId: "",
      properties,
    };

    this.queue.push(event);

    console.debug(
      `[Telemetry] track → ${eventType} (cola: ${this.queue.length})`,
    );

    if (this.queue.length >= BATCH_MAX_SIZE) {
      void this.flush();
    } else if (!this.timerId) {
      this.startTimer();
    }
  }

  /** Fuerza el envío inmediato de la cola (útil para debugging). */
  forceFlush(): void {
    if (this.queue.length > 0) {
      console.debug(
        `[Telemetry] forceFlush → enviando ${this.queue.length} eventos`,
      );
      void this.flush();
    }
  }

  // -----------------------------------------------------------------------
  // Internos
  // -----------------------------------------------------------------------

  private startTimer(): void {
    this.timerId = setTimeout(() => {
      void this.flush();
    }, BATCH_INTERVAL_MS);
  }

  private clearTimer(): void {
    if (this.timerId !== null) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
  }

  private async flush(): Promise<void> {
    this.clearTimer();

    if (this.queue.length === 0) return;
    if (!this.endpoint) return;

    const batch = this.queue.splice(0);
    const requestId = generateUUID();

    const eventsWithRequestId = batch.map((e) => ({ ...e, requestId }));

    await this.sendWithRetry(eventsWithRequestId);
  }

  private async sendWithRetry(
    events: TelemetryEvent[],
    attempt: number = 0,
  ): Promise<void> {
    try {
      const response = await fetch(this.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      console.debug(
        `[Telemetry] Lote enviado OK: ${events.length} eventos (intento ${attempt + 1})`,
      );
    } catch (error) {
      if (attempt < MAX_RETRIES - 1) {
        const delay =
          attempt < RETRY_DELAYS.length
            ? RETRY_DELAYS[attempt]
            : RETRY_DELAYS[RETRY_DELAYS.length - 1];

        console.warn(
          `[Telemetry] Error (intento ${attempt + 1}/${MAX_RETRIES}), reintentando en ${delay}ms`,
        );

        await new Promise((resolve) => setTimeout(resolve, delay));
        return this.sendWithRetry(events, attempt + 1);
      }

      console.error(
        `[Telemetry] Lote descartado tras ${MAX_RETRIES} intentos (${events.length} eventos perdidos)`,
      );
    }
  }

  private flushViaBeacon(): void {
    this.clearTimer();

    if (this.queue.length === 0) return;
    if (!this.endpoint) return;

    const batch = this.queue.splice(0);
    const requestId = generateUUID();

    const eventsWithRequestId = batch.map((e) => ({ ...e, requestId }));
    const blob = new Blob([JSON.stringify({ events: eventsWithRequestId })], {
      type: "application/json",
    });

    const sent = navigator.sendBeacon(this.endpoint, blob);

    if (!sent) {
      this.sendWithRetry(eventsWithRequestId);
    }
  }
}

// ---------------------------------------------------------------------------
// Export — singleton
// ---------------------------------------------------------------------------

export const telemetry = new TelemetryService();

// ---------------------------------------------------------------------------
// Global para debugging desde consola DevTools
// ---------------------------------------------------------------------------

if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).telemetry = telemetry;
}