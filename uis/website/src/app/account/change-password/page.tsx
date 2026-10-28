"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { ApiError, changePassword } from "@/lib/auth";

export default function ChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmation) {
      setError("La nueva contraseña y su confirmación no coinciden.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setMessage("Contraseña actualizada correctamente.");
    } catch (caughtError) {
      if (caughtError instanceof ApiError && caughtError.status === 400) {
        setError("La contraseña actual no es correcta.");
      } else {
        setError(caughtError instanceof Error ? caughtError.message : "No se pudo cambiar la contraseña.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 p-4 text-slate-100 sm:p-8">
      <section className="w-full max-w-lg rounded-3xl border border-orange-300/25 bg-slate-900 p-8 shadow-2xl shadow-orange-950/30 sm:p-10">
        <Link href="/backoffice" className="text-sm font-bold uppercase tracking-[0.2em] text-orange-300">Brasaland · Backoffice</Link>
        <p className="mt-10 text-xs font-bold uppercase tracking-[0.2em] text-orange-200">Seguridad</p>
        <h1 className="mt-3 text-3xl font-black text-white">Cambiar contraseña</h1>
        <form onSubmit={handleSubmit} className="mt-8 space-y-5">
          <label className="block text-sm font-semibold text-slate-200" htmlFor="current-password">Contraseña actual<input id="current-password" type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" /></label>
          <label className="block text-sm font-semibold text-slate-200" htmlFor="new-password">Nueva contraseña<input id="new-password" type="password" autoComplete="new-password" minLength={8} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" /></label>
          <label className="block text-sm font-semibold text-slate-200" htmlFor="password-confirmation">Confirmar nueva contraseña<input id="password-confirmation" type="password" autoComplete="new-password" minLength={8} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" /></label>
          {error && <p role="alert" className="rounded-xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</p>}
          {message && <p role="status" className="rounded-xl border border-emerald-400/40 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">{message}</p>}
          <button type="submit" disabled={submitting} className="w-full rounded-xl bg-orange-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-orange-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 disabled:cursor-not-allowed disabled:opacity-60">{submitting ? "Actualizando…" : "Actualizar contraseña"}</button>
        </form>
      </section>
    </main>
  );
}
