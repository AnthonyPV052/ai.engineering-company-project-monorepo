#!/usr/bin/env python3
"""CLI runner for the RFP approval & final document pipeline (Parte 3).

Simulates the full approval flow from Part 2 → human approvals → arbitration
→ CEO approval → final document generation.

Usage:
    python scripts/run_rfp_part3.py <ticket_id>                  # Run Part 3 on an existing Part 2 ticket
    python scripts/run_rfp_part3.py <ticket_id> --auto-approve   # Auto-approve all departments (demo)
    python scripts/run_rfp_part3.py --from-pdf <pdf_path>        # Run Parts 1+2+3 end-to-end

Examples:
    python scripts/run_rfp_part3.py <ticket-uuid>
    python scripts/run_rfp_part3.py <ticket-uuid> --auto-approve
    python scripts/run_rfp_part3.py --from-pdf rfp-requests/brasaland/brasaland-request-1.pdf
"""

from __future__ import annotations

import json
import sys
import time
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

    # Mode 1: Run Parts 1+2+3 end-to-end from a PDF
    if args[0] == "--from-pdf" and len(args) >= 2:
        pdf_path = Path(args[1])
        if not pdf_path.exists():
            print(f"ERROR: File not found: {pdf_path}")
            sys.exit(1)

        ticket_id = str(uuid.uuid4())
        for i, arg in enumerate(args):
            if arg == "--ticket-id" and i + 1 < len(args):
                ticket_id = args[i + 1]

        auto_approve = "--auto-approve" in args

        print(f"\n{'='*60}")
        print(f"RFP Complete Pipeline — Partes 1 + 2 + 3")
        print(f"{'='*60}")
        print(f"PDF:        {pdf_path}")
        print(f"Ticket ID:  {ticket_id}")
        print(f"Auto-approve: {auto_approve}")
        print(f"{'='*60}\n")

        # ── Part 1 ──
        print("🔷 PARTE 1 — Análisis y Clasificación")
        print("-" * 40)
        from data.pipelines.rfp_intake.graph import run_pipeline
        result_p1 = run_pipeline(ticket_id=ticket_id, pdf_path=str(pdf_path))

        if result_p1.get("status") != "analisis_completo":
            print(f"\n📛 Part 1 failed. Status: {result_p1.get('status')}")
            reason = result_p1.get("classification_result", {}).get("classification_reason", "N/A")
            print(f"   Reason: {reason}")
            sys.exit(1)

        print(f"✅ Part 1 complete — Status: analisis_completo")
        client_name = result_p1.get("metadata", {}).get("client_name", "N/A")
        handoff_p1 = result_p1.get("handoff_payload", {})
        if isinstance(handoff_p1, str):
            try:
                handoff_p1 = json.loads(handoff_p1)
            except (json.JSONDecodeError, TypeError):
                handoff_p1 = {}
        departments = handoff_p1.get("departments_needed", [])
        print(f"   Client: {client_name}")
        print(f"   Departments needed: {', '.join(departments)}")
        print()

        # ── Part 2 ──
        print("🔷 PARTE 2 — Generación y Evaluación de Borradores")
        print("-" * 40)
        from data.pipelines.rfp_intake.graph_part2 import trigger_part2
        result_p2 = trigger_part2(ticket_id)
        part2_status = result_p2.get("status", "unknown")

        print(f"Result: {part2_status}")
        sections = result_p2.get("sections", [])
        if not sections:
            payload = result_p2.get("handoff_payload", {})
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}
            sections = payload.get("sections", [])

        for section in sections:
            dept = section.get("department_id", "?")
            eval_result = section.get("evaluation_result", {})
            passed = eval_result.get("overall_pass", False)
            needs_review = section.get("needs_human_review", False)
            status_icon = "✅" if passed and not needs_review else "⚠️" if needs_review else "❌"
            print(f"  {status_icon} {dept.capitalize()}: "
                  f"{'PASS' if passed else 'FAIL'}"
                  f"{' (needs review)' if needs_review else ''}")
        print()

        # ── Part 3 ──
        print("🔷 PARTE 3 — Aprobación, Arbitraje y Documento Final")
        print("-" * 40)
        run_part3(ticket_id, auto_approve=auto_approve)
        return

    # Mode 2: Run Part 3 on an existing ticket
    ticket_id = args[0]
    auto_approve = "--auto-approve" in args

    print(f"\n{'='*60}")
    print(f"RFP Approval Pipeline — Parte 3")
    print(f"{'='*60}")
    print(f"Ticket ID:  {ticket_id}")
    print(f"Auto-approve: {auto_approve}")
    print(f"{'='*60}\n")

    run_part3(ticket_id, auto_approve=auto_approve)


