"use client";

import { usePathname, useSearchParams } from "next/navigation";
import {
  Component,
  type ErrorInfo,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
} from "react";
import { telemetry } from "@/services/telemetry";

// ============================================================================
// Error Boundary — captura errores no controlados del frontend
// ============================================================================

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class TelemetryErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Determinar tipo de error
    let errorType = "ReactError";
    if (error instanceof TypeError) errorType = "TypeError";
    else if (error instanceof ReferenceError) errorType = "ReferenceError";

    telemetry.track("frontend_error_occurred", {
      page_path: typeof window !== "undefined" ? window.location.pathname : "",
      error_type: errorType,
      error_message: error.message.slice(0, 200),
    });
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[40vh] items-center justify-center px-4">
          <div className="rounded-xl border border-rose-400/30 bg-rose-400/10 px-6 py-8 text-center">
            <p className="text-lg font-bold text-rose-200">
              Algo salió mal
            </p>
            <p className="mt-2 text-sm text-rose-100/70">
              Ocurrió un error inesperado. El equipo de operaciones ya ha sido notificado.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-6 rounded-lg bg-rose-300 px-5 py-2 text-sm font-bold text-slate-900 transition hover:bg-rose-200"
            >
              Recargar página
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// ============================================================================
// Global error listeners — window.onerror / unhandledrejection
// ============================================================================

function useGlobalErrorListeners(): void {
  useEffect(() => {
    function handleOnError(event: ErrorEvent) {
      let errorType = "ReactError";
      if (["TypeError", "ReferenceError", "NetworkError", "ReactError"].includes(event.error?.name ?? "")) {
        errorType = event.error.name;
      }
      telemetry.track("frontend_error_occurred", {
        page_path: window.location.pathname,
        error_type: errorType,
        error_message: (event.message ?? "").slice(0, 200),
      });
    }

    function handleRejection(event: PromiseRejectionEvent) {
      // Mapeamos rechazos de promesas al enum permitido
      const reasonName = event.reason?.name ?? "";
      let errorType = "ReactError";
      if (["TypeError", "ReferenceError", "NetworkError", "ReactError"].includes(reasonName)) {
        errorType = reasonName;
      } else if (event.reason instanceof TypeError) {
        errorType = "TypeError";
      } else if (event.reason instanceof ReferenceError) {
        errorType = "ReferenceError";
      } else {
        // La mayoría de PromiseRejection son errores de red
        errorType = "NetworkError";
      }
      telemetry.track("frontend_error_occurred", {
        page_path: window.location.pathname,
        error_type: errorType,
        error_message: (event.reason?.message ?? String(event.reason)).slice(
          0,
          200,
        ),
      });
    }

    window.addEventListener("error", handleOnError);
    window.addEventListener("unhandledrejection", handleRejection);

    return () => {
      window.removeEventListener("error", handleOnError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);
}

// ============================================================================
// Page view tracking — rastrea navegación en backoffice
// ============================================================================

function usePageViewTracking(): void {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const prevPathRef = useRef<string>("");

  useEffect(() => {
    const currentPath = pathname + (searchParams.toString() ? `?${searchParams.toString()}` : "");
    const referrer = prevPathRef.current || document.referrer || "";

    // Solo rastrear páginas del backoffice
    if (currentPath.startsWith("/backoffice")) {
      telemetry.track("page_visited", {
        page_path: currentPath,
        referrer_path: referrer,
        country: "",
      });
    }

    prevPathRef.current = currentPath;
  }, [pathname, searchParams]);
}

// ============================================================================
// Web Vitals — reportWebVitals vía telemetría
// ============================================================================

function useWebVitalsTracking(): void {
  useEffect(() => {
    if (typeof window === "undefined") return;

    // Cargar web-vitals desde dependencia del proyecto
    import("web-vitals").then(({ onCLS, onFCP, onINP, onLCP, onTTFB }) => {
      const sendMetric = (metric: { name: string; value: number }) => {
        telemetry.track("web_vital_recorded", {
          page_path: window.location.pathname,
          metric_name: metric.name,
          metric_value: metric.value,
        });
      };

      onCLS(sendMetric);
      onFCP(sendMetric);
      onINP(sendMetric);
      onLCP(sendMetric);
      onTTFB(sendMetric);
    }).catch(() => {
      // web-vitals no crítico; si falla la carga, se ignora silenciosamente
    });
  }, []);
}

// ============================================================================
// API request failure tracking (wraps authenticatedApiFetch)
// ============================================================================

/** Decorador para rastrear fallos de peticiones fetch a la API. */
export function trackApiError(
  endpoint: string,
  method: string,
  error: unknown,
): void {
  let errorType = "server_error";
  let statusCode = 0;

  if (error && typeof error === "object" && "status" in error) {
    const s = (error as { status: number }).status;
    statusCode = s;
    if (s >= 400 && s < 500) errorType = "http_4xx";
    else if (s >= 500) errorType = "server_error";
  }

  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof (error as { message: string }).message === "string"
  ) {
    const msg = (error as { message: string }).message;
    if (
      msg.includes("conectar") ||
      msg.includes("timeout") ||
      msg.includes("Network")
    ) {
      errorType = "network_timeout";
    }
  }

  telemetry.track("error_api_request_failure", {
    endpoint,
    method,
    error_type: errorType,
    status_code: statusCode,
    retry_attempted: false,
  });
}

// ============================================================================
// Provider principal — envuelve el backoffice entero
// ============================================================================

interface TelemetryProviderProps {
  children: ReactNode;
}

export default function TelemetryProvider({
  children,
}: TelemetryProviderProps) {
  useGlobalErrorListeners();
  usePageViewTracking();
  useWebVitalsTracking();

  return (
    <TelemetryErrorBoundary>{children}</TelemetryErrorBoundary>
  );
}