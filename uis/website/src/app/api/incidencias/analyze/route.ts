import { NextResponse } from "next/server";
import { analyzeIncidentRows, parseCsv, summaryToCsv } from "@/lib/incidents-analyzer";

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const file = formData.get("file");

    if (!(file instanceof File)) {
      return NextResponse.json(
        { error: "Debes adjuntar un archivo CSV en el campo 'file'." },
        { status: 400 },
      );
    }

    const text = await file.text();
    const rows = parseCsv(text);

    if (rows.length === 0) {
      return NextResponse.json(
        { error: "El CSV no contiene registros analizables." },
        { status: 400 },
      );
    }

    const result = analyzeIncidentRows(rows);
    const summaryCsv = summaryToCsv(result.resumen);

    return NextResponse.json({
      ...result,
      export_csv: summaryCsv,
      archivo: {
        nombre: file.name,
        tamanio_bytes: file.size,
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? `Error al procesar el archivo: ${error.message}`
            : "Error inesperado al procesar el archivo.",
      },
      { status: 500 },
    );
  }
}