def run_part3(ticket_id: str, auto_approve: bool = False) -> None:
    """Run the Part 3 approval pipeline.

    Args:
        ticket_id: The ticket UUID.
        auto_approve: If True, automatically approve all departments (demo mode).
    """
    from data.pipelines.rfp_intake.graph_part3 import (
        trigger_part3,
        resume_ticket,
        DEPARTMENT_APPROVERS,
    )

    # ── Step 1: Enter Part 3 ──
    print("⏳ Entering Part 3 (saving checkpoints)...")
    result = trigger_part3(ticket_id)
    status = result.get("status", "unknown")
    departments = result.get("departments_needed", [])
    print(f"   Status: {status}")
    print(f"   Departments needing approval: {', '.join(departments)}")
    print()

    if auto_approve:
        # ── Step 2: Auto-approve each department ──
        for dept in departments:
            approver = DEPARTMENT_APPROVERS.get(dept, dept)
            print(f"⏳ {approver} approving '{dept}'...")
            result = resume_ticket(ticket_id, dept, "approve")
            current_status = result.get("status", "unknown")
            print(f"   → Status: {current_status}")
            print()

        # ── Step 3: Check for conflicts / CEO approval ──
        result = print_status(ticket_id, result)
    else:
        print("⏸️  Pipeline paused. Use the API to approve departments:")
        for dept in departments:
            approver = DEPARTMENT_APPROVERS.get(dept, dept)
            print(f"   POST /api/rfp/tickets/{ticket_id}/approve/{dept}")
            print(f"       Body: {{\"action\": \"approve\"}}  # by {approver}")
        print()
        print_status(ticket_id, result)


def print_status(ticket_id: str, result: dict) -> dict:
    """Print the current status and final document if available."""
    from data.pipelines.rfp_intake.graph_part3 import CEO_NAME, CEO_THRESHOLD_USD

    status = result.get("status", "unknown")
    usd = result.get("annual_estimated_usd")
    ceo_needed = result.get("ceo_approval_required", False)
    ceo_approved = result.get("ceo_approved", False)
    arbitration = result.get("arbitration_resolved", [])
    final_doc = result.get("final_document_content", "")
    errors = result.get("errors", [])

    print(f"📊 Pipeline Status: {status}")
    if usd:
        print(f"   Annual estimated value: USD ${usd:,.0f}")
    if ceo_needed:
        print(f"   CEO approval: {'✅ Approved' if ceo_approved else '⏳ Pending'} ({CEO_NAME})")
    if ceo_needed and not ceo_approved:
        print(f"   → POST /api/rfp/tickets/{ticket_id}/ceo-approve")
        print(f'       Body: {{"approved": true}}  # by {CEO_NAME}')

    if arbitration:
        print(f"   Arbitration records:")
        for r in arbitration:
            auto = " (auto)" if r.get("auto_resolved") else ""
            print(f"     {r['trigger_id']}: {r['resolution']}{auto} — {r['arbiter']}")

    if errors:
        print(f"   ⚠️  Errors: {', '.join(errors)}")

    if final_doc:
        print(f"\n📄 Documento Final Generado ({len(final_doc)} chars):")
        print("-" * 40)
        print(final_doc[:2000])
        if len(final_doc) > 2000:
            print(f"\n... ({len(final_doc) - 2000} chars more)")
        print("-" * 40)
    else:
        print(f"\n⏳ Documento final no generado aún (pendiente de aprobaciones)")

    return result


if __name__ == "__main__":
    main()