#!/usr/bin/env python3
"""CLI runner for the RFP response generation pipeline (Parte 2).

Consumes a Part 1 handoff payload and generates draft proposals.

Usage:
    python scripts/run_rfp_part2.py <ticket_id>
    python scripts/run_rfp_part2.py --from-pdf <pdf_path>

Examples:
    python scripts/run_rfp_part2.py <ticket-uuid>
    python scripts/run_rfp_part2.py --from-pdf rfp-requests/brasaland/brasaland-request-1.pdf
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

    # Mode 1: Run Part 1 first, then Part 2
    if args[0] == "--from-pdf" and len(args) >= 2:
        pdf_path = Path(args[1])
        if not pdf_path.exists():
            print(f"ERROR: File not found: {pdf_path}")
            sys.exit(1)

        ticket_id = str(uuid.uuid4())
        for i, arg in enumerate(args):
            if arg == "--ticket-id" and i + 1 < len(args):
                ticket_id = args[i + 1]

        print(f"\n{'='*60}")
        print(f"RFP Response Pipeline — Partes 1 + 2")
        print(f"{'='*60}")
        print(f"PDF:        {pdf_path}")
        print(f"Ticket ID:  {ticket_id}")
        print(f"{'='*60}\n")

        # Run Part 1
        from data.pipelines.rfp_intake.graph import run_pipeline
        result_part1 = run_pipeline(ticket_id=ticket_id, pdf_path=str(pdf_path))

        if result_part1.get("status") != "analisis_completo":
            print(f"\n📛 Part 1 failed. Status: {result_part1.get('status')}")
            reason = result_part1.get("classification_result", {}).get("classification_reason", "N/A")
            print(f"   Reason: {reason}")
            sys.exit(1)

        print(f"\n✅ Part 1 complete. Status: analisis_completo\n")
        handoff = json.loads(result_part1.get("handoff_payload", "{}"))

        # Run Part 2
        print(f"{'='*60}")
        print(f"Parte 2 — Generación y Evaluación de Borradores")
        print(f"{'='*60}\n")
        _run_part2(ticket_id, handoff)
        return

    # Mode 2: Load ticket from DB and run Part 2
    ticket_id = args[0]
    print(f"\n{'='*60}")
    print(f"RFP Response Pipeline — Parte 2")
    print(f"{'='*60}")
    print(f"Ticket ID:  {ticket_id}")
    print(f"{'='*60}\n")

    from data.pipelines.rfp_intake.graph_part2 import trigger_part2
    result = trigger_part2(ticket_id)
    _print_results(ticket_id, result)
    return


def _run_part2(ticket_id: str, handoff: dict) -> None:
    """Run Part 2 pipeline and print results."""
    from data.pipelines.rfp_intake.graph_part2 import run_response_pipeline
    result = run_response_pipeline(ticket_id, handoff)
    _print_results(ticket_id, result)


def _print_results(ticket_id: str, result: dict) -> None:
    """Print Part 2 results to stdout."""
    status = result.get("status", "unknown")
    print(f"Status: {status}\n")

    handoff = result.get("handoff_payload", result.get("handoff_to_part3", "{}"))
    if isinstance(handoff, str):
        try:
            payload = json.loads(handoff)
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = handoff

    sections = payload.get("sections", [])
    evaluations = result.get("evaluations", {})
    handoff_payload = result.get("handoff_payload", {})

    # If no sections in payload, build from state
    if not sections:
        departments = handoff_payload.get("departments_needed", [])
        drafts = result.get("drafts", {})
        for dept_id in departments:
            draft = drafts.get(dept_id, "")
            eval_result = evaluations.get(dept_id, {})
            overall_pass = eval_result.get("overall_pass", False)
            needs_review = dept_id in result.get("sections_needing_review", [])

            status_icon = "✅" if overall_pass and not needs_review else "⚠️" if needs_review else "❌"
            print(f"{status_icon} {dept_id.capitalize()}")
            if needs_review:
                print(f"   ⚠️  Needs human review (iteration limit)")
            print(f"   Evaluation: {'PASS' if overall_pass else 'FAIL'}")
            print(f"   Draft: {len(draft)} chars")
            print(f"   Feedback: {eval_result.get('feedback_for_generator', 'N/A')[:150]}")
            print()

        if evaluations:
            readability_ok = all(
                e.get("readability", {}).get("pass", False)
                for e in evaluations.values()
            )
            relevance_ok = all(
                e.get("relevance", {}).get("pass", False)
                for e in evaluations.values()
            )
            compliance_ok = all(
                e.get("compliance", {}).get("pass", False)
                for e in evaluations.values()
            )

            print(f"📊 Resumen de evaluaciones:")
            print(f"   Legibilidad:  {'✅' if readability_ok else '❌'} "
                  f"({sum(1 for e in evaluations.values() if e.get('readability',{}).get('pass',False))}/{len(evaluations)} pass)")
            print(f"   Pertinencia:  {'✅' if relevance_ok else '❌'} "
                  f"({sum(1 for e in evaluations.values() if e.get('relevance',{}).get('pass',False))}/{len(evaluations)} pass)")
            print(f"   Cumplimiento: {'✅' if compliance_ok else '❌'} "
                  f"({sum(1 for e in evaluations.values() if e.get('compliance',{}).get('pass',False))}/{len(evaluations)} pass)")
            print()

        needs_review = result.get("sections_needing_review", [])
        if needs_review:
            print(f"⚠️  Secciones que requieren revisión humana: {', '.join(needs_review)}")
        print()

    else:
        # Print from part3 payload
        passed = payload.get("sections_passed", 0)
        failed = payload.get("sections_failed", 0)
        needs_review_count = payload.get("sections_needing_human_review", 0)
        avg_iters = payload.get("average_iterations", 0)

        for section in sections:
            dept_id = section["department_id"]
            eval_result = section.get("evaluation_result", {})
            overall_pass = eval_result.get("overall_pass", False)
            needs_review = section.get("needs_human_review", False)

            status_icon = "✅" if overall_pass and not needs_review else "⚠️" if needs_review else "❌"
            print(f"{status_icon} {dept_id.capitalize()}")
            if needs_review:
                print(f"   ⚠️  Needs human review")
            print(f"   Evaluation: {'PASS' if overall_pass else 'FAIL'}")
            draft_len = len(section.get("draft_content", ""))
            print(f"   Draft: {draft_len} chars")
            print()
            compliance = eval_result.get("compliance", {})
            if not compliance.get("pass", True):
                for v in compliance.get("violations", []):
                    print(f"   ⚠️  Compliance: {v}")
                print()

        print(f"📊 Totales: {passed}/{passed + failed} secciones pasaron, "
              f"{needs_review_count} necesitan revisión, "
              f"{avg_iters} iteraciones promedio")
        print()

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()