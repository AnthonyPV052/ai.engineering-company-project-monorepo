import Link from "next/link";
import { redirect } from "next/navigation";

export default function Home() {
  const autoRedirectToList = false;

  if (autoRedirectToList) {
    redirect("/listOfCandidates");
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-slate-950 px-4 py-10 md:px-8">
      <div className="pointer-events-none absolute -left-20 top-12 h-64 w-64 rounded-full bg-teal-500/20 blur-3xl" />
      <div className="pointer-events-none absolute bottom-8 right-4 h-72 w-72 rounded-full bg-cyan-500/20 blur-3xl" />

      <section className="relative mx-auto flex min-h-[80vh] w-full max-w-5xl items-center justify-center rounded-3xl border border-white/10 bg-white/[0.04] p-6 shadow-2xl backdrop-blur md:p-12">
        <div className="max-w-3xl text-center md:text-left">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-teal-300">
            Brasaland Digital
          </p>
          <h1 className="text-4xl font-black leading-tight text-white md:text-6xl">
            Talent Pipeline Tracker
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-relaxed text-slate-200 md:text-lg">
            Panel operativo para gestionar el proceso completo de selección del
            puesto de Asistente de Dirección, desde la recepción de candidaturas
            hasta la etapa de oferta.
          </p>

          <div className="mt-8 flex flex-col items-center gap-4 sm:flex-row md:items-start">
            <Link
              href="/listOfCandidates"
              className="inline-flex h-12 items-center justify-center rounded-xl bg-teal-500 px-6 text-base font-semibold text-slate-950 transition hover:bg-teal-400"
            >
              Ir al listado de candidaturas
            </Link>
            <span className="inline-flex h-12 items-center rounded-xl border border-white/15 px-5 text-sm text-slate-300">
              Vacante activa: Asistente de Dirección
            </span>
          </div>
        </div>
      </section>
    </main>
  );
}
