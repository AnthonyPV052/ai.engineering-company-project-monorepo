"use client";

import { FormEvent, useMemo, useState } from "react";

export interface CandidateFormData {
  name: string;
  email: string;
  phone: string;
  position: string;
  linkedin: string;
  cv_link: string;
  years_of_experience: number;
}

interface CandidateFormProps {
  initialValues?: Partial<CandidateFormData>;
  onSubmit: (data: CandidateFormData) => Promise<void> | void;
  submitLabel: string;
  isSubmitting?: boolean;
  apiError?: string;
  onCancel?: () => void;
}

interface FieldErrors {
  name?: string;
  email?: string;
  phone?: string;
  linkedin?: string;
  cv_link?: string;
  years_of_experience?: string;
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_REGEX = /^\+?[0-9()\-\s]{7,20}$/;

function isValidUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export default function CandidateForm({
  initialValues,
  onSubmit,
  submitLabel,
  isSubmitting = false,
  apiError,
  onCancel,
}: CandidateFormProps) {
  const defaults = useMemo(
    () => ({
      name: initialValues?.name ?? "",
      email: initialValues?.email ?? "",
      phone: initialValues?.phone ?? "",
      position: initialValues?.position ?? "Asistente de Dirección",
      linkedin: initialValues?.linkedin ?? "",
      cv_link: initialValues?.cv_link ?? "",
      years_of_experience:
        initialValues?.years_of_experience !== undefined
          ? String(initialValues.years_of_experience)
          : "",
    }),
    [initialValues]
  );

  const [name, setName] = useState(defaults.name);
  const [email, setEmail] = useState(defaults.email);
  const [phone, setPhone] = useState(defaults.phone);
  const [position, setPosition] = useState(defaults.position);
  const [linkedin, setLinkedin] = useState(defaults.linkedin);
  const [cvLink, setCvLink] = useState(defaults.cv_link);
  const [yearsOfExperience, setYearsOfExperience] = useState(
    defaults.years_of_experience
  );
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  function validate(): FieldErrors {
    const errors: FieldErrors = {};

    if (!name.trim()) {
      errors.name = "El nombre es obligatorio.";
    }

    if (!email.trim()) {
      errors.email = "El email es obligatorio.";
    } else if (!EMAIL_REGEX.test(email.trim())) {
      errors.email = "El email no tiene un formato válido.";
    }

    if (phone.trim() && !PHONE_REGEX.test(phone.trim())) {
      errors.phone =
        "El teléfono solo puede incluir números, espacios, paréntesis, guiones y +.";
    }

    if (linkedin.trim()) {
      if (!isValidUrl(linkedin.trim())) {
        errors.linkedin = "LinkedIn debe ser una URL válida (http/https).";
      } else if (!linkedin.toLowerCase().includes("linkedin.com/")) {
        errors.linkedin = "La URL de LinkedIn debe contener linkedin.com.";
      }
    }

    if (cvLink.trim() && !isValidUrl(cvLink.trim())) {
      errors.cv_link = "El enlace al CV debe ser una URL válida (http/https).";
    }

    const years = Number(yearsOfExperience);
    if (!yearsOfExperience.trim()) {
      errors.years_of_experience = "Los años de experiencia son obligatorios.";
    } else if (!Number.isFinite(years) || years <= 0) {
      errors.years_of_experience =
        "Los años de experiencia deben ser un número positivo.";
    }

    return errors;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const errors = validate();
    setFieldErrors(errors);

    if (Object.keys(errors).length > 0) {
      return;
    }

    await onSubmit({
      name: name.trim(),
      email: email.trim(),
      phone: phone.trim(),
      position: position.trim() || "Asistente de Dirección",
      linkedin: linkedin.trim(),
      cv_link: cvLink.trim(),
      years_of_experience: Number(yearsOfExperience),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {apiError ? (
        <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {apiError}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Nombre completo *</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="Nombre y apellido"
          />
          {fieldErrors.name ? (
            <span className="text-xs text-rose-700">{fieldErrors.name}</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Email *</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="nombre@empresa.com"
          />
          {fieldErrors.email ? (
            <span className="text-xs text-rose-700">{fieldErrors.email}</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Teléfono</span>
          <input
            type="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="+34 600 000 000"
            inputMode="tel"
            pattern="^\+?[0-9()\-\s]{7,20}$"
            title="Solo números, espacios, paréntesis, guiones y +"
          />
          {fieldErrors.phone ? (
            <span className="text-xs text-rose-700">{fieldErrors.phone}</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Puesto</span>
          <input
            type="text"
            value={position}
            onChange={(event) => setPosition(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="Asistente de Dirección"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">LinkedIn</span>
          <input
            type="url"
            value={linkedin}
            onChange={(event) => setLinkedin(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="https://linkedin.com/in/..."
          />
          {fieldErrors.linkedin ? (
            <span className="text-xs text-rose-700">{fieldErrors.linkedin}</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Enlace al CV</span>
          <input
            type="url"
            value={cvLink}
            onChange={(event) => setCvLink(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="https://..."
          />
          {fieldErrors.cv_link ? (
            <span className="text-xs text-rose-700">{fieldErrors.cv_link}</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1 md:col-span-2">
          <span className="text-sm font-medium text-slate-700">
            Años de experiencia *
          </span>
          <input
            type="number"
            min={1}
            step={1}
            value={yearsOfExperience}
            onChange={(event) => setYearsOfExperience(event.target.value)}
            className="h-10 rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="Ejemplo: 5"
          />
          {fieldErrors.years_of_experience ? (
            <span className="text-xs text-rose-700">
              {fieldErrors.years_of_experience}
            </span>
          ) : null}
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={isSubmitting}
          className="inline-flex h-10 items-center rounded-md bg-slate-900 px-4 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Guardando..." : submitLabel}
        </button>
        {onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-10 items-center rounded-md border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
          >
            Cancelar
          </button>
        ) : null}
      </div>
    </form>
  );
}
