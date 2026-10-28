import { NextResponse } from "next/server";
import { getLastAnalysis } from "@/services/api/incidents/results-store";

export async function GET() {
  const last = getLastAnalysis();

  if (!last) {
    return NextResponse.json(
      {
        error:
          "No hay resultados disponibles para exportar. Ejecuta primero POST /api/incidents/analyze.",
      },
      { status: 404 },
    );
  }

  const filename = `results-${last.createdAt.slice(0, 19).replace(/[:T]/g, "-")}.csv`;

  return new NextResponse(last.csvExport, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename=\"${filename}\"`,
      "Cache-Control": "no-store",
    },
  });
}
