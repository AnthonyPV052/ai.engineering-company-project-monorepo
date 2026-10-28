import { NextResponse } from "next/server";
import {
  AnalyzeInputError,
  analyzeIncidentsCsvWithScript,
} from "@/services/api/incidents/analysis-service";
import { saveLastAnalysis } from "@/services/api/incidents/results-store";
import { logError } from "@/lib/logger"; // Usa tu logger real

export async function POST(request: Request) {
  // --- FASE 1: Validación de multipart/form-data ---
  let formData: FormData;
  try {
    const contentType = request.headers.get("content-type") ?? "";
    if (!contentType.includes("multipart/form-data")) {
      return NextResponse.json(
        {
          error:
            "Formato de petición incorrecto: usa multipart/form-data con el campo 'file'.",
        },
        { status: 400 },
      );
    }

    formData = await request.formData();
  } catch (error) {
    logError("Error al procesar multipart/form-data", error);
    return NextResponse.json(
      { error: "No se pudo procesar la petición. Intenta de nuevo." },
      { status: 400 },
    );
  }

  // --- FASE 2: Validación del fichero ---
  let file: File;
  try {
    const maybeFile = formData.get("file");

    if (!(maybeFile instanceof File)) {
      return NextResponse.json(
        { error: "Debes adjuntar un fichero CSV en el campo 'file'." },
        { status: 400 },
      );
    }

    file = maybeFile;

    if (file.size === 0) {
      return NextResponse.json(
        { error: "El fichero CSV está vacío." },
        { status: 400 },
      );
    }

    if (!file.name.toLowerCase().endsWith(".csv")) {
      return NextResponse.json(
        { error: "Formato incorrecto: el fichero debe tener extensión .csv." },
        { status: 422 },
      );
    }
  } catch (error) {
    logError("Error al validar el fichero CSV", error);
    return NextResponse.json(
      { error: "No se pudo validar el fichero CSV." },
      { status: 400 },
    );
  }

  // --- FASE 3: Lectura del CSV ---
  let csvText: string;
  try {
    csvText = await file.text();
  } catch (error) {
    logError("Error al leer el contenido del fichero CSV", error);
    return NextResponse.json(
      { error: "No se pudo leer el fichero CSV." },
      { status: 400 },
    );
  }

  // --- FASE 4: Análisis del CSV con el script ---
  let result: any;
  let csvExport: string;
  try {
    const analysis = await analyzeIncidentsCsvWithScript(csvText, file.name);
    result = analysis.result;
    csvExport = analysis.csvExport;
  } catch (error) {
    if (error instanceof AnalyzeInputError) {
      // Este error es seguro porque tú lo controlas
      return NextResponse.json({ error: error.message }, { status: error.status });
    }

    // Error inesperado del script → NO exponer error.message
    logError("Error inesperado en analyzeIncidentsCsvWithScript", error);

    return NextResponse.json(
      {
        error:
          "No hemos podido analizar el fichero CSV. Intenta de nuevo más tarde.",
      },
      { status: 500 },
    );
  }

  // --- FASE 5: Guardado del resultado ---
  try {
    saveLastAnalysis({
      filename: file.name,
      csvExport,
      result,
      createdAt: new Date().toISOString(),
    });
  } catch (error) {
    logError("Error al guardar el resultado del análisis", error);
    // No romper la respuesta al usuario
  }

  // --- FASE 6: Respuesta final ---
  return NextResponse.json({
    ...result,
    archivo: {
      nombre: file.name,
      tamanio_bytes: file.size,
    },
  });
}

