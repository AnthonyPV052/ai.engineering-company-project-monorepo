"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  getCurrentUser,
  type AuthenticatedUser,
  updateCurrentUserProfile,
} from "@/lib/auth";

type ProfileForm = {
  name: string;
  phone: string;
  address: string;
};

const EMPTY_PROFILE: ProfileForm = { name: "", phone: "", address: "" };

export default function ProfilePage() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [form, setForm] = useState<ProfileForm>(EMPTY_PROFILE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadProfile() {
      try {
        const currentUser = await getCurrentUser();
        if (!active) return;

        setUser(currentUser);
        setForm({
          name: currentUser.profile?.name ?? "",
          phone: currentUser.profile?.phone ?? "",
          address: currentUser.profile?.address ?? "",
        });
      } catch (caughtError) {
        if (active) setError(caughtError instanceof Error ? caughtError.message : "No se pudo cargar tu perfil.");
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadProfile();
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);

    try {
      const updatedProfile = await updateCurrentUserProfile({
        name: form.name.trim() || null,
        phone: form.phone.trim() || null,
        address: form.address.trim() || null,
      });
      setUser((currentUser) => (currentUser ? { ...currentUser, profile: updatedProfile } : currentUser));
      window.dispatchEvent(new Event("brasaland:profile-updated"));
      setMessage("Perfil actualizado correctamente.");
    } catch (caughtError) {
      if (caughtError instanceof ApiError && caughtError.status === 422) {
        setError("Revisa el formato de los datos antes de guardar.");
      } else {
        setError(caughtError instanceof Error ? caughtError.message : "No se pudo actualizar el perfil.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-8 pb-10">
      <section className="relative overflow-hidden rounded-3xl border border-orange-300/25 bg-gradient-to-br from-slate-900 via-orange-950 to-stone-950 p-7 sm:p-10">
        <div aria-hidden="true" className="absolute -right-12 -top-12 h-48 w-48 rounded-full bg-orange-300/15 blur-3xl" />
        <div className="relative max-w-xl">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-orange-200">Cuenta</p>
          <h1 className="mt-3 text-4xl font-black text-white">Perfil de usuario</h1>
          <p className="mt-3 text-sm leading-6 text-slate-200">Mantén actualizados tus datos de contacto para el equipo de Brasaland.</p>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-6 sm:p-8">
        {loading ? (
          <p className="text-sm text-slate-300">Cargando perfil…</p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="grid gap-4 rounded-xl border border-slate-700 bg-slate-950/70 p-4 sm:grid-cols-2">
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Email</p>
                <p className="mt-1 break-all text-sm text-white">{user?.email}</p>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Rol</p>
                <p className="mt-1 text-sm capitalize text-white">{user?.role}</p>
              </div>
            </div>

            <p className="text-sm text-slate-300">Completa o modifica los campos opcionales.</p>
            <label className="block text-sm font-semibold text-slate-200" htmlFor="name">
              Nombre
              <input id="name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
            </label>
            <label className="block text-sm font-semibold text-slate-200" htmlFor="phone">
              Teléfono
              <input id="phone" type="tel" autoComplete="tel" value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
            </label>
            <label className="block text-sm font-semibold text-slate-200" htmlFor="address">
              Dirección
              <textarea id="address" rows={3} autoComplete="street-address" value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} className="mt-2 w-full resize-y rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-orange-300 focus:ring-2 focus:ring-orange-300/30" />
            </label>

            {error && <p role="alert" className="rounded-xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</p>}
            {message && <p role="status" className="rounded-xl border border-emerald-400/40 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">{message}</p>}

            <button type="submit" disabled={saving} className="rounded-xl bg-orange-400 px-5 py-3 text-sm font-bold text-slate-950 transition hover:bg-orange-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-300 disabled:cursor-not-allowed disabled:opacity-60">
              {saving ? "Guardando…" : "Guardar cambios"}
            </button>
            <Link href="/account/change-password" className="ml-4 text-sm font-semibold text-orange-300 underline underline-offset-4 hover:text-orange-200">
              Cambiar contraseña
            </Link>
          </form>
        )}
      </section>
    </main>
  );
}
