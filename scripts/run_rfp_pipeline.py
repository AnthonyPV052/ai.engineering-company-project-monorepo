#!/usr/bin/env python3
"""CLI runner for the RFP intake pipeline.

Usage:
    python scripts/run_rfp_pipeline.py <pdf_path> [--ticket-id <id>]

Examples:
    python scripts/run_rfp_pipeline.py rfp-requests/brasaland/brasaland-request-1.pdf
    python scripts/run_rfp_pipeline.py rfp-requests/brasaland/brasaland-request-2.pdf
    python scripts/run_rfp_pipeline.py rfp-requests/brasaland/brasaland-request-3.pdf
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# Ensure paths
ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(1)

    pdf_path = Path(args[0])
    ticket_id = str(uuid.uuid4())

    for i, arg in enumerate(args):
        if arg == "--ticket-id" and i + 1 < len(args):
            ticket_id = args[i + 1]

    if not pdf_path.exists():
        print(f"ERROR: File not found: {pdf_path}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"RFP Intake Pipeline — Parte 1")
    print(f"{'='*60}")
    print(f"PDF:        {pdf_path}")
    print(f"Ticket ID:  {ticket_id}")
    print(f"{'='*60}\n")

    # Run the graph pipeline (this persists to DB too)
    from data.pipelines.rfp_intake.graph import run_pipeline

    result = run_pipeline(ticket_id=ticket_id, pdf_path=str(pdf_path))

    print(f"\n{'='*60}")
    print(f"Status: {result.get('status', 'unknown')}")
    print(f"{'='*60}\n")

    if result.get("status") == "descartado":
        reason = result.get("classification_result", {}).get("classification_reason", "N/A")
        print(f"📛 Documento DESCARTADO.")
        print(f"   Razón: {reason}")
        return

    if result.get("status") == "analisis_completo":
        print(f"✅ Análisis COMPLETO.\n")

        departments = result.get("departments_needed", [])
        print(f"Departamentos involucrados: {', '.join(departments)}")
        print()

        metadata = result.get("metadata", {})
        print(f"Cliente:     {metadata.get('client_name', 'N/A')}")
        print(f"Ubicación:   {metadata.get('location', 'N/A')}")
        print(f"Servicio:    {metadata.get('service_type', 'N/A')}")
        print(f"Presupuesto: {metadata.get('budget_range', 'N/A')}")
        print(f"Plazo:       {metadata.get('deadline', 'N/A')}")
        print()

        # Readability
        rm = result.get("readability_metrics", {})
        if rm.get("flesch_kincaid_grade"):
            print(f"📊 Legibilidad: FK={rm['flesch_kincaid_grade']}, "
                  f"Fog={rm['gunning_fog']}, "
                  f"Palabras={rm['word_count']}")
            print()

        # Workers
        for dept_id, worker_result in result.get("worker_results", {}).items():
            label = {
                "marketing": "Marketing",
                "operaciones": "Operaciones",
                "procurement": "Procurement",
                "training": "Training",
            }.get(dept_id, dept_id)
            print(f"── {label} ──")
            print(worker_result.get("key_aspects", "N/A")[:500])
            if worker_result.get("open_questions"):
                print(f"\n  ❓ Preguntas: {worker_result['open_questions']}")
            print()

        # Handoff preview
        print("── Handoff payload (vista previa) ──")
        handoff = result.get("handoff_payload", "")
        if handoff:
            try:
                preview = json.loads(handoff)
                print(json.dumps(preview, indent=2, ensure_ascii=False)[:1000])
            except json.JSONDecodeError:
                print(handoff[:500])
        print()
    else:
        print(f"Estado inesperado: {result.get('status')}")
        if result.get("errors"):
            print(f"Errores: {result['errors']}")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()