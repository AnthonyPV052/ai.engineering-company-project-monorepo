import Link from "next/link";

type NavbarProps = {
  mode?: "home" | "form";
};

export default function Navbar({ mode = "home" }: NavbarProps) {
  const isHome = mode === "home";
  const containerClass = isHome
    ? "mx-auto flex w-full items-center justify-between px-4 py-4 sm:px-6 lg:px-8"
    : "mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8";

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-stone-950/90 backdrop-blur">
      <div className={containerClass}>
        <Link href="/" className="flex items-center gap-3" aria-label="Inicio Brasaland">
          <img
            src="https://dummyimage.com/44x44/f97316/ffffff.png&text=B"
            alt="Logotipo de Brasaland"
            className="h-11 w-11 rounded-xl"
          />
          <div>
            <p className="text-lg font-bold tracking-tight text-white">Brasaland</p>
            <p className="text-xs text-stone-300">Cocina a la brasa · Colombia + Florida</p>
          </div>
        </Link>

        <details className="relative md:hidden">
          <summary
            className="list-none cursor-pointer rounded-lg border border-white/20 px-3 py-2 text-sm font-semibold text-stone-100 transition hover:bg-white/10"
            aria-label="Abrir menú de navegación"
          >
            Menú
          </summary>
          <nav
            aria-label="Navegación principal móvil"
            className="absolute right-0 mt-3 w-56 rounded-2xl border border-white/15 bg-stone-900/95 p-3 shadow-2xl"
          >
            <ul className="space-y-1 text-sm text-stone-100">
              <li>
                <Link href="/" className="block rounded-lg px-3 py-2 transition hover:bg-white/10">
                  Home
                </Link>
              </li>
              {isHome && (
                <>
                  <li>
                    <a href="#nosotros" className="block rounded-lg px-3 py-2 transition hover:bg-white/10">
                      Nosotros
                    </a>
                  </li>
                  <li>
                    <a href="#beneficios" className="block rounded-lg px-3 py-2 transition hover:bg-white/10">
                      Beneficios
                    </a>
                  </li>
                  <li>
                    <a href="#contacto" className="block rounded-lg px-3 py-2 transition hover:bg-white/10">
                      Contacto
                    </a>
                  </li>
                </>
              )}
              <li>
                <Link
                  href="/Form"
                  className="mt-1 block rounded-lg bg-ember-600 px-3 py-2 text-center font-semibold text-white [text-shadow:_2px_2px_0_#000] transition hover:bg-ember-700"
                >
                  Formulario
                </Link>
              </li>
              <li>
                <Link
                  href="/backoffice/incidents"
                  className="block rounded-lg px-3 py-2 transition hover:bg-white/10"
                >
                  Gestor de incidencias
                </Link>
              </li>
              <li>
                <Link
                  href="/backoffice/suppliers"
                  className="block rounded-lg px-3 py-2 transition hover:bg-white/10"
                >
                  Proveedores
                </Link>
              </li>
            </ul>
          </nav>
        </details>

        <nav aria-label="Navegación principal" className="hidden items-center gap-7 text-sm md:flex">
          <Link href="/" className="text-stone-100 transition hover:text-amber-300">
            Home
          </Link>
          {isHome && (
            <>
              <a href="#nosotros" className="text-stone-100 transition hover:text-amber-300">
                Nosotros
              </a>
              <a href="#beneficios" className="text-stone-100 transition hover:text-amber-300">
                Beneficios
              </a>
              <a href="#contacto" className="text-stone-100 transition hover:text-amber-300">
                Contacto
              </a>
            </>
          )}
          <Link
            href="/Form"
            className="rounded-full bg-ember-600 px-5 py-2.5 font-semibold text-white transition hover:bg-ember-700 [text-shadow:_2px_2px_0_#000]"
          >
            Formulario
          </Link>
          <Link
            href="/backoffice/incidents"
            className="rounded-full border border-white/25 px-5 py-2.5 font-semibold text-white transition hover:bg-white/10"
          >
            Gestor de incidencias
          </Link>
          <Link
            href="/backoffice/suppliers"
            className="rounded-full border border-amber-300/60 px-5 py-2.5 font-semibold text-amber-200 transition hover:bg-amber-300/10"
          >
            Proveedores
          </Link>
        </nav>
      </div>
    </header>
  );
}
