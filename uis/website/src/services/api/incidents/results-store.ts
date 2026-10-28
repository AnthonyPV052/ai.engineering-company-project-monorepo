import type { IncidentsAnalysisResponse } from "@/services/api/incidents/analysis-service";

interface LastAnalysisPayload {
  csvExport: string;
  result: IncidentsAnalysisResponse;
  filename: string;
  createdAt: string;
}

let lastAnalysis: LastAnalysisPayload | null = null;

export function saveLastAnalysis(payload: LastAnalysisPayload): void {
  lastAnalysis = payload;
}

export function getLastAnalysis(): LastAnalysisPayload | null {
  return lastAnalysis;
}
