"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, login } from "@/lib/auth";
import { telemetry } from "@/services/telemetry";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message] = useState<string | null>(() =>
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("reset") === "success"
      ? "Contraseña restablecida. Ya puedes iniciar sesión."
      : null,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await login(email.trim(), password);
      telemetry.track("auth_login_attempted", {
        success: true,
        ip_country: "",
      });
      router.replace("/backoffice");
    } catch (caughtError) {
      if (caughtError instanceof ApiError && caughtError.status === 401) {
        telemetry.track("auth_login_attempted", {
          success: false,
          failure_reason: "invalid_credentials",
          ip_country: "",
        });
      } else {
        // Error de red u otro: no enviamos failure_reason porque
        // el enum del schema solo permite: invalid_credentials, account_locked, inactive_account
        telemetry.track("auth_login_attempted", {
          success: false,
          ip_country: "",
        });
      }
      if (caughtError instanceof ApiError && caughtError.status === 401) {
        setError("El email o la contraseña no son correctos.");
      } else {
        setError(caughtError instanceof Error ? caughtError.message : "No fue posible iniciar sesión.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-stone-950 px-4 py-8 text-stone-100 sm:place-items-center sm:p-8">
      <section className="grid w-full max-w-4xl overflow-hidden rounded-3xl border border-orange-300/25 bg-slate-900 shadow-2xl shadow-orange-950/30 md:grid-cols-[0.82fr_1.18fr]">
        <aside className="bg-gradient-to-br from-orange-500 via-orange-700 to-stone-950 p-8 sm:p-10">
          <Link href="/" className="text-sm font-bold uppercase tracking-[0.2em] text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white">
            Brasaland
          </Link>
          <div className="mt-20 max-w-xs">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-orange-100">Área operativa</p>
            <h1 className="mt-4 text-4xl font-black leading-none text-white">Vuelve a la cocina.</h1>
            <p className="mt-5 text-sm leading-6 text-orange-50">Accede a las herramientas internas de proveedores e incidencias.</p>
          </div>
        </aside>

        <div className="p-8 sm:p-10">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-orange-300">Iniciar sesión</p>
          <h2 className="mt-3 text-3xl font-black text-white">Tu turno empieza aquí</h2>
          <p className="mt-2 text-sm text-slate-300">Introduce tus datos de acceso para abrir el backoffice.</p>

          <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
            <label className="block text-sm font-semibold text-slate-200" htmlFor="email">
              Email
              <input id="email" name="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
            </label>
            <label className="block text-sm font-semibold text-slate-200" htmlFor="password">
              Contraseña
              <input id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
            </label>

            {error && <p role="alert" className="rounded-xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</p>}
            {message && <p role="status" className="rounded-xl border border-emerald-400/40 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">{message}</p>}

            <button type="submit" disabled={isSubmitting} className="w-full rounded-xl bg-orange-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-orange-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 disabled:cursor-not-allowed disabled:opacity-60">
              {isSubmitting ? "Accediendo…" : "Entrar al backoffice"}
            </button>
          </form>

          <p className="mt-4 text-right text-sm"><Link href="/forgot-password" className="font-semibold text-orange-300 underline underline-offset-4 hover:text-orange-200">¿Olvidaste tu contraseña?</Link></p>
          <p className="mt-6 text-sm text-slate-300">¿Aún no tienes cuenta? <Link href="/auth/register" className="font-semibold text-orange-300 underline underline-offset-4 hover:text-orange-200">Crear una cuenta</Link></p>
        </div>
      </section>
    </main>
  );
}
