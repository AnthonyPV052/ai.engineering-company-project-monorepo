"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import CandidateForm, { type CandidateFormData } from "@/components/CandidateForm";
import { stageTranslations, statusTranslations } from "@/lib/constants";
import { createRecord, getRecords } from "@/services/api";
import type { Candidate, CandidateStage, CandidateStatus } from "@/types";

type LoadingState = "loading" | "success" | "error";
const LOCAL_CANDIDATES_KEY = "talent_pipeline_local_candidates";

function readLocalCandidates(): Candidate[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(LOCAL_CANDIDATES_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Candidate[]) : [];
  } catch {
    return [];
  }
}

function writeLocalCandidates(candidates: Candidate[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    LOCAL_CANDIDATES_KEY,
    JSON.stringify(candidates)
  );
}

function mergeCandidates(apiCandidates: Candidate[], localCandidates: Candidate[]) {
  const map = new Map<string, Candidate>();

  for (const candidate of [...localCandidates, ...apiCandidates]) {
    map.set(candidate.id, candidate);
  }

  return Array.from(map.values());
}

export default function ListOfCandidatesPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [records, setRecords] = useState<Candidate[]>([]);
  const [loadingState, setLoadingState] = useState<LoadingState>("loading");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [searchInput, setSearchInput] = useState<string>("");
  const [appliedSearch, setAppliedSearch] = useState<string>("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createSuccess, setCreateSuccess] = useState("");

  const selectedStatus = (searchParams.get("status") ?? "") as
    | CandidateStatus
    | "";
  const selectedStage = (searchParams.get("stage") ?? "") as CandidateStage | "";

  async function loadRecords() {
    setLoadingState("loading");
    setErrorMessage("");

    try {
      const data = await getRecords();
      const apiCandidates = Array.isArray(data) ? data : [];
      const localCandidates = readLocalCandidates();
      const merged = mergeCandidates(apiCandidates, localCandidates);
      setRecords(merged);
      writeLocalCandidates(merged);
      setLoadingState("success");
    } catch (error) {
      setLoadingState("error");
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "No se pudieron cargar las candidaturas."
      );
    }
  }

  useEffect(() => {
    void loadRecords();
  }, []);

  function updateFilter(key: "status" | "stage", value: string) {
    const params = new URLSearchParams(searchParams.toString());

    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }

    const queryString = params.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname);
  }

  const filteredCandidates = useMemo(() => {
    return records.filter((candidate) => {
      const byStatus = selectedStatus ? candidate.status === selectedStatus : true;
      const byStage = selectedStage ? candidate.stage === selectedStage : true;
      const byQuery = appliedSearch
        ? candidate.name.toLowerCase().includes(appliedSearch.toLowerCase()) ||
          candidate.email.toLowerCase().includes(appliedSearch.toLowerCase())
        : true;

      return byStatus && byStage && byQuery;
    });
  }, [records, selectedStatus, selectedStage, appliedSearch]);

  async function handleSearch() {
    setAppliedSearch(searchInput.trim());

    // Fuerza nueva carga para validar conexión API incluso cuando la búsqueda esté vacía.
    await loadRecords();
  }

  async function handleCreateCandidate(data: CandidateFormData) {
    setIsCreating(true);
    setCreateError("");
    setCreateSuccess("");

    try {
      const created = await createRecord(data);
      setRecords((previous) => {
        const merged = mergeCandidates([created], previous);
        writeLocalCandidates(merged);
        return merged;
      });
      setShowCreateForm(false);
      setCreateSuccess("Candidato registrado correctamente.");
    } catch (error) {
      setCreateError(
        error instanceof Error
          ? error.message
          : "No se pudo registrar el candidato."
      );
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-100 px-4 py-8 text-slate-900 md:px-8">
      <section className="mx-auto w-full max-w-6xl rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:p-8">
        <header className="mb-6 flex flex-col gap-4 md:mb-8 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-medium uppercase tracking-wide text-slate-500">
              Talent Pipeline Tracker
            </p>
            <h1 className="text-2xl font-bold text-slate-900 md:text-3xl">
              Listado de candidaturas
            </h1>
          </div>

          <button
            type="button"
            onClick={() => {
              setShowCreateForm((previous) => !previous);
              setCreateError("");
            }}
            className="inline-flex h-11 items-center justify-center rounded-lg bg-teal-700 px-5 text-sm font-semibold text-white transition hover:bg-teal-800"
          >
            {showCreateForm ? "Cerrar formulario" : "Registrar Candidato"}
          </button>
        </header>

        {createSuccess ? (
          <p className="mb-5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {createSuccess}
          </p>
        ) : null}

        {showCreateForm ? (
          <section className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-4 md:p-5">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">
              Registrar nuevo candidato
            </h2>
            <CandidateForm
              onSubmit={handleCreateCandidate}
              submitLabel="Guardar candidato"
              isSubmitting={isCreating}
              apiError={createError}
              onCancel={() => {
                setShowCreateForm(false);
                setCreateError("");
              }}
            />
          </section>
        ) : null}

        <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-slate-700">Buscar</span>
            <input
              type="text"
              placeholder="Nombre o email"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void handleSearch();
                }
              }}
              className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none ring-0 transition placeholder:text-slate-400 focus:border-teal-600"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-slate-700">Estado</span>
            <select
              value={selectedStatus}
              onChange={(event) => updateFilter("status", event.target.value)}
              className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none ring-0 transition focus:border-teal-600"
            >
              <option value="">Todos los estados</option>
              {Object.entries(statusTranslations).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-slate-700">Etapa</span>
            <select
              value={selectedStage}
              onChange={(event) => updateFilter("stage", event.target.value)}
              className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none ring-0 transition focus:border-teal-600"
            >
              <option value="">Todas las etapas</option>
              {Object.entries(stageTranslations).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mb-6 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void handleSearch()}
            className="inline-flex h-10 items-center rounded-md bg-slate-900 px-4 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            Buscar
          </button>
          <button
            type="button"
            onClick={() => {
              setSearchInput("");
              setAppliedSearch("");
              void loadRecords();
            }}
            className="inline-flex h-10 items-center rounded-md border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
          >
            Limpiar
          </button>
        </div>

        {loadingState === "loading" ? (
          <div className="space-y-3">
            {[...Array.from({ length: 4 })].map((_, index) => (
              <div
                key={`skeleton-${index}`}
                className="h-16 animate-pulse rounded-lg border border-slate-200 bg-slate-100"
              />
            ))}
          </div>
        ) : null}

        {loadingState === "error" ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            Ocurrió un problema al consultar la API. Intenta nuevamente en unos
            minutos.
            {errorMessage ? ` Detalle: ${errorMessage}` : ""}
            <div className="mt-3">
              <button
                type="button"
                onClick={() => void loadRecords()}
                className="inline-flex h-9 items-center rounded-md bg-rose-700 px-3 text-xs font-semibold text-white transition hover:bg-rose-800"
              >
                Reintentar conexión
              </button>
            </div>
          </div>
        ) : null}

        {loadingState === "success" ? (
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <div className="hidden grid-cols-[2fr_2fr_1.4fr_1.6fr_1fr] gap-3 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 md:grid">
              <span>Nombre completo</span>
              <span>Puesto</span>
              <span>Estado</span>
              <span>Etapa actual</span>
              <span>Acciones</span>
            </div>

            {filteredCandidates.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-600">
                No hay candidaturas que coincidan con los filtros aplicados.
              </div>
            ) : (
              <ul className="divide-y divide-slate-200">
                {filteredCandidates.map((candidate) => (
                  <li
                    key={candidate.id}
                    className="grid gap-3 px-4 py-4 md:grid-cols-[2fr_2fr_1.4fr_1.6fr_1fr] md:items-center"
                  >
                    <div>
                      <p className="font-semibold text-slate-900">{candidate.name}</p>
                      <p className="text-sm text-slate-500">{candidate.email}</p>
                    </div>

                    <p className="text-sm text-slate-700">
                      {candidate.position || "Asistente de Dirección"}
                    </p>

                    <p className="text-sm font-medium text-slate-700">
                      {statusTranslations[candidate.status]}
                    </p>

                    <p className="text-sm text-slate-700">
                      {stageTranslations[candidate.stage]}
                    </p>

                    <div>
                      <Link
                        href={`/candidates/${candidate.id}`}
                        className="inline-flex h-9 items-center rounded-md border border-slate-300 px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                      >
                        Ver detalle
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </section>
    </main>
  );
}