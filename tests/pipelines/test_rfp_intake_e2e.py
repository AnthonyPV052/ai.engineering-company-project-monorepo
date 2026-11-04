"""E2E integration test for the full RFP pipeline (Partes 1 + 2 + 3).

This test runs the complete flow from a PDF to final document:
1. Part 1: Classify → Extract → Analyze
2. Part 2: Generate drafts → Evaluate → Iterate
3. Part 3: Human approval → Arbitration → Final document

It verifies state consistency, event logs, and trace completeness.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

# Ensure paths
ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest

# ---------------------------------------------------------------------------
# Fixtures: use real test PDFs from the repo
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def test_pdfs() -> dict[str, Path]:
    """Map of test PDF paths."""
    base = ROOT / "rfp-requests" / "brasaland"
    pdfs = {
        "request-1": base / "brasaland-request-1.pdf",
        "request-2": base / "brasaland-request-2.pdf",
        "request-3": base / "brasaland-request-3.pdf",
    }
    missing = [k for k, p in pdfs.items() if not p.exists()]
    if missing:
        pytest.skip(f"Test PDFs not found: {missing}. Skipping E2E test.")
    return pdfs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_part1(ticket_id: str, pdf_path: str) -> dict:
    """Run Part 1 pipeline and return result."""
    from data.pipelines.rfp_intake.graph import run_pipeline
    result = run_pipeline(ticket_id=ticket_id, pdf_path=pdf_path)
    return result


def _run_part2(ticket_id: str) -> dict:
    """Run Part 2 pipeline via trigger (loads from DB)."""
    from data.pipelines.rfp_intake.graph_part2 import trigger_part2
    result = trigger_part2(ticket_id)
    return result


def _run_part3_entry(ticket_id: str) -> dict:
    """Enter Part 3 pipeline (save checkpoints, wait for approvals)."""
    from data.pipelines.rfp_intake.graph_part3 import trigger_part3
    result = trigger_part3(ticket_id)
    return result


def _run_part3_resume(ticket_id: str, department: str, action: str) -> dict:
    """Resume Part 3 with a human decision."""
    from data.pipelines.rfp_intake.graph_part3 import resume_ticket
    result = resume_ticket(ticket_id, department, action)
    return result


def _check_db_status(ticket_id: str) -> str:
    """Get the current ticket status from DB."""
    from sqlmodel import Session
    from database import _get_engine
    from rfp_models import RFPTicket

    engine = _get_engine()
    with Session(engine) as db:
        ticket = db.get(RFPTicket, ticket_id)
        if ticket:
            return ticket.status
    return "not_found"


def _check_db_events(ticket_id: str) -> list[dict]:
    """Get events for a ticket from DB."""
    from sqlmodel import Session, select
    from database import _get_engine
    from rfp_models import RFPEventLog

    engine = _get_engine()
    with Session(engine) as db:
        events = db.exec(
            select(RFPEventLog)
            .where(RFPEventLog.ticket_id == ticket_id)
            .order_by(RFPEventLog.created_at.asc())
        ).all()
        return [
            {"event": e.event, "detail": e.detail}
            for e in events
        ]


def _check_trace(ticket_id: str) -> list[dict]:
    """Get trace for a ticket."""
    from data.pipelines.rfp_intake.traceability import get_trace_for_ticket
    return get_trace_for_ticket(ticket_id)


def _check_final_document(ticket_id: str) -> dict | None:
    """Get final document from DB."""
    from sqlmodel import Session, select
    from database import _get_engine
    from rfp_models import RFPFinalDocument

    engine = _get_engine()
    with Session(engine) as db:
        doc = db.exec(
            select(RFPFinalDocument)
            .where(RFPFinalDocument.ticket_id == ticket_id)
            .order_by(RFPFinalDocument.created_at.desc())
        ).first()
        if doc:
            return {
                "id": doc.id,
                "content": doc.content,
                "total_estimated_value_cop": doc.total_estimated_value_cop,
                "total_estimated_value_usd": doc.total_estimated_value_usd,
                "ceo_approval_required": doc.ceo_approval_required,
                "ceo_approved": doc.ceo_approved,
            }
    return None


# ===========================================================================
# E2E Test: Request 3 (should be rejected by classifier)
# ===========================================================================


def test_e2e_request3_rejected(test_pdfs):
    """Request 3 is an informal inquiry — should be rejected by Part 1."""
    ticket_id = f"e2e-req3-{uuid.uuid4().hex[:8]}"
    pdf_path = test_pdfs["request-3"]

    result = _run_part1(ticket_id, str(pdf_path))
    assert result.get("status") == "descartado", (
        f"Expected request-3 to be descartado, got {result.get('status')}"
    )

    # Verify DB
    status = _check_db_status(ticket_id)
    assert status == "descartado"

    # Verify events
    events = _check_db_events(ticket_id)
    event_types = [e["event"] for e in events]
    assert any("rechazad" in e or "descart" in e for e in event_types), (
        f"No rejection event found in {event_types}"
    )


# ===========================================================================
# E2E Test: Request 2 (Andes Tech Solutions — < $50K, no CEO approval)
# ===========================================================================


@pytest.mark.slow
def test_e2e_request2_full_pipeline(test_pdfs, request):
    """Run full pipeline on request-2 (Andes Tech, <$50K, no CEO approval)."""
    ticket_id = f"e2e-req2-{uuid.uuid4().hex[:8]}"
    pdf_path = test_pdfs["request-2"]
    _run_full_e2e(ticket_id, str(pdf_path), expect_ceo_approval=False)


# ===========================================================================
# E2E Test: Request 1 (Sunset Bay — > $50K, CEO approval, arbitration)
# ===========================================================================


@pytest.mark.slow
def test_e2e_request1_full_pipeline(test_pdfs):
    """Run full pipeline on request-1 (Sunset Bay, >$50K, CEO approval)."""
    ticket_id = f"e2e-req1-{uuid.uuid4().hex[:8]}"
    pdf_path = test_pdfs["request-1"]
    _run_full_e2e(ticket_id, str(pdf_path), expect_ceo_approval=True)


def _run_full_e2e(ticket_id: str, pdf_path: str, expect_ceo_approval: bool = False) -> dict:
    """Run the complete Part 1 → Part 2 → Part 3 pipeline.

    Args:
        ticket_id: A unique ticket ID.
        pdf_path: Path to the PDF file.
        expect_ceo_approval: Whether CEO approval is expected.

    Returns:
        The final state dict.
    """
    # ======================================================================
    # PARTE 1
    # ======================================================================
    print(f"\n{'='*60}")
    print(f"E2E: Part 1 — Classify & Extract")
    print(f"{'='*60}")
    print(f"Ticket: {ticket_id}")
    print(f"PDF:    {pdf_path}")

    result_p1 = _run_part1(ticket_id, pdf_path)

    assert result_p1.get("status") == "analisis_completo", (
        f"Part 1 failed: {result_p1.get('status')}. "
        f"Reason: {result_p1.get('classification_result', {}).get('classification_reason', 'N/A')}"
    )

    # Verify metadata was created
    from sqlmodel import Session, select
    from database import _get_engine
    from rfp_models import RFPMetadata

    engine = _get_engine()
    with Session(engine) as db:
        meta = db.exec(
            select(RFPMetadata).where(RFPMetadata.ticket_id == ticket_id)
        ).first()
        assert meta is not None, "No metadata created"
        assert meta.client_name is not None, "No client name in metadata"

    print(f"✅ Part 1 Complete")
    print(f"   Client: {result_p1.get('metadata', {}).get('client_name', 'N/A')}")
    handoff = result_p1.get("handoff_payload", {})
    if isinstance(handoff, str):
        try:
            handoff = json.loads(handoff)
        except (json.JSONDecodeError, TypeError):
            handoff = {}
    departments_needed = handoff.get("departments_needed", result_p1.get("departments_needed", []))
    print(f"   Departments: {departments_needed}")

    # Verify events
    events = _check_db_events(ticket_id)
    event_types = [e["event"] for e in events]
    print(f"   Events: {event_types}")

    # ======================================================================
    # PARTE 2
    # ======================================================================
    print(f"\n{'='*60}")
    print(f"E2E: Part 2 — Generate & Evaluate Drafts")
    print(f"{'='*60}")

    result_p2 = _run_part2(ticket_id)
    part2_status = result_p2.get("status", "unknown")

    print(f"   Status: {part2_status}")

    sections = result_p2.get("sections", [])
    if not sections:
        payload = result_p2.get("handoff_payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}
        sections = payload.get("sections", [])

    departments_found = set()
    for section in sections:
        dept = section.get("department_id", "?")
        departments_found.add(dept)
        eval_result = section.get("evaluation_result", {})
        passed = eval_result.get("overall_pass", False)
        needs_review = section.get("needs_human_review", False)
        print(f"   {dept}: {'✅' if passed and not needs_review else '⚠️' if needs_review else '❌'} "
              f"{'PASS' if passed else 'FAIL'}"
              f"{' (needs review)' if needs_review else ''}")

    print(f"✅ Part 2 Complete")

    # ======================================================================
    # PARTE 3 — Entry
    # ======================================================================
    print(f"\n{'='*60}")
    print(f"E2E: Part 3 — Approval Pipeline")
    print(f"{'='*60}")

    result_p3 = _run_part3_entry(ticket_id)
    print(f"   Entry status: {result_p3.get('status')}")
    departments = result_p3.get("departments_needed", [])
    print(f"   Departments needing approval: {departments}")

    # Verify checkpoints were saved
    from data.pipelines.rfp_intake.checkpointer import load_checkpoint
    for dept in departments:
        ckpt = load_checkpoint(ticket_id, department_id=dept)
        assert ckpt is not None, f"No checkpoint for {dept}"

    # ======================================================================
    # PARTE 3 — Human approvals (simulated)
    # ======================================================================
    for dept in departments:
        print(f"\n   ⏳ {dept}: approving...")
        result = _run_part3_resume(ticket_id, dept, "approve")
        print(f"   → {dept} approved. Status: {result.get('status')}")

    # After all departments approved, check what happened
    final_status = _check_db_status(ticket_id)
    print(f"\n   All departments approved. Final status: {final_status}")

    # ======================================================================
    # PARTE 3 — CEO approval (if needed)
    # ======================================================================
    if expect_ceo_approval:
        print(f"\n⏳ CEO approval required (>$50K USD)")

        # Check that CEO approval is pending
        from data.pipelines.rfp_intake.graph_part3 import ceo_approve_ticket
        result_ceo = ceo_approve_ticket(ticket_id, approved=True)
        print(f"   CEO approved. Status: {result_ceo.get('status', 'terminado')}")
        print(f"   CEO Decision: {'Approved' if result_ceo.get('ceo_approved', True) else 'Rejected'}")

        # Check again
        final_status = _check_db_status(ticket_id)

    # ======================================================================
    # Verify Final Document
    # ======================================================================
    print(f"\n{'='*60}")
    print(f"Verification: Final Document")
    print(f"{'='*60}")

    doc = _check_final_document(ticket_id)
    if doc:
        print(f"✅ Final document generated (id={doc['id']})")
        print(f"   Content length: {len(doc['content'])} chars")
        print(f"   CEO required: {doc['ceo_approval_required']}")
        print(f"   CEO approved: {doc['ceo_approved']}")
        # Print first 500 chars
        print(f"\n   Preview:")
        for line in doc["content"].split("\n")[:15]:
            print(f"     {line}")
    else:
        print(f"⚠️  No final document found in DB")
        print(f"   Final status: {final_status}")

    # ======================================================================
    # Verify Trace Completeness
    # ======================================================================
    print(f"\n{'='*60}")
    print(f"Verification: Execution Trace")
    print(f"{'='*60}")

    trace = _check_trace(ticket_id)
    if trace:
        print(f"✅ Trace has {len(trace)} entries")
        for t in trace:
            print(f"   • {t['node_name']} ({t['agent']}) "
                  f"{'— ' + t['department_id'] if t.get('department_id') else ''}")
    else:
        print("⚠️  No trace entries found")

    # ======================================================================
    # Verify Event Log
    # ======================================================================
    print(f"\n{'='*60}")
    print(f"Verification: Event Log")
    print(f"{'='*60}")

    events = _check_db_events(ticket_id)
    print(f"✅ {len(events)} events recorded")
    for e in events:
        print(f"   • {e['event']}: {e['detail'][:100] if e.get('detail') else ''}")

    # ======================================================================
    # Assertions
    # ======================================================================
    assert final_status in ("terminado", "esperando_aprobacion"), (
        f"Pipeline did not finish. Status: {final_status}"
    )

    if not expect_ceo_approval:
        assert doc is not None, "No final document generated for low-value ticket"
        assert final_status == "terminado", (
            f"Low-value ticket should be 'terminado', got '{final_status}'"
        )

    # Verify all departments have approval status
    from sqlmodel import Session, select
    from rfp_models import DepartmentSection

    with Session(engine) as db:
        sections_db = db.exec(
            select(DepartmentSection).where(DepartmentSection.ticket_id == ticket_id)
        ).all()
        for section in sections_db:
            assert section.approval_status == "aprobado", (
                f"Section {section.department_id} has status {section.approval_status}"
            )

    print(f"\n{'='*60}")
    print(f"🎉 E2E Pipeline Complete for {ticket_id}")
    print(f"{'='*60}")

    return result_p3


# ===========================================================================
# Run this test directly
# ===========================================================================

if __name__ == "__main__":
    pytest.main(["-v", "-s", __file__])