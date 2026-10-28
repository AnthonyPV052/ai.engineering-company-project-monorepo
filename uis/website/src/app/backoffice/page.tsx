import dynamic from "next/dynamic";

const DashboardMetrics = dynamic(
  () => import("@/components/DashboardMetrics"),
  {
    loading: () => (
      <div className="flex items-center justify-center py-20 text-sm text-slate-400">
        Cargando dashboard…
      </div>
    ),
  },
);

export default function BackofficeHomePage() {

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-3xl border border-cyan-300/20 bg-gradient-to-br from-slate-900 via-cyan-950 to-orange-900 p-8 sm:p-12">
        <div className="absolute -right-20 -top-10 h-64 w-64 rounded-full bg-cyan-400/20 blur-3xl" aria-hidden="true" />
        <div className="absolute -bottom-16 -left-16 h-64 w-64 rounded-full bg-orange-400/20 blur-3xl" aria-hidden="true" />

        <div className="relative z-10 max-w-3xl space-y-6">
          <p className="inline-flex rounded-full border border-cyan-200/40 bg-cyan-200/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100">
            Backoffice Brasaland
          </p>
          <h1 className="text-4xl font-black leading-tight text-white sm:text-5xl lg:text-6xl">
            Panel operativo con datos de muestra listos para explorar
          </h1>
          <p className="max-w-2xl text-base text-slate-200 sm:text-lg">
            Esta vista usa los tipos, utilidades y data del directorio src para transformar informacion de ventas,
            locaciones y menu en metricas accionables.
          </p>
        </div>
      </section>

      <DashboardMetrics />
    </div>
  );
}
