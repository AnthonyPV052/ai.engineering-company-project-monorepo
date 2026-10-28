"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, resetPassword } from "@/lib/auth";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token] = useState(() =>
    typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("token") ?? "",
  );
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirmation) {
      setError("La nueva contraseña y su confirmación no coinciden.");
      return;
    }
    if (!token) {
      setError("El enlace de restablecimiento no es válido. Solicita uno nuevo.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await resetPassword(token, password);
      router.replace("/login?reset=success");
    } catch (caughtError) {
      if (caughtError instanceof ApiError && caughtError.status === 400) {
        setError("El enlace no es válido, ya fue usado o ha caducado. Solicita uno nuevo.");
      } else {
        setError(caughtError instanceof Error ? caughtError.message : "No se pudo restablecer la contraseña.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-stone-950 p-4 text-stone-100 sm:p-8">
      <section className="w-full max-w-lg rounded-3xl border border-orange-300/25 bg-slate-900 p-8 shadow-2xl shadow-orange-950/30 sm:p-10">
        <Link href="/" className="text-sm font-bold uppercase tracking-[0.2em] text-orange-300">Brasaland</Link>
        <p className="mt-10 text-xs font-bold uppercase tracking-[0.2em] text-orange-200">Nueva contraseña</p>
        <h1 className="mt-3 text-3xl font-black text-white">Elige una contraseña nueva</h1>
        <form onSubmit={handleSubmit} className="mt-8 space-y-5">
          <label className="block text-sm font-semibold text-slate-200" htmlFor="password">
            Nueva contraseña
            <input id="password" type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
          </label>
          <label className="block text-sm font-semibold text-slate-200" htmlFor="confirmation">
            Confirmar nueva contraseña
            <input id="confirmation" type="password" autoComplete="new-password" minLength={8} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
          </label>
          {error && <p role="alert" className="rounded-xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</p>}
          <button type="submit" disabled={submitting} className="w-full rounded-xl bg-orange-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-orange-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 disabled:cursor-not-allowed disabled:opacity-60">{submitting ? "Restableciendo…" : "Restablecer contraseña"}</button>
        </form>
        <p className="mt-6 text-sm text-slate-300"><Link href="/forgot-password" className="font-semibold text-orange-300 underline underline-offset-4 hover:text-orange-200">Solicitar otro enlace</Link></p>
      </section>
    </main>
  );
}
