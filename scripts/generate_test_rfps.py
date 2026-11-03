"""Generate test RFP PDFs for Brasaland pipeline development.

Produces three PDFs under rfp-requests/brasaland/ matching the specs in
the BRIEFING:

  1. brasaland-request-1.pdf — RFP formal (Sunset Bay Resorts)
  2. brasaland-request-2.pdf — RFP informal (Andes Tech Solutions)
  3. brasaland-request-3.pdf — inválido (sin alcance, sin presupuesto)

Usage:
    python scripts/generate_test_rfps.py
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "rfp-requests" / "brasaland"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class RFPPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(200, 80, 30)
        self.cell(0, 8, "BRASALAND FOOD GROUP", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Pagina {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str) -> None:
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 80, 30)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def body_text(self, text: str) -> None:
        self.set_font("Helvetica", "", 10)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5.5, text)
        self.ln(2)


def build_request_1() -> None:
    """RFP formal: Sunset Bay Resorts — concesión co-branded, ~60-75k USD/año."""
    pdf = RFPPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 14, "Solicitud de Propuesta (RFP)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, "Emision: 15 de octubre de 2025", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # --- Información del cliente ---
    pdf.section_title("Informacion del Cliente")
    pdf.body_text(
        "Razon Social: Sunset Bay Hospitality Group Inc.\n"
        "Nombre Comercial: Sunset Bay Resorts\n"
        "Direccion: 4500 Ocean Drive, Miami Beach, FL 33139, Estados Unidos\n"
        "Contacto: Sra. Victoria Hamilton, Directora de Operaciones Hoteleras\n"
        "Email: v.hamilton@sunsetbayresorts.com\n"
        "Telefono: +1 (305) 555-0198"
    )

    # --- Tipo de servicio ---
    pdf.section_title("Tipo de Servicio Solicitado")
    pdf.body_text(
        "Concesion de restaurante co-branded (Sunset Bay x Brasaland) en tres (3) resorts:\n"
        "  - Sunset Bay Miami Beach (Florida) - Lobby principal, 180 m2\n"
        "  - Sunset Bay Key West (Florida) - Terraza frente al mar, 120 m2\n"
        "  - Sunset Bay Orlando (Florida) - Piscina principal, 200 m2\n\n"
        "Se espera una experiencia de 'menu de autor' que fusione la identidad "
        "Brasaland con la propuesta gastronomica de cada resort. Exclusividad "
        "alimentaria dentro de cada propiedad."
    )

    # --- Volumen / Alcance ---
    pdf.section_title("Volumen y Alcance")
    pdf.body_text(
        "Comensales estimados: 450 cubiertos/dia en temporada alta, "
        "250 cubiertos/dia en temporada baja.\n"
        "Duracion del contrato: 3 anos renovables.\n"
        "Valor estimado del contrato: USD 60,000 - USD 75,000 anuales.\n"
        "Las partes acordaran un revenue share del 12% sobre ventas netas."
    )

    # --- Fecha límite ---
    pdf.section_title("Fecha Limite para Responder")
    pdf.body_text(
        "La propuesta debe ser recibida a mas tardar el 30 de noviembre de 2025. "
        "Se espera que el servicio comience en marzo de 2026, previa temporada de "
        "capacitacion del personal del resort durante febrero de 2026."
    )

    pdf.output(str(OUTPUT_DIR / "brasaland-request-1.pdf"))
    print(f"  Creado: {OUTPUT_DIR / 'brasaland-request-1.pdf'}")


def build_request_2() -> None:
    """RFP informal: Andes Tech Solutions — catering semanal, menú estándar."""
    pdf = RFPPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, "Solicitud de Servicio de Catering", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.section_title("Datos del Solicitante")
    pdf.body_text(
        "Empresa: Andes Tech Solutions S.A.S.\n"
        "Contacto: Sr. Andres Marin, Gerente Administrativo\n"
        "Email: a.marin@andestech.com\n"
        "Direccion: Carrera 43A # 1-50, Torre Sur, Piso 12, Medellin, Colombia\n"
        "Telefono: +57 (604) 555-0234"
    )

    pdf.section_title("Servicio Requerido")
    pdf.body_text(
        "Buen dia,\n\n"
        "Por medio de la presente, solicitamos una propuesta para servicio de "
        "catering semanal dirigido a nuestros colaboradores. Actualmente tenemos "
        "220 empleados en nuestra sede de Medellin y nos gustaria ofrecerles "
        "almuerzo de lunes a viernes.\n\n"
        "Buscamos un menu estandar (no necesariamente personalizado) con opcion "
        "de eleccion entre dos platos principales cada dia. El servicio seria "
        "en nuestro comedor corporativo (140 m2), que ya cuenta con cocina "
        "industrial basica.\n\n"
        "El contrato seria por 12 meses, con posibilidad de renovacion."
    )

    pdf.section_title("Detalles Operativos")
    pdf.body_text(
        "Horario sugerido: 12:00 p.m. a 2:00 p.m., de lunes a viernes.\n"
        "Presupuesto estimado: COP 18,000,000 - COP 22,000,000 mensuales.\n"
        "Inicio estimado: Enero 2026.\n\n"
        "Agradecemos nos hagan llegar una propuesta con costos desglosados "
        "y opciones de menu. Quedamos atentos a cualquier visita tecnica "
        "que requieran para ajustar la propuesta."
    )

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, "Nota: Esta solicitud se envia por correo electronico "
                         "a modo de carta de intencion. Agradecemos confirmar "
                         "recibido.")

    pdf.output(str(OUTPUT_DIR / "brasaland-request-2.pdf"))
    print(f"  Creado: {OUTPUT_DIR / 'brasaland-request-2.pdf'}")


def build_request_3() -> None:
    """Documento inválido: consulta de franquicia sin alcance ni presupuesto."""
    pdf = RFPPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, "Consulta de Oportunidad Comercial", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.section_title("Informacion General")
    pdf.body_text(
        "Nombre: Carlos Mendez\n"
        "Telefono: +57 (315) 555-9876\n"
        "Email: cmendez@email.com\n\n"
        "Hola, estoy interesado en abrir un restaurante Brasaland en mi ciudad. "
        "Siempre he sido fan de la marca y creo que tendria exito aca. "
        "Podrian darme mas informacion sobre requisitos y costos?"
    )

    pdf.section_title("Sobre la Ubicacion")
    pdf.body_text(
        "Todavia no tengo un local definido, pero estoy explorando opciones "
        "en el centro de la ciudad. Creo que un local de unos 80 m2 estaria "
        "bien para empezar.\n\n"
        "Quedo atento a su respuesta. Muchas gracias."
    )

    # Sin fecha límite, sin presupuesto, sin alcance de servicio claro
    pdf.output(str(OUTPUT_DIR / "brasaland-request-3.pdf"))
    print(f"  Creado: {OUTPUT_DIR / 'brasaland-request-3.pdf'}")


def main() -> None:
    print("Generando PDFs de prueba para Brasaland RFP...")
    build_request_1()
    build_request_2()
    build_request_3()
    print("Listo.")


if __name__ == "__main__":
    main()