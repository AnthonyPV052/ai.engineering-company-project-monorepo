"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { telemetry } from "@/services/telemetry";
import {
  AUTH_SESSION_CLEARED_EVENT,
  clearToken,
  getCurrentUser,
  getStoredToken,
} from "@/lib/auth";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [isAuthorized, setIsAuthorized] = useState(false);

  useEffect(() => {
    let active = true;

    async function validateSession() {
      if (!getStoredToken()) {
        router.replace("/auth/login");
        return;
      }

      try {
        const user = await getCurrentUser();
        telemetry.setUserId(user.id);
        if (active) {
          setIsAuthorized(true);
        }
      } catch {
        // Sesión expirada — rastrear evento
        telemetry.track("session_expired", {
          time_since_last_activity: 0,
          page_before_expiry: window.location.pathname,
        });
        clearToken();
        router.replace("/auth/login");
      }
    }

    void validateSession();
    const redirectAfterSessionCleared = () => router.replace("/auth/login");
    window.addEventListener(AUTH_SESSION_CLEARED_EVENT, redirectAfterSessionCleared);

    return () => {
      active = false;
      window.removeEventListener(AUTH_SESSION_CLEARED_EVENT, redirectAfterSessionCleared);
    };
  }, [router]);

  if (!isAuthorized) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-950 px-6 text-slate-200">
        <p className="text-sm font-medium">Comprobando tu sesión…</p>
      </div>
    );
  }

  return <>{children}</>;
}
