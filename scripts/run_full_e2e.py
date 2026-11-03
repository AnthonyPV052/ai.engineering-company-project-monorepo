#!/usr/bin/env python3
"""E2E script: create Part 3 DB tables, run Part 1→2→3, verify everything.

Usage:
    export $(grep -v '^\s*#' .env | xargs)
    python scripts/run_full_e2e.py [--pdf <path>] [--auto-approve] [--setup-only]
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("run_full_e2e")


def setup_db_tables() -> None:
    """Create all Part 3 tables in the database."""
    from sqlmodel import SQLModel, Session
    from database import _get_engine
    from rfp_models import (
        RFPNodeExecution, RFPCheckpoint, RFPFinalDocument, RFPArbitrationRecord,
    )

    engine = _get_engine()
    logger.info("Creating Part 3 tables...")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            RFPNodeExecution.__table__,
            RFPCheckpoint.__table__,
            RFPFinalDocument.__table__,
            RFPArbitrationRecord.__table__,
        ],
        checkfirst=True,
    )
    logger.info("Tables verified/created.")


def run_pipeline(ticket_id: str, pdf_path: str, auto_approve: bool = False) -> dict:
    """Run Parts 1+2+3 and return the final state."""

    # ── Part 1 ──
    print(f"\n{'='*60}")
    print(f"🔷 PARTE 1 — Análisis y Clasificación")
    print(f"{'='*60}")

    from data.pipelines.rfp_intake.graph import run_pipeline as run_part1
    result_p1 = run_part1(ticket_id=ticket_id, pdf_path=pdf_path)

    status = result_p1.get("status", "???")
    print(f"   Status: {status}")
    if status != "analisis_completo":
        reason = result_p1.get("classification_result", {}).get(
            "classification_reason", "N/A"
        )
        print(f"   Reason: {reason}")
        return result_p1

    handoff_p1 = result_p1.get("handoff_payload", {})
    if isinstance(handoff_p1, str):
        try:
            handoff_p1 = json.loads(handoff_p1)
        except Exception:
            handoff_p1 = {}
    client_name = handoff_p1.get("client_name", result_p1.get("metadata", {}).get("client_name", "N/A"))
    departments = handoff_p1.get("departments_needed", [])
    print(f"   Client: {client_name}")
    print(f"   Departments: {departments}")
    annual_usd = handoff_p1.get("metadata", {}).get("annual_estimated_usd", "?")
    print(f"   Annual est. USD: ${annual_usd}")
    print(f"✅ Part 1 complete.")

    # ── Part 2 ──
    print(f"\n{'='*60}")
    print(f"🔷 PARTE 2 — Generación y Evaluación de Borradores")
    print(f"{'='*60}")

    from data.pipelines.rfp_intake.graph_part2 import trigger_part2
    result_p2 = trigger_part2(ticket_id)
    part2_status = result_p2.get("status", "unknown")
    print(f"   Status: {part2_status}")

    sections = result_p2.get("sections", [])
    if not sections:
        payload = result_p2.get("handoff_payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        sections = payload.get("sections", [])

    for section in sections:
        dept = section.get("department_id", "?")
        eval_result = section.get("evaluation_result", {})
        if isinstance(eval_result, str):
            try:
                eval_result = json.loads(eval_result)
            except Exception:
                eval_result = {}
        passed = eval_result.get("overall_pass", False)
        print(f"   {dept}: {'✅' if passed else '❌'}")

    print(f"✅ Part 2 complete.")

    # ── Part 3 — Entry ──
    print(f"\n{'='*60}")
    print(f"🔷 PARTE 3 — Aprobación, Arbitraje y Documento Final")
    print(f"{'='*60}")

    from data.pipelines.rfp_intake.graph_part3 import trigger_part3, resume_ticket, ceo_approve_ticket
    from data.pipelines.rfp_intake.checkpointer import load_checkpoint

    result_p3 = trigger_part3(ticket_id)
    print(f"   Entry status: {result_p3.get('status')}")

    departments_p3 = result_p3.get("departments_needed", departments or [])
    print(f"   Departments needing approval: {departments_p3}")

    # Check checkpoints
    for dept in departments_p3:
        ckpt = load_checkpoint(ticket_id, department_id=dept)
        if ckpt:
            print(f"   ✅ Checkpoint saved for {dept}")
        else:
            print(f"   ⚠️  No checkpoint for {dept}")

    # ── Part 3 — Human approvals (simulated) ──
    if auto_approve:
        print(f"\n{'─'*40}")
        print(f"Auto-approving all departments...")
        for dept in departments_p3:
            print(f"   👤 {dept}: approving...")
            result = resume_ticket(ticket_id, dept, "approve")
            status_after = result.get("status", "?")
            print(f"   → {dept} approved. Status: {status_after}")

        # Check final status
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPTicket

        engine = _get_engine()
        with Session(engine) as db:
            ticket = db.get(RFPTicket, ticket_id)
            final_status = ticket.status if ticket else "not_found"
        print(f"\n   Final ticket status: {final_status}")

        # ── CEO approval (if needed) ──
        if result_p3.get("ceo_approval_required", False):
            print(f"\n{'─'*40}")
            print(f"🔷 CEO Approval Required (>$50K USD)")
            print(f"{'─'*40}")
            result_ceo = ceo_approve_ticket(ticket_id, approved=True)
            ceo_approved = result_ceo.get("ceo_approved", True)
            print(f"   CEO Decision: {'✅ Approved' if ceo_approved else '❌ Rejected'}")

        # ── Verify final document ──
        print(f"\n{'─'*40}")
        print(f"📄 Final Document Verification")
        print(f"{'─'*40}")

        from sqlmodel import Session, select
        from database import _get_engine
        from rfp_models import RFPFinalDocument, RFPNodeExecution, RFPArbitrationRecord

        engine = _get_engine()
        with Session(engine) as db:
            doc = db.exec(
                select(RFPFinalDocument)
                .where(RFPFinalDocument.ticket_id == ticket_id)
                .order_by(RFPFinalDocument.created_at.desc())
            ).first()

            if doc:
                print(f"✅ Document generated (id={doc.id})")
                print(f"   Content length: {len(doc.content)} chars")
                print(f"   CEO required: {doc.ceo_approval_required}")
                print(f"   CEO approved: {doc.ceo_approved}")
                print(f"\n   Preview:")
                for line in doc.content.split("\n")[:15]:
                    print(f"     {line}")

                # Check if CEO approval appears in content
                if doc.ceo_approval_required:
                    if "Mariana Restrepo" in doc.content or "CEO" in doc.content:
                        print(f"\n   ✅ CEO approval note found in document")
                    else:
                        print(f"\n   ⚠️  No CEO approval mention in document")
            else:
                print("⚠️  No final document generated")

            # Check trace
            trace = db.exec(
                select(RFPNodeExecution)
                .where(RFPNodeExecution.ticket_id == ticket_id)
                .order_by(RFPNodeExecution.created_at.asc())
            ).all()
            print(f"\n📋 Trace entries: {len(trace)}")
            for t in trace:
                dept_info = f" ({t.department_id})" if t.department_id else ""
                print(f"   • {t.node_name}{dept_info} — {t.agent}")

            # Check arbitration records
            arb_records = db.exec(
                select(RFPArbitrationRecord)
                .where(RFPArbitrationRecord.ticket_id == ticket_id)
            ).all()
            if arb_records:
                print(f"\n⚖️  Arbitration records: {len(arb_records)}")
                for ar in arb_records:
                    print(f"   • {ar.trigger_id} → {ar.resolution} (by {ar.resolved_by})")

            # Check events
            from rfp_models import RFPEventLog
            events = db.exec(
                select(RFPEventLog)
                .where(RFPEventLog.ticket_id == ticket_id)
                .order_by(RFPEventLog.created_at.asc())
            ).all()
            print(f"\n📝 Event log: {len(events)} events")
            for e in events:
                print(f"   • {e.event}")
    else:
        print(f"\n⚠️  --auto-approve not set. Part 3 entry complete, waiting for manual approval.")
        print(f"   To approve departments, use:")
        print(f"   python -c \"from data.pipelines.rfp_intake.graph_part3 import resume_ticket; print(resume_ticket('{ticket_id}', 'marketing', 'approve'))\"")

    print(f"\n{'='*60}")
    print(f"🎉 Pipeline complete for {ticket_id}")
    print(f"{'='*60}")

    return result_p3


def main() -> None:
    args = sys.argv[1:]

    # Default PDF
    pdf_path = "rfp-requests/brasaland/brasaland-request-2.pdf"
    auto_approve = "--auto-approve" in args
    setup_only = "--setup-only" in args

    for i, arg in enumerate(args):
        if arg == "--pdf" and i + 1 < len(args):
            pdf_path = args[i + 1]
        if arg == "--request-1":
            pdf_path = "rfp-requests/brasaland/brasaland-request-1.pdf"
        if arg == "--request-2":
            pdf_path = "rfp-requests/brasaland/brasaland-request-2.pdf"
        if arg == "--request-3":
            pdf_path = "rfp-requests/brasaland/brasaland-request-3.pdf"

    # Setup DB tables
    setup_db_tables()

    if setup_only:
        print("Database tables created. Exiting (--setup-only).")
        return

    # Run pipeline
    ticket_id = f"e2e-{uuid.uuid4().hex[:12]}"
    for i, arg in enumerate(args):
        if arg == "--ticket-id" and i + 1 < len(args):
            ticket_id = args[i + 1]

    run_pipeline(
        ticket_id=ticket_id,
        pdf_path=pdf_path,
        auto_approve=auto_approve,
    )


if __name__ == "__main__":
    main()