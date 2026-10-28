import type { Candidate, Note } from "@/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "https://playground.4geeks.com/tracker/api/v1";

type CandidatePayload = Partial<
  Omit<Candidate, "id" | "created_at"> & Pick<Candidate, "name" | "email">
>;

interface RawNote {
  id: string;
  record_id: string;
  content: string;
  created_at: string;
}

interface RawCandidate {
  id: string;
  full_name?: string;
  name?: string;
  email: string;
  phone?: string;
  position?: string;
  linkedin_url?: string;
  linkedin?: string;
  cv_url?: string;
  cv_link?: string;
  experience_years?: number;
  years_of_experience?: number;
  status: Candidate["status"];
  stage: Candidate["stage"];
  applied_at?: string;
  created_at?: string;
  notes?: RawNote[];
}

function normalizeCandidate(raw: RawCandidate): Candidate {
  return {
    id: String(raw.id),
    name: raw.full_name ?? raw.name ?? "",
    email: raw.email,
    phone: raw.phone ?? "",
    position: raw.position ?? "Asistente de Dirección",
    linkedin: raw.linkedin_url ?? raw.linkedin ?? "",
    cv_link: raw.cv_url ?? raw.cv_link ?? "",
    years_of_experience: raw.experience_years ?? raw.years_of_experience ?? 0,
    status: raw.status,
    stage: raw.stage,
    created_at: raw.applied_at ?? raw.created_at ?? "",
  };
}

function normalizeNote(raw: RawNote): Note {
  return {
    id: String(raw.id),
    record_id: String(raw.record_id),
    content: raw.content,
    created_at: raw.created_at,
  };
}

function buildCandidatePayload(data: CandidatePayload): Record<string, unknown> {
  const payload: Record<string, unknown> = {};

  if (data.name !== undefined) payload.full_name = data.name;
  if (data.email !== undefined) payload.email = data.email;
  if (data.phone !== undefined) payload.phone = data.phone;
  if (data.position !== undefined) payload.position = data.position;
  if (data.linkedin !== undefined) payload.linkedin_url = data.linkedin;
  if (data.cv_link !== undefined) payload.cv_url = data.cv_link;
  if (data.years_of_experience !== undefined) {
    payload.experience_years = data.years_of_experience;
  }
  if (data.status !== undefined) payload.status = data.status;
  if (data.stage !== undefined) payload.stage = data.stage;

  return payload;
}

class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const body = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const message =
      (isJson &&
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof (body as { detail?: unknown }).detail === "string" &&
        (body as { detail: string }).detail) ||
      `Request failed with status ${response.status}`;

    throw new ApiError(message, response.status, body);
  }

  return body as T;
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });

    return await parseResponse<T>(response);
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }

    throw new Error(
      error instanceof Error
        ? `Network error: ${error.message}`
        : "Network error: unknown error"
    );
  }
}

export async function getRecords(): Promise<Candidate[]> {
  const response = await apiRequest<
    RawCandidate[] | { data?: RawCandidate[]; results?: RawCandidate[] }
  >("/records", { method: "GET" });

  const list = Array.isArray(response)
    ? response
    : response.data ?? response.results ?? [];

  return list.map(normalizeCandidate);
}

export async function createRecord(data: CandidatePayload): Promise<Candidate> {
  const created = await apiRequest<RawCandidate>("/records", {
    method: "POST",
    body: JSON.stringify(buildCandidatePayload(data)),
  });

  return normalizeCandidate(created);
}

export async function getRecordById(id: string): Promise<Candidate> {
  const record = await apiRequest<RawCandidate>(`/records/${id}`, { method: "GET" });
  return normalizeCandidate(record);
}

export async function updateRecord(
  id: string,
  data: CandidatePayload
): Promise<Candidate> {
  const updated = await apiRequest<RawCandidate>(`/records/${id}`, {
    method: "PUT",
    body: JSON.stringify(buildCandidatePayload(data)),
  });

  return normalizeCandidate(updated);
}

export async function patchRecord(
  id: string,
  data: CandidatePayload
): Promise<Candidate> {
  const updated = await apiRequest<RawCandidate>(`/records/${id}`, {
    method: "PATCH",
    body: JSON.stringify(buildCandidatePayload(data)),
  });

  return normalizeCandidate(updated);
}

export async function getNotes(recordId: string): Promise<Note[]> {
  const response = await apiRequest<
    RawNote[] | { data?: RawNote[]; results?: RawNote[] }
  >(`/records/${recordId}/notes`, {
    method: "GET",
  });

  const notes = Array.isArray(response)
    ? response
    : response.data ?? response.results ?? [];

  return notes.map(normalizeNote);
}

export async function createNote(
  recordId: string,
  content: string
): Promise<Note> {
  const response = await apiRequest<RawNote | { data?: RawNote }>(
    `/records/${recordId}/notes`,
    {
    method: "POST",
    body: JSON.stringify({ content }),
    }
  );

  const note =
    typeof response === "object" && response !== null && "data" in response
      ? response.data
      : response;

  if (!note) {
    throw new Error("No se pudo crear la nota.");
  }

  return normalizeNote(note);
}

export async function deleteNote(
  recordId: string,
  noteId: string
): Promise<void> {
  return apiRequest<void>(`/records/${recordId}/notes/${noteId}`, {
    method: "DELETE",
  });
}

export { ApiError };
export type { CandidatePayload };