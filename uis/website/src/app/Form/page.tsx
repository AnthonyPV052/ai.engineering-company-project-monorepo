import Navbar from "../../components/Navbar";

export default function FormPage() {
  return (
		<div className="min-h-screen bg-[#da8141]">
      
		<Navbar mode="form" />

		<main className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 lg:px-8 lg:py-14">
			<section className="rounded-3xl border border-stone-300 bg-white p-6 text-stone-900 shadow-xl sm:p-8 lg:p-10" aria-labelledby="form-title">
				<div className="max-w-3xl">
					<p className="text-xs font-semibold uppercase tracking-[0.24em] text-orange-900">Formulario de aplicación</p>
					<h1 id="form-title" className="mt-2 text-3xl font-extrabold leading-tight sm:text-4xl">Cuéntanos cómo quieres conectar con Brasaland</h1>
					<p className="mt-4 text-stone-900">
						Recopilamos esta información para enrutar tu solicitud al equipo correcto: operaciones, compras, marketing,
						talento, formación o tecnología.
					</p>
				</div>

				<noscript>
					<p className="mt-6 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-700">
						Este formulario requiere JavaScript para validar y enviar la aplicación.
					</p>
				</noscript>

				<div id="form-alert" className="mt-6 hidden rounded-xl border p-4 text-sm" role="alert" aria-live="polite"></div>

				<form id="application-form" className="mt-8 grid gap-6" noValidate>
					<fieldset className="grid gap-5 rounded-2xl border border-stone-200 p-5 sm:grid-cols-2">
						<legend className="px-2 text-sm font-semibold text-stone-900">Datos personales</legend>

						<div>
							<label htmlFor="firstName" className="mb-1 block text-sm font-semibold text-stone-900">Nombre</label>
							<input
								id="firstName"
								name="firstName"
								type="text"
								autoComplete="given-name"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							/>
							<p id="firstName-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="lastName" className="mb-1 block text-sm font-semibold text-stone-900">Apellido</label>
							<input
								id="lastName"
								name="lastName"
								type="text"
								autoComplete="family-name"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							/>
							<p id="lastName-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="email" className="mb-1 block text-sm font-semibold text-stone-900">Correo electrónico</label>
							<input
								id="email"
								name="email"
								type="email"
								autoComplete="email"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							/>
							<p id="email-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="phone" className="mb-1 block text-sm font-semibold text-stone-900">Teléfono</label>
							<input
								id="phone"
								name="phone"
								type="tel"
								inputMode="tel"
								autoComplete="tel"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							/>
							<p id="phone-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="country" className="mb-1 block text-sm font-semibold text-stone-900">País de residencia</label>
							<select
								id="country"
								name="country"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							>
								<option value="">Selecciona una opción</option>
								<option value="Colombia">Colombia</option>
								<option value="Estados Unidos">Estados Unidos</option>
								<option value="Otro">Otro</option>
							</select>
							<p id="country-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="city" className="mb-1 block text-sm font-semibold text-stone-900">Ciudad</label>
							<input
								id="city"
								name="city"
								type="text"
								autoComplete="address-level2"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							/>
							<p id="city-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>
					</fieldset>

					<fieldset className="grid gap-5 rounded-2xl border border-stone-200 p-5 sm:grid-cols-2">
						<legend className="px-2 text-sm font-semibold text-stone-900">Información de interés</legend>

						<div>
							<label htmlFor="relationshipType" className="mb-1 block text-sm font-semibold text-stone-900">¿Cómo quieres vincularte con Brasaland?</label>
							<select
								id="relationshipType"
								name="relationshipType"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							>
								<option value="">Selecciona una opción</option>
								<option value="Talento / empleo">Talento / empleo</option>
								<option value="Proveedor">Proveedor</option>
								<option value="Alianza comercial">Alianza comercial</option>
								<option value="Cliente o comunidad">Cliente o comunidad</option>
							</select>
							<p id="relationshipType-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="areaInterest" className="mb-1 block text-sm font-semibold text-stone-900">Área de interés</label>
							<select
								id="areaInterest"
								name="areaInterest"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							>
								<option value="">Selecciona una opción</option>
								<option value="Operaciones de Restaurante">Operaciones de Restaurante</option>
								<option value="Compras y Proveedores">Compras y Proveedores</option>
								<option value="Marketing y Experiencia Digital">Marketing y Experiencia Digital</option>
								<option value="Personas y Cultura">Personas y Cultura</option>
								<option value="Formación y Estándares de Calidad">Formación y Estándares de Calidad</option>
								<option value="Tecnología">Tecnología</option>
								<option value="Dirección Ejecutiva">Dirección Ejecutiva</option>
							</select>
							<p id="areaInterest-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div className="sm:col-span-2" role="radiogroup" aria-labelledby="market-label">
							<p id="market-label" className="mb-2 block text-sm font-semibold text-stone-900">Mercado de interés principal</p>
							<div className="flex flex-wrap gap-4">
								<label className="inline-flex items-center gap-2 text-sm font-medium text-stone-900">
									<input type="radio" name="market" value="Colombia" className="h-4 w-4 border-stone-400 text-orange-600 focus:ring-orange-500" />
									Colombia
								</label>
								<label className="inline-flex items-center gap-2 text-sm font-medium text-stone-900">
									<input type="radio" name="market" value="Florida" className="h-4 w-4 border-stone-400 text-orange-600 focus:ring-orange-500" />
									Florida
								</label>
								<label className="inline-flex items-center gap-2 text-sm font-medium text-stone-900">
									<input type="radio" name="market" value="Ambos" className="h-4 w-4 border-stone-400 text-orange-600 focus:ring-orange-500" />
									Ambos mercados
								</label>
							</div>
							<p id="market-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="contactMethod" className="mb-1 block text-sm font-semibold text-stone-900">Canal preferido de contacto</label>
							<select
								id="contactMethod"
								name="contactMethod"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							>
								<option value="">Selecciona una opción</option>
								<option value="Email">Email</option>
								<option value="Teléfono">Teléfono</option>
								<option value="WhatsApp">WhatsApp</option>
							</select>
							<p id="contactMethod-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div>
							<label htmlFor="availabilityDate" className="mb-1 block text-sm font-semibold text-stone-900">Fecha disponible para primer contacto</label>
							<input
								id="availabilityDate"
								name="availabilityDate"
								type="date"
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							/>
							<p id="availabilityDate-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>

						<div className="sm:col-span-2">
							<label htmlFor="message" className="mb-1 block text-sm font-semibold text-stone-900">Describe brevemente tu propuesta o interés</label>
							<textarea
								id="message"
								name="message"
								rows={5}
								maxLength={600}
								required
								className="w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-sm shadow-sm outline-none transition focus:border-orange-500 focus:ring-2 focus:ring-orange-200"
							></textarea>
							<p className="mt-1 text-xs text-stone-900">Mínimo 30 caracteres. Máximo 600.</p>
							<p id="message-error" className="mt-1 text-sm text-red-700" aria-live="polite"></p>
						</div>
					</fieldset>

					<fieldset className="rounded-2xl border border-stone-200 p-5">
						<legend className="px-2 text-sm font-semibold text-stone-900">Consentimientos</legend>
						<div className="space-y-3">
							<label className="flex items-start gap-3 text-sm text-stone-900">
								<input id="privacyConsent" name="privacyConsent" type="checkbox" className="mt-0.5 h-4 w-4 rounded border-stone-400 text-orange-600 focus:ring-orange-500" />
								<span>Acepto el tratamiento de mis datos para gestionar esta aplicación.</span>
							</label>
							<p id="privacyConsent-error" className="text-sm text-red-700" aria-live="polite"></p>

							<label className="flex items-start gap-3 text-sm text-stone-900">
								<input id="followupConsent" name="followupConsent" type="checkbox" className="mt-0.5 h-4 w-4 rounded border-stone-400 text-orange-600 focus:ring-orange-500" />
								<span>Autorizo recibir comunicaciones de seguimiento por el canal indicado.</span>
							</label>
							<p id="followupConsent-error" className="text-sm text-red-700" aria-live="polite"></p>
						</div>
					</fieldset>

					<div className="flex flex-wrap items-center gap-3">
						<button
							type="submit"
							className="inline-flex [text-shadow:_2px_2px_0_#000] items-center rounded-full bg-orange-600 px-6 py-3 text-sm font-bold uppercase tracking-wide text-white transition hover:bg-orange-700"
						>
							Enviar aplicación
						</button>
						<p className="text-xs text-stone-900">Todos los campos son obligatorios.</p>
					</div>
				</form>
			</section>
		</main>

		<script src="validation.js" defer></script>
    </div>)
  }