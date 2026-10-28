import type { ReactNode } from "react";
import Link from "next/link";
import LogoutButton from "@/components/auth/LogoutButton";
import ProfileNavigation from "@/components/auth/ProfileNavigation";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import TelemetryProvider from "@/components/TelemetryProvider";
import BackofficeSidebar from "@/components/backoffice/BackofficeSidebar";

export default function BackofficeLayout({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute>
      <TelemetryProvider>
        <div className="min-h-screen bg-slate-950 text-slate-100 antialiased">
          <header className="border-b border-slate-800 bg-slate-950/90">
            <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
              <p className="text-sm font-bold uppercase tracking-[0.18em] text-orange-200">Brasaland · Backoffice</p>
              <div className="flex items-center gap-3">
                <Link
                  href="/backoffice"
                  aria-label="Volver al inicio del backoffice"
                  className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 text-slate-100 transition hover:border-orange-300 hover:text-orange-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                    <path d="m4 11 8-7 8 7v8a1 1 0 0 1-1 1h-4v-5H9v5H5a1 1 0 0 1-1-1z" strokeLinejoin="round" />
                  </svg>
                </Link>
                <ProfileNavigation />
                <LogoutButton />
              </div>
            </div>
          </header>
          <div className="mx-auto flex w-full max-w-7xl items-start">
            <BackofficeSidebar />
            <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
          </div>
        </div>
      </TelemetryProvider>
    </ProtectedRoute>
  );
}
