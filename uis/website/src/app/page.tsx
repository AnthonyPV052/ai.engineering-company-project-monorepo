import Link from "next/link";
import Navbar from "../components/Navbar";

export default function Home() {
  return (
		<div className="min-h-screen w-full bg-stone-950 font-sans text-stone-100">
    
		<a
			href="#main-content"
			className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-stone-900"
			>Saltar al contenido principal</a
		>

		<Navbar mode="home" />

		<main id="main-content">
			<section
				id="nosotros"
				className="relative overflow-hidden border-b border-white/10 bg-gradient-to-br from-stone-900 via-amber-950 to-ember-900"
			>
				<div className="absolute -right-24 -top-10 h-72 w-72 rounded-full bg-amber-400/25 blur-3xl" aria-hidden="true"></div>
				<div className="absolute -left-24 bottom-0 h-72 w-72 rounded-full bg-orange-500/25 blur-3xl" aria-hidden="true"></div>
				<div className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-16 sm:px-6 md:py-20 lg:grid-cols-2 lg:px-8 lg:py-28">
					<div className="space-y-7">
						<p className="inline-flex rounded-full border border-white/25 bg-white/10 px-3 py-1 text-xs font-medium uppercase tracking-widest text-amber-200">
							14 restaurantes · 2 países · una misma experiencia
						</p>
						<h1 className="text-4xl font-extrabold leading-tight sm:text-5xl lg:text-6xl">
							El sabor de siempre,
							<span className="text-amber-300">impulsado por tecnología</span>
						</h1>
						<p className="max-w-xl text-base leading-relaxed text-stone-200 sm:text-lg">
							Brasaland transforma la cocina a la brasa en una experiencia confiable, rápida y humana. Operamos en
							dos mercados con estándares consistentes y ahora aceleramos nuestra evolución digital para tomar mejores
							decisiones, personalizar la relación con clientes y escalar sin perder nuestra esencia.
						</p>
						<ul className="grid gap-3 text-sm text-stone-200 sm:grid-cols-2" aria-label="Propuesta de valor de Brasaland">
							<li className="rounded-xl border border-white/20 bg-white/10 px-3 py-2">Servicio cálido y consistente en Colombia y Florida</li>
							<li className="rounded-xl border border-white/20 bg-white/10 px-3 py-2">Operación ágil para reducir tiempos de espera</li>
							<li className="rounded-xl border border-white/20 bg-white/10 px-3 py-2">Calidad de producto mantenida local por local</li>
							<li className="rounded-xl border border-white/20 bg-white/10 px-3 py-2">Visión digital orientada a crecimiento sostenible</li>
						</ul>
						<div className="flex flex-wrap gap-4">
							<a
								href="application.html"
								className="rounded-full bg-amber-300 px-6 py-3 text-sm font-bold uppercase tracking-wide text-stone-900 transition hover:bg-amber-200"
								>Enviar aplicación</a
							>
							<a
								href="#beneficios"
								className="rounded-full border border-white/35 px-6 py-3 text-sm font-semibold transition hover:bg-white/10"
								>Conocer beneficios</a
							>
						</div>
					</div>

					<article className="rounded-3xl border border-white/20 bg-black/20 p-6 shadow-2xl backdrop-blur">
						<h2 className="text-lg font-semibold text-amber-200">Brasaland en números</h2>
						<dl className="mt-6 grid grid-cols-2 gap-4">
							<div className="rounded-2xl bg-white/10 p-4">
								<dt className="text-xs uppercase tracking-widest text-stone-300">Restaurantes</dt>
								<dd className="mt-2 text-3xl font-extrabold">14</dd>
							</div>
							<div className="rounded-2xl bg-white/10 p-4">
								<dt className="text-xs uppercase tracking-widest text-stone-300">Países</dt>
								<dd className="mt-2 text-3xl font-extrabold">2</dd>
							</div>
							<div className="rounded-2xl bg-white/10 p-4">
								<dt className="text-xs uppercase tracking-widest text-stone-300">Equipo</dt>
								<dd className="mt-2 text-3xl font-extrabold">115+</dd>
							</div>
							<div className="rounded-2xl bg-white/10 p-4">
								<dt className="text-xs uppercase tracking-widest text-stone-300">Facturación anual</dt>
								<dd className="mt-2 text-3xl font-extrabold">$6M</dd>
							</div>
						</dl>
					</article>
				</div>
			</section>

			<section id="beneficios" className="bg-stone-100 py-20 text-stone-900">
				<div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
					<div className="mx-auto max-w-2xl text-center">
						<p className="text-sm font-semibold uppercase tracking-[0.2em] text-ember-700">Por qué Brasaland</p>
						<h2 className="mt-3 text-3xl font-extrabold sm:text-4xl">Nuestra experiencia convertida en valor real</h2>
					</div>

					<div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
						<article className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm">
							<h3 className="text-xl font-bold">Consistencia multi-sede</h3>
							<p className="mt-3 text-stone-600">
								Mantenemos recetas y estándares de servicio consistentes en Medellín y Florida, cuidando cada detalle
								de la experiencia.
							</p>
						</article>
						<article className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm">
							<h3 className="text-xl font-bold">Operación ágil en cocina</h3>
							<p className="mt-3 text-stone-600">
								Tenemos foco en velocidad, turnos eficientes y ejecución precisa para servir más rápido sin comprometer
								calidad.
							</p>
						</article>
						<article className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm">
							<h3 className="text-xl font-bold">Evolución digital estratégica</h3>
							<p className="mt-3 text-stone-600">
								Brasaland Digital impulsa decisiones basadas en datos, experiencia omnicanal y herramientas modernas
								para seguir creciendo.
							</p>
						</article>
					</div>
				</div>
			</section>

			<section id="contacto" className="bg-stone-900 py-20">
				<div className="mx-auto w-full max-w-5xl px-4 sm:px-6 lg:px-8">
					<article className="rounded-3xl border border-amber-300/30 bg-gradient-to-r from-ember-900/70 to-amber-700/40 p-8 text-center sm:p-10">
						<h2 className="text-3xl font-extrabold sm:text-4xl">¿Quieres colaborar con Brasaland?</h2>
						<p className="mx-auto mt-4 max-w-2xl text-stone-200">
							Cuéntanos quién eres y cómo quieres conectar con nosotros: talento, proveedores, alianzas o iniciativas
							digitales para transformar la experiencia del cliente.
						</p>
						<div className="mt-8 flex flex-wrap items-center justify-center gap-4">
							<Link
								href="/Form"
								className="rounded-full bg-amber-300 px-7 py-3 text-sm font-bold uppercase tracking-wide text-stone-900 transition hover:bg-amber-200"
                >Enviar aplicación</Link>
							<a href="mailto:hola@brasaland.com" className="rounded-full border border-white/35 px-7 py-3 text-sm font-semibold transition hover:bg-white/10"
								>hola@brasaland.com</a
							>
						</div>
					</article>
				</div>
			</section>
		</main>

		<footer className="border-t border-white/10 bg-stone-950">
			<div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-8 text-sm text-stone-400 sm:px-6 md:grid-cols-2 lg:grid-cols-3 lg:px-8">
				<div className="space-y-1">
					<p>© 2026 Brasaland. Todos los derechos reservados.</p>
					<p>Medellín, Colombia · Miami, Florida</p>
				</div>
				<div className="space-y-1">
					<p className="font-semibold text-stone-200">Contacto</p>
					<p>Email: <a href="mailto:hola@brasaland.com" className="transition hover:text-amber-300">hola@brasaland.com</a></p>
					<p>Tel: <a href="tel:+573001112233" className="transition hover:text-amber-300">+57 300 111 2233</a></p>
				</div>
				<div className="space-y-1">
					<p className="font-semibold text-stone-200">Horario de atención</p>
					<p>Lunes a viernes: 8:00 a.m. - 6:00 p.m.</p>
					<p>Sábados: 9:00 a.m. - 1:00 p.m.</p>
				</div>
			</div>
		</footer>
    </div>
  );
}
