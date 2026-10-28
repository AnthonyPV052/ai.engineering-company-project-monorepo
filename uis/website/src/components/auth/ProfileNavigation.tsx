"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AUTH_SESSION_CLEARED_EVENT, getCurrentUser } from "@/lib/auth";

function ProfileIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <circle cx="12" cy="8" r="3.25" />
      <path d="M5 20c.8-3.45 3.1-5.2 7-5.2s6.2 1.75 7 5.2" strokeLinecap="round" />
    </svg>
  );
}

export default function ProfileNavigation() {
  const [hasIncompleteProfile, setHasIncompleteProfile] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadProfileStatus() {
      try {
        const user = await getCurrentUser();
        const profile = user.profile;
        const isIncomplete = !profile || !profile.name?.trim() || !profile.phone?.trim() || !profile.address?.trim();
        if (active) setHasIncompleteProfile(isIncomplete);
      } catch {
        // The route guard owns session invalidation and redirection.
      }
    }

    void loadProfileStatus();
    const reloadProfileStatus = () => void loadProfileStatus();
    window.addEventListener("brasaland:profile-updated", reloadProfileStatus);
    window.addEventListener(AUTH_SESSION_CLEARED_EVENT, reloadProfileStatus);

    return () => {
      active = false;
      window.removeEventListener("brasaland:profile-updated", reloadProfileStatus);
      window.removeEventListener(AUTH_SESSION_CLEARED_EVENT, reloadProfileStatus);
    };
  }, []);

  return (
    <div className="group relative">
      <Link href="/backoffice/profile" aria-label="Perfil de usuario" className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 text-slate-100 transition hover:border-orange-300 hover:text-orange-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300">
        <ProfileIcon />
        {hasIncompleteProfile && <span aria-label="Rellena los campos opcionales" className="absolute right-0.5 top-0.5 h-2.5 w-2.5 rounded-full bg-amber-300 ring-2 ring-slate-950" />}
      </Link>
      {hasIncompleteProfile && <div role="tooltip" className="pointer-events-none absolute right-0 top-12 z-50 w-max max-w-56 rounded-lg bg-amber-100 px-3 py-2 text-xs font-semibold text-slate-950 opacity-0 shadow-lg transition group-hover:opacity-100 group-focus-within:opacity-100">Rellena los campos opcionales</div>}
    </div>
  );
}
