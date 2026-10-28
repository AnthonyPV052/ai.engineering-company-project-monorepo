"use client";

import { FormEvent, useState } from "react";

interface KnowledgeResponse {
  answer: string;
  trace_id: string;
  sources: string[];
  execution_order: string[];
}

export default function KnowledgePage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [trace, setTrace] = useState<Pick<KnowledgeResponse, "trace_id" | "sources" | "execution_order"> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) {
      setError("Escribe una pregunta antes de consultar.");
      setAnswer(null);
      return;
    }

    setLoading(true);
    setError(null);
    setAnswer(null);
    setTrace(null);
    try {
      const response = await fetch("/api/knowledge/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const payload = (await response.json().catch(() => null)) as KnowledgeResponse | { detail?: string } | null;
      if (!response.ok || !payload || !("answer" in payload) || typeof payload.answer !== "string") {
        throw new Error(payload && "detail" in payload && payload.detail ? payload.detail : "No se pudo obtener una respuesta.");
      }
      setAnswer(payload.answer);
      setTrace({
        trace_id: payload.trace_id,
        sources: payload.sources,
        execution_order: payload.execution_order,
      });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo conectar con el servicio de conocimiento.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl space-y-7 pb-12">
      <section className="rounded-3xl border border-violet-300/25 bg-gradient-to-br from-slate-950 via-violet-950 to-cyan-950 p-7 sm:p-10">
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-violet-200">Conocimiento Brasaland</p>
        <h1 className="mt-3 text-3xl font-black text-white sm:text-5xl">Pregunta a la base de conocimiento</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-200 sm:text-base">Consulta procedimientos, alérgenos, proveedores y el programa de fidelización con respuestas fundamentadas en la documentación interna.</p>
      </section>

      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-5 sm:p-7">
        <form onSubmit={submit} className="space-y-4">
          <label htmlFor="knowledge-question" className="text-sm font-bold text-white">Tu pregunta</label>
          <textarea
            id="knowledge-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="¿Qué alérgenos tiene la Ensalada Tropical?"
            rows={4}
            disabled={loading}
            className="w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-slate-100 outline-none focus:border-violet-300 disabled:opacity-60"
          />
          <button type="submit" disabled={loading} className="rounded-xl bg-violet-300 px-5 py-3 text-sm font-black uppercase tracking-wide text-slate-950 transition hover:bg-violet-200 disabled:cursor-wait disabled:opacity-60">
            {loading ? "Consultando…" : "Consultar"}
          </button>
        </form>

        {error && (
          <div role="alert" className="mt-6 rounded-xl border border-rose-400/40 bg-rose-950/30 p-4 text-sm text-rose-100">
            <p className="font-bold">La consulta no pudo completarse</p>
            <p className="mt-1">{error}</p>
          </div>
        )}
        {loading && <p className="mt-6 text-sm text-slate-300" role="status">Buscando en la documentación y preparando la respuesta…</p>}
        {answer !== null && !loading && (
          <div className="mt-6 rounded-xl border border-emerald-300/30 bg-emerald-950/20 p-5">
            <h2 className="text-sm font-bold uppercase tracking-[0.16em] text-emerald-200">Respuesta</h2>
            <p className="mt-3 whitespace-pre-wrap leading-7 text-slate-100">{answer}</p>
            {trace && (
              <div className="mt-5 border-t border-emerald-300/20 pt-4 text-xs text-emerald-100/80">
                <p><span className="font-bold">Fuentes:</span> {trace.sources.join(" → ")}</p>
                <p className="mt-1"><span className="font-bold">Orden de ejecución:</span> {trace.execution_order.join(" → ")}</p>
                <p className="mt-1 break-all"><span className="font-bold">Trace ID:</span> {trace.trace_id}</p>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
