"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import CandidateForm, { type CandidateFormData } from "@/components/CandidateForm";
import { stageTranslations, statusTranslations } from "@/lib/constants";
import {
  createNote,
  deleteNote,
  getNotes,
  getRecordById,
  patchRecord,
  updateRecord,
} from "@/services/api";
import type { Candidate, CandidateStage, CandidateStatus, Note } from "@/types";

type ViewState = "loading" | "success" | "error";

const statusOptions = Object.entries(statusTranslations) as Array<
  [CandidateStatus, string]
>;
const stageOptions = Object.entries(stageTranslations) as Array<
  [CandidateStage, string]
>;

function formatApplicationDate(date: string): string {
  const parsed = new Date(date);

  if (Number.isNaN(parsed.getTime())) {
    return "Fecha no disponible";
  }

  return parsed.toLocaleDateString("es-ES", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

export default function CandidateDetailsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const candidateId = useMemo(() => {
    return Array.isArray(params.id) ? params.id[0] : params.id;
  }, [params.id]);

  const [viewState, setViewState] = useState<ViewState>("loading");
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [errorMessage, setErrorMessage] = useState("");

  const [isPatchingStatus, setIsPatchingStatus] = useState(false);
  const [isPatchingStage, setIsPatchingStage] = useState(false);
  const [noteContent, setNoteContent] = useState("");
  const [isCreatingNote, setIsCreatingNote] = useState(false);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [notesError, setNotesError] = useState("");
  const [showEditForm, setShowEditForm] = useState(false);
  const [isUpdatingCandidate, setIsUpdatingCandidate] = useState(false);
  const [editError, setEditError] = useState("");
  const [editSuccess, setEditSuccess] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadCandidateDetails() {
      if (!candidateId) {
        setViewState("error");
        setErrorMessage("El ID del candidato no es válido.");
        return;
      }

      setViewState("loading");
      setErrorMessage("");

      try {
        const [record, candidateNotes] = await Promise.all([
          getRecordById(candidateId),
          getNotes(candidateId),
        ]);

        if (!isMounted) {
          return;
        }

        setCandidate(record);
        setNotes(Array.isArray(candidateNotes) ? candidateNotes : []);
        setViewState("success");
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setViewState("error");
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "No se pudo cargar el detalle del candidato."
        );
      }
    }

    void loadCandidateDetails();

    return () => {
      isMounted = false;
    };
  }, [candidateId]);

  async function handleStatusChange(value: CandidateStatus) {
    if (!candidate) {
      return;
    }

    setIsPatchingStatus(true);
    setNotesError("");

    try {
      const updated = await patchRecord(candidate.id, { status: value });
      setCandidate(updated);
    } catch (error) {
      setNotesError(
        error instanceof Error
          ? error.message
          : "No se pudo actualizar el estado."
      );
    } finally {
      setIsPatchingStatus(false);
    }
  }

  async function handleStageChange(value: CandidateStage) {
    if (!candidate) {
      return;
    }

    setIsPatchingStage(true);
    setNotesError("");

    try {
      const updated = await patchRecord(candidate.id, { stage: value });
      setCandidate(updated);
    } catch (error) {
      setNotesError(
        error instanceof Error
          ? error.message
          : "No se pudo actualizar la etapa."
      );
    } finally {
      setIsPatchingStage(false);
    }
  }

  async function handleCreateNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!candidate || !noteContent.trim()) {
      return;
    }

    setIsCreatingNote(true);
    setNotesError("");

    try {
      const created = await createNote(candidate.id, noteContent.trim());
      setNotes((previous) => [created, ...previous]);
      setNoteContent("");
    } catch (error) {
      setNotesError(
        error instanceof Error ? error.message : "No se pudo crear la nota."
      );
    } finally {
      setIsCreatingNote(false);
    }
  }

  async function handleDeleteNote(noteId: string) {
    if (!candidate) {
      return;
    }

    setDeletingNoteId(noteId);
    setNotesError("");

    try {
      await deleteNote(candidate.id, noteId);
      setNotes((previous) => previous.filter((note) => note.id !== noteId));
    } catch (error) {
      setNotesError(
        error instanceof Error ? error.message : "No se pudo eliminar la nota."
      );
    } finally {
      setDeletingNoteId(null);
    }
  }

  async function handleUpdateCandidate(data: CandidateFormData) {
    if (!candidate) {
      return;
    }

    setIsUpdatingCandidate(true);
    setEditError("");
    setEditSuccess("");

    try {
      const updated = await updateRecord(candidate.id, data);
      setCandidate(updated);
      setShowEditForm(false);
      setEditSuccess("Datos del candidato actualizados correctamente.");
    } catch (error) {
      setEditError(
        error instanceof Error
          ? error.message
          : "No se pudieron actualizar los datos del candidato."
      );
    } finally {
      setIsUpdatingCandidate(false);
    }
  }

  if (viewState === "loading") {
    return (
      <main className="min-h-screen bg-slate-100 px-4 py-8 md:px-8">
        <section className="mx-auto w-full max-w-5xl animate-pulse space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm md:p-8">
          <div className="h-8 w-1/3 rounded bg-slate-200" />
          <div className="h-24 rounded bg-slate-200" />
          <div className="h-24 rounded bg-slate-200" />
          <div className="h-24 rounded bg-slate-200" />
        </section>
      </main>
    );
  }

  if (viewState === "error") {
    return (
      <main className="min-h-screen bg-slate-100 px-4 py-8 md:px-8">
        <section className="mx-auto w-full max-w-3xl rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-700 shadow-sm">
          <h1 className="mb-2 text-xl font-bold">No pudimos cargar el candidato</h1>
          <p className="text-sm">
            {errorMessage || "Intenta nuevamente en unos minutos."}
          </p>
          <button
            type="button"
            onClick={() => router.push("/listOfCandidates")}
            className="mt-4 inline-flex h-10 items-center rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white"
          >
            Volver al listado
          </button>
        </section>
      </main>
    );
  }

  if (!candidate) {
    return null;
  }

  return (
    <main className="min-h-screen bg-slate-100 px-4 py-8 text-slate-900 md:px-8">
      <section className="mx-auto w-full max-w-5xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm md:p-8">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium uppercase tracking-wide text-slate-500">
              Perfil de candidatura
            </p>
            <h1 className="text-2xl font-bold text-slate-900 md:text-3xl">
              {candidate.name}
            </h1>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => router.push("/listOfCandidates")}
              className="inline-flex h-10 items-center rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              Volver al listado
            </button>
            <button
              type="button"
              onClick={() => {
                setShowEditForm((previous) => !previous);
                setEditError("");
              }}
              className="inline-flex h-10 items-center rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white transition hover:bg-teal-800"
            >
              {showEditForm ? "Cerrar edición" : "Editar Datos"}
            </button>
          </div>
        </header>

        {editSuccess ? (
          <p className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {editSuccess}
          </p>
        ) : null}

        {showEditForm ? (
          <section className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-4 md:p-5">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">
              Editar datos del candidato
            </h2>
            <CandidateForm
              initialValues={{
                name: candidate.name,
                email: candidate.email,
                phone: candidate.phone,
                position: candidate.position,
                linkedin: candidate.linkedin,
                cv_link: candidate.cv_link,
                years_of_experience: candidate.years_of_experience,
              }}
              onSubmit={handleUpdateCandidate}
              submitLabel="Actualizar datos"
              isSubmitting={isUpdatingCandidate}
              apiError={editError}
              onCancel={() => {
                setShowEditForm(false);
                setEditError("");
              }}
            />
          </section>
        ) : null}

        <section className="mb-8 grid grid-cols-1 gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-2">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Email</p>
            <p className="text-sm font-medium text-slate-800">{candidate.email}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Teléfono</p>
            <p className="text-sm font-medium text-slate-800">{candidate.phone}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Puesto</p>
            <p className="text-sm font-medium text-slate-800">{candidate.position}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">
              Años de experiencia
            </p>
            <p className="text-sm font-medium text-slate-800">
              {candidate.years_of_experience}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">LinkedIn</p>
            <a
              href={candidate.linkedin}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium text-teal-700 underline-offset-2 hover:underline"
            >
              Ver perfil
            </a>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">CV</p>
            <a
              href={candidate.cv_link}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium text-teal-700 underline-offset-2 hover:underline"
            >
              Descargar CV
            </a>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">
              Fecha de aplicación
            </p>
            <p className="text-sm font-medium text-slate-800">
              {formatApplicationDate(candidate.created_at)}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-slate-500">
                Estado
              </span>
              <select
                value={candidate.status}
                onChange={(event) =>
                  void handleStatusChange(event.target.value as CandidateStatus)
                }
                disabled={isPatchingStatus}
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-800 disabled:opacity-60"
              >
                {statusOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-slate-500">
                Etapa
              </span>
              <select
                value={candidate.stage}
                onChange={(event) =>
                  void handleStageChange(event.target.value as CandidateStage)
                }
                disabled={isPatchingStage}
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-800 disabled:opacity-60"
              >
                {stageOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 p-4 md:p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">Notas internas</h2>
            <Link
              href={`/candidates/${candidate.id}`}
              className="text-xs font-medium text-slate-500"
            >
              ID candidato: {candidate.id}
            </Link>
          </div>

          <form onSubmit={handleCreateNote} className="mb-4 flex flex-col gap-2 md:flex-row">
            <input
              type="text"
              value={noteContent}
              onChange={(event) => setNoteContent(event.target.value)}
              placeholder="Añadir una nueva nota"
              className="h-10 flex-1 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            />
            <button
              type="submit"
              disabled={!noteContent.trim() || isCreatingNote}
              className="inline-flex h-10 items-center justify-center rounded-md bg-slate-900 px-4 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isCreatingNote ? "Guardando..." : "Añadir nota"}
            </button>
          </form>

          {notesError ? (
            <p className="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {notesError}
            </p>
          ) : null}

          {notes.length === 0 ? (
            <p className="text-sm text-slate-600">Este candidato no tiene notas aún.</p>
          ) : (
            <ul className="space-y-2">
              {notes.map((note) => (
                <li
                  key={note.id}
                  className="flex items-start justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-3"
                >
                  <div>
                    <p className="text-sm text-slate-800">{note.content}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatApplicationDate(note.created_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleDeleteNote(note.id)}
                    disabled={deletingNoteId === note.id}
                    className="text-sm font-medium text-rose-700 transition hover:text-rose-800 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {deletingNoteId === note.id ? "Eliminando..." : "Eliminar"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </section>
    </main>
  );
}