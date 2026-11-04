"""LangGraph pipeline for RFP Part 3 — Human Approval, Arbitration & Final Document.

This graph completes the RFP intake flow:

1. Entry: load from Part 2 handoff (or resume from checkpoint)
2. Per-department human approval interrupt (checkpointed, non-blocking between depts)
3. Arbitration: detect conflicts using fixed arbiters (not LLM voting)
4. CEO approval if annual value > $50K USD
5. Generate final consolidated document
6. Full traceability of every node execution

Key design decisions:
- Interrupts are modeled as checkpoint + early end; resume loads checkpoint and continues
- Each department's interrupt is independent — other departments are not blocked
- Arbitration uses deterministic rules + named humans, not LLM agents negotiating
- Thread IDs are namespaced: rfp-{ticket_id} (global) or rfp-{ticket_id}:{department}
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure API module is importable
API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

logger = logging.getLogger("rfp_intake.graph_part3")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPROVAL_STATUS_PENDIENTE = "pendiente"
APPROVAL_STATUS_APROBADO = "aprobado"
APPROVAL_STATUS_RECHAZADO = "rechazado"
APPROVAL_STATUS_REQUEST_CHANGES = "request_changes"

DEPARTMENT_APPROVERS: dict[str, str] = {
    "marketing": "Camila Ospina",
    "operaciones": "Felipe Guerrero",
    "procurement": "Lucía Fernández",
    "training": "Jake Morrison",
}

CEO_NAME = "Mariana Restrepo"

CEO_THRESHOLD_USD = 50000.0

# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------


class RFPApprovalState(dict):
    """Mutable state dict for the RFP approval graph (Parte 3).

    Extends the handoff from Part 2.
    """

    ticket_id: str
    handoff_payload: dict  # From Part 2 (JSON-parsed)
    status: str
    # Per-department state
    departments_needed: list[str]
    approval_statuses: dict[str, str]  # department_id → approval_status
    approvers: dict[str, str]          # department_id → human name
    # Section drafts + evaluations from Part 2
    sections: list[dict]
    # Arbitration
    arbitration_conflicts: list[dict]
    arbitration_resolved: list[dict]
    # CEO approval
    annual_estimated_usd: Optional[float]
    ceo_approval_required: bool
    ceo_approved: bool
    ceo_approved_at: Optional[str]
    # Final document
    final_document_content: str
    total_estimated_value_cop: Optional[float]
    total_estimated_value_usd: Optional[float]
    # Resume support
    is_resume: bool
    resume_action: Optional[str]      # "approve" | "reject" | "request_changes"
    resume_department: Optional[str]  # Which department triggered the resume
    # Errors
    errors: list[str]


def make_approval_state(ticket_id: str, handoff_payload: dict) -> dict:
    """Create initial state for Part 3 from Part 2 handoff."""
    departments = handoff_payload.get("departments_needed", [])
    sections = handoff_payload.get("sections", [])

    # Build approval statuses from sections
    approval_statuses: dict[str, str] = {}
    for section in sections:
        dept_id = section.get("department_id", "")
        if dept_id:
            approval_statuses[dept_id] = section.get("approval_status", APPROVAL_STATUS_PENDIENTE)

    # Ensure all needed departments are represented
    for dept_id in departments:
        if dept_id not in approval_statuses:
            approval_statuses[dept_id] = APPROVAL_STATUS_PENDIENTE

    # Build approvers map
    approvers: dict[str, str] = {}
    for dept_id in departments:
        approvers[dept_id] = DEPARTMENT_APPROVERS.get(dept_id, dept_id)

    annual_usd = handoff_payload.get("annual_estimated_usd")
    if annual_usd is None:
        # Try to find it in sections or metadata
        meta = handoff_payload.get("metadata", handoff_payload)
        annual_usd = meta.get("annual_estimated_usd")

    return {
        "ticket_id": ticket_id,
        "handoff_payload": handoff_payload,
        "status": "esperando_aprobacion",
        "departments_needed": departments,
        "approval_statuses": approval_statuses,
        "approvers": approvers,
        "sections": sections,
        "arbitration_conflicts": [],
        "arbitration_resolved": [],
        "annual_estimated_usd": float(annual_usd) if annual_usd is not None else None,
        "ceo_approval_required": float(annual_usd) > CEO_THRESHOLD_USD if annual_usd is not None else False,
        "ceo_approved": False,
        "ceo_approved_at": None,
        "final_document_content": "",
        "total_estimated_value_cop": None,
        "total_estimated_value_usd": None,
        "is_resume": False,
        "resume_action": None,
        "resume_department": None,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Helper: record trace
# ---------------------------------------------------------------------------


def _record_trace(state: dict, node_name: str, agent: str, input_data: Any = None, output_data: Any = None, department_id: Optional[str] = None) -> None:
    """Record node execution in trace log."""
    try:
        from data.pipelines.rfp_intake.traceability import record_execution
        record_execution(
            ticket_id=state["ticket_id"],
            node_name=node_name,
            agent=agent,
            input_data=input_data,
            output_data=output_data,
            department_id=department_id,
        )
    except Exception as exc:
        logger.warning("[%s] Trace record failed: %s", state["ticket_id"], exc)


# ---------------------------------------------------------------------------
# Node: Entry — load Part 2 handoff
# ---------------------------------------------------------------------------


def enter_part3_node(state: dict) -> dict:
    """Entry point: load Part 2 handoff and set up initial state.

    If this is a resume, the state already contains resume context and
    we load from the saved checkpoint instead.
    """
    ticket_id = state["ticket_id"]
    logger.info("[%s] Entering Part 3 (resume=%s)", ticket_id, state.get("is_resume", False))

    # Record entry trace
    _record_trace(state, "enter_part3", "graph:enter_part3",
                  input_data={"is_resume": state.get("is_resume", False)},
                  output_data={
                      "departments_needed": state.get("departments_needed", []),
                      "status": state.get("status"),
                  })

    return state


# ---------------------------------------------------------------------------
# Node: Save interrupt checkpoints for pending departments
# ---------------------------------------------------------------------------


def save_interrupts_node(state: dict) -> dict:
    """For each department needing approval, save a checkpoint and mark paused.

    Only departments with 'pendiente' status get checkpointed.
    Already-approved/rejected departments are skipped.

    This does NOT block — it saves state and lets the graph end naturally.
    The ticket status is set to 'esperando_aprobacion'.
    """
    from data.pipelines.rfp_intake.checkpointer import save_checkpoint

    ticket_id = state["ticket_id"]
    departments = state.get("departments_needed", [])
    approval_statuses = state.get("approval_statuses", {})

    pending_depts = [
        dept for dept in departments
        if approval_statuses.get(dept) == APPROVAL_STATUS_PENDIENTE
    ]

    if not pending_depts:
        # No pending approvals — move on
        logger.info("[%s] No pending approvals needed.", ticket_id)
        return state

    logger.info("[%s] Saving checkpoints for %d pending departments: %s",
                ticket_id, len(pending_depts), pending_depts)

    # Save per-department checkpoints
    for dept_id in pending_depts:
        ckpt_state = dict(state)  # shallow copy is fine for serialization
        ckpt_state["_checkpoint_reason"] = f"awaiting_approval:{dept_id}"
        save_checkpoint(
            ticket_id=ticket_id,
            node_name="save_interrupts",
            state_snapshot=ckpt_state,
            department_id=dept_id,
        )
        logger.info("[%s] Checkpoint saved for department %s", ticket_id, dept_id)

    # Also save a global checkpoint
    save_checkpoint(
        ticket_id=ticket_id,
        node_name="save_interrupts",
        state_snapshot=dict(state),
        department_id=None,
    )

    _record_trace(state, "save_interrupts", "graph:save_interrupts",
                  input_data={"pending_departments": pending_depts},
                  output_data={"pending_departments": pending_depts, "checkpointed": True})

    # Update ticket status in DB
    _update_ticket_status(ticket_id, "esperando_aprobacion",
                          f"Waiting for approval: {', '.join(pending_depts)}")

    return state


# ---------------------------------------------------------------------------
# Node: Resume from checkpoint when human responds
# ---------------------------------------------------------------------------


def resume_from_checkpoint_node(state: dict) -> dict:
    """Entry point for resume: validate and load checkpoint.

    This node is the START for resume invocations.
    It validates the human response and loads the saved state.
    """
    from data.pipelines.rfp_intake.checkpointer import load_checkpoint, mark_checkpoint_resumed

    ticket_id = state["ticket_id"]
    resume_department = state.get("resume_department")
    resume_action = state.get("resume_action")

    logger.info("[%s] Resume requested: department=%s action=%s",
                ticket_id, resume_department, resume_action)

    if not resume_department:
        state.setdefault("errors", []).append("resume_department is required for resume")
        return state

    if resume_action not in ("approve", "reject", "request_changes"):
        state.setdefault("errors", []).append(
            f"Invalid resume_action: {resume_action}. Must be approve/reject/request_changes"
        )
        return state

    # Load the per-department checkpoint
    saved_state = load_checkpoint(ticket_id, department_id=resume_department)

    if saved_state is None:
        # Try global checkpoint
        saved_state = load_checkpoint(ticket_id)
        if saved_state is None:
            state.setdefault("errors", []).append(
                f"No checkpoint found for ticket {ticket_id}"
            )
            return state
        logger.info("[%s] Using global checkpoint for resume", ticket_id)
    else:
        logger.info("[%s] Using department checkpoint for resume", ticket_id)

    # Merge saved state into current state
    # The saved state is our previous state; we overlay the resume action
    for key, value in saved_state.items():
        if key not in ("is_resume", "resume_action", "resume_department", "errors"):
            state[key] = value

    state["is_resume"] = True

    # Mark checkpoint as resumed
    mark_checkpoint_resumed(ticket_id, department_id=resume_department)

    _record_trace(state, "resume_from_checkpoint", "graph:resume",
                  input_data={"department": resume_department, "action": resume_action},
                  output_data={"status": "checkpoint_loaded"})

    return state


# ---------------------------------------------------------------------------
# Node: Process human decision
# ---------------------------------------------------------------------------


def process_human_decision_node(state: dict) -> dict:
    """Apply the human's decision for a department.

    Actions:
    - approve: mark department as approved
    - reject: mark department as rejected (triggers arbitration)
    - request_changes: mark department for re-generation, return to Part 2 loop
    """
    ticket_id = state["ticket_id"]
    action = state.get("resume_action", "")
    department = state.get("resume_department", "")

    if not department or not action:
        state.setdefault("errors", []).append("Missing resume_action or resume_department")
        return state

    approval_statuses = state.get("approval_statuses", {})
    sections = state.get("sections", [])

    if action == "approve":
        approval_statuses[department] = APPROVAL_STATUS_APROBADO
        # Update section
        for section in sections:
            if section.get("department_id") == department:
                section["approval_status"] = APPROVAL_STATUS_APROBADO
                section["approved_at"] = datetime.now(timezone.utc).isoformat()
                break
        logger.info("[%s] Department %s APPROVED by %s",
                    ticket_id, department, DEPARTMENT_APPROVERS.get(department, "Unknown"))

        # Persist to DB
        _persist_approval(ticket_id, department, APPROVAL_STATUS_APROBADO)

    elif action == "reject":
        approval_statuses[department] = APPROVAL_STATUS_RECHAZADO
        for section in sections:
            if section.get("department_id") == department:
                section["approval_status"] = APPROVAL_STATUS_RECHAZADO
                break
        logger.info("[%s] Department %s REJECTED", ticket_id, department)
        _persist_approval(ticket_id, department, APPROVAL_STATUS_RECHAZADO)

    elif action == "request_changes":
        approval_statuses[department] = APPROVAL_STATUS_REQUEST_CHANGES
        for section in sections:
            if section.get("department_id") == department:
                section["approval_status"] = APPROVAL_STATUS_REQUEST_CHANGES
                break
        logger.info("[%s] Department %s requested CHANGES", ticket_id, department)
        _persist_approval(ticket_id, department, APPROVAL_STATUS_REQUEST_CHANGES)

    state["approval_statuses"] = approval_statuses
    state["sections"] = sections

    _record_trace(state, "process_human_decision", f"human:{department}",
                  input_data={"department": department, "action": action},
                  output_data={"approval_statuses": approval_statuses})

    return state


def _persist_approval(ticket_id: str, department_id: str, approval_status: str) -> None:
    """Update department section approval in DB."""
    try:
        from datetime import datetime, timezone
        from sqlmodel import Session, select
        from database import _get_engine
        from rfp_models import DepartmentSection

        engine = _get_engine()
        with Session(engine) as db:
            section = db.exec(
                select(DepartmentSection).where(
                    DepartmentSection.ticket_id == ticket_id,
                    DepartmentSection.department_id == department_id,
                )
            ).first()

            if section:
                section.approval_status = approval_status
                section.approver = DEPARTMENT_APPROVERS.get(department_id)
                if approval_status == APPROVAL_STATUS_APROBADO:
                    section.approved_at = datetime.now(timezone.utc)
                section.updated_at = datetime.now(timezone.utc)
                db.add(section)
                db.commit()
                logger.info("[%s] Approval %s persisted for %s",
                           ticket_id, approval_status, department_id)
    except Exception as exc:
        logger.warning("[%s] Failed to persist approval: %s", ticket_id, exc)


# ---------------------------------------------------------------------------
# Router: after processing human decision
# ---------------------------------------------------------------------------


def route_after_human_decision(state: dict) -> str:
    """Route based on the human decision outcome.

    - If changes requested: return to "needs_human_review" (Part 2 retrigger)
    - If rejected: check arbitration
    - If approved: check if all departments done → arbitration → final document
    """
    action = state.get("resume_action", "")
    department = state.get("resume_department", "")

    if action == "request_changes":
        # This section needs to go back to the generator-evaluator loop
        # We signal this by setting the ticket status appropriately
        logger.info("[%s] %s requested changes — returning to evaluation loop",
                    state["ticket_id"], department)
        _update_ticket_status(state["ticket_id"], "needs_human_review",
                              f"{department} requested changes")
        return "needs_regeneration"

    if action == "reject":
        logger.info("[%s] %s rejected — checking arbitration",
                    state["ticket_id"], department)
        return "arbitration"

    # action == "approve"
    # Check if all departments are approved
    approval_statuses = state.get("approval_statuses", {})
    all_approved = all(
        v == APPROVAL_STATUS_APROBADO
        for v in approval_statuses.values()
    )

    if all_approved:
        logger.info("[%s] All departments approved. Proceeding to arbitration.",
                    state["ticket_id"])
        return "arbitration"
    else:
        # Still waiting for other departments
        pending = [
            d for d, v in approval_statuses.items()
            if v == APPROVAL_STATUS_PENDIENTE
        ]
        logger.info("[%s] Approved %s. Still waiting for: %s",
                    state["ticket_id"], department, pending)
        # Check if there are checkpoints for pending departments
        from data.pipelines.rfp_intake.checkpointer import load_checkpoint
        for dept in pending:
            ckpt = load_checkpoint(state["ticket_id"], department_id=dept)
            if ckpt is None:
                # Need to save checkpoint for this department
                from data.pipelines.rfp_intake.checkpointer import save_checkpoint
                save_checkpoint(
                    ticket_id=state["ticket_id"],
                    node_name="save_interrupts",
                    state_snapshot=dict(state),
                    department_id=dept,
                )

        return "wait_for_others"


# ---------------------------------------------------------------------------
# Node: Arbitration
# ---------------------------------------------------------------------------


def arbitration_node(state: dict) -> dict:
    """Detect and resolve conflicts using fixed arbiters.

    This node:
    1. Scans state for conflict triggers
    2. Auto-resolves where possible (setup-sla-breach)
    3. Records pending human arbitrations
    4. If CEO threshold is exceeded and CEO hasn't approved, sets up CEO interrupt
    """
    from data.pipelines.rfp_intake.arbitration import detect_conflicts, resolve_conflict_auto, record_arbitration

    ticket_id = state["ticket_id"]

    # Rebuild the sections dict for the arbitration scanner
    sections = state.get("sections", [])
    evaluations: dict[str, dict] = {}
    drafts: dict[str, str] = {}
    for section in sections:
        dept_id = section.get("department_id", "")
        if dept_id:
            eval_result = section.get("evaluation_result", {})
            if eval_result:
                evaluations[dept_id] = eval_result
            draft = section.get("draft_content", "")
            if draft:
                drafts[dept_id] = draft

    # Build a state snapshot for conflict detection
    arb_state = {
        "handoff_payload": state.get("handoff_payload", {}),
        "sections": sections,
        "evaluations": evaluations,
        "evaluation_results": evaluations,
        "drafts": drafts,
        "annual_estimated_usd": state.get("annual_estimated_usd"),
        "ceo_approved": state.get("ceo_approved", False),
    }

    conflicts = detect_conflicts(arb_state)
    state["arbitration_conflicts"] = conflicts

    if not conflicts:
        logger.info("[%s] No conflicts detected.", ticket_id)
        _record_trace(state, "arbitration", "graph:arbitration",
                      input_data={},
                      output_data={"conflicts": []})
        return state

    logger.info("[%s] Detected %d conflict(s): %s",
                ticket_id, len(conflicts),
                [c["trigger_id"] for c in conflicts])

    resolved: list[dict] = []

    for conflict in conflicts:
        trigger_id = conflict["trigger_id"]
        arbiter = conflict["arbiter"]

        # Try auto-resolve
        if conflict.get("auto_resolve", False):
            resolution = resolve_conflict_auto(trigger_id, conflict, arb_state)
            resolved.append({
                "trigger_id": trigger_id,
                "arbiter": arbiter,
                "resolution": resolution["resolution"],
                "note": resolution["note"],
                "auto_resolved": True,
            })
            # Apply state updates
            for key, value in resolution.get("state_updates", {}).items():
                if key == "arbitration_requested_changes":
                    for dept in value:
                        approval_statuses = state.get("approval_statuses", {})
                        approval_statuses[dept] = APPROVAL_STATUS_REQUEST_CHANGES
                        state["approval_statuses"] = approval_statuses
                else:
                    state[key] = value

            record_arbitration(
                ticket_id=ticket_id,
                trigger_id=trigger_id,
                arbiter=arbiter,
                description=conflict.get("description", ""),
                resolution=resolution["resolution"],
                departments_involved=conflict.get("departments_involved"),
                resolved_by=arbiter,
            )
            logger.info("[%s] Auto-resolved conflict %s: %s",
                       ticket_id, trigger_id, resolution["resolution"])
        else:
            # Needs human arbitration
            resolved.append({
                "trigger_id": trigger_id,
                "arbiter": arbiter,
                "resolution": "pending",
                "note": conflict.get("description", ""),
                "auto_resolved": False,
            })
            logger.info("[%s] Conflict %s pending human arbitration by %s",
                       ticket_id, trigger_id, arbiter)

    state["arbitration_resolved"] = resolved

    _record_trace(state, "arbitration", "graph:arbitration",
                  input_data={"conflicts_detected": [c["trigger_id"] for c in conflicts]},
                  output_data={"conflicts": conflicts, "resolved": resolved})

    return state


# ---------------------------------------------------------------------------
# Router: after arbitration
# ---------------------------------------------------------------------------


def route_after_arbitration(state: dict) -> str:
    """Route based on arbitration outcomes.

    - If any conflict triggered request_changes → go back to generation loop
    - If CEO threshold and CEO not approved → CEO interrupt
    - If all resolved → generate final document
    """
    resolved = state.get("arbitration_resolved", [])
    conflicts = state.get("arbitration_conflicts", [])

    # Check if any conflict remains pending (human arbitration needed)
    pending = [r for r in resolved if r.get("resolution") == "pending"]
    if pending:
        logger.info("[%s] Arbitration pending for triggers: %s",
                    state["ticket_id"], [p["trigger_id"] for p in pending])
        # Save checkpoint for each pending arbitration
        from data.pipelines.rfp_intake.checkpointer import save_checkpoint
        for p in pending:
            ckpt_state = dict(state)
            ckpt_state["_checkpoint_reason"] = f"awaiting_arbitration:{p['trigger_id']}"
            save_checkpoint(
                ticket_id=state["ticket_id"],
                node_name="arbitration",
                state_snapshot=ckpt_state,
            )
        return "wait_for_arbitration"

    # Check if any conflict triggered changes
    for r in resolved:
        if r.get("resolution") == "request_changes":
            logger.info("[%s] Arbitration forced request_changes. Returning to evaluation.",
                        state["ticket_id"])
            _update_ticket_status(state["ticket_id"], "needs_human_review",
                                  "Arbitration forced changes")
            return "needs_regeneration"

    # Check CEO threshold
    if state.get("ceo_approval_required") and not state.get("ceo_approved"):
        logger.info("[%s] CEO approval required but pending.", state["ticket_id"])
        # Save CEO checkpoint
        from data.pipelines.rfp_intake.checkpointer import save_checkpoint
        save_checkpoint(
            ticket_id=state["ticket_id"],
            node_name="arbitration",
            state_snapshot=dict(state),
        )
        _update_ticket_status(state["ticket_id"], "esperando_aprobacion",
                              "Awaiting CEO approval (Mariana Restrepo)")
        return "ceo_approval"

    # All clear — generate final document
    logger.info("[%s] All conflicts resolved. Generating final document.", state["ticket_id"])
    return "generate_final_document"


# ---------------------------------------------------------------------------
# Node: Generate Final Document
# ---------------------------------------------------------------------------


def generate_final_document_node(state: dict) -> dict:
    """Consolidate all approved sections into the final proposal document.

    The document includes:
    - Header with client info
    - Each department's approved section
    - Total estimated value (sum of all sections)
    - Validity period
    - Sign-off area
    """
    ticket_id = state["ticket_id"]
    sections = state.get("sections", [])
    handoff = state.get("handoff_payload", {})
    meta = handoff.get("metadata", handoff)

    client_name = meta.get("client_name", "Cliente")
    location = meta.get("location", "")
    service_type = meta.get("service_type", "")
    scope = meta.get("scope", "")

    # Only include approved sections
    approved_sections = [
        s for s in sections
        if s.get("approval_status") == APPROVAL_STATUS_APROBADO
    ]

    lines: list[str] = []
    lines.append("# Propuesta Económica — Brasaland")
    lines.append("")
    lines.append(f"**Preparada para:** {client_name}")
    if location:
        lines.append(f"**Ubicación:** {location}")
    if service_type:
        lines.append(f"**Tipo de servicio:** {service_type}")
    if scope:
        lines.append(f"**Alcance:** {scope}")
    lines.append(f"**Ticket:** {ticket_id}")
    lines.append(f"**Fecha de emisión:** {datetime.now(timezone.utc).strftime('%d de %B de %Y')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, section in enumerate(approved_sections, 1):
        dept_id = section.get("department_id", "")
        draft = section.get("draft_content", "")
        label = {
            "marketing": "Marketing y Experiencia Digital",
            "operaciones": "Operaciones de Restaurante",
            "procurement": "Procurement y Proveedores",
            "training": "Training y Estándares de Calidad",
        }.get(dept_id, dept_id)
        approver = DEPARTMENT_APPROVERS.get(dept_id, "")

        lines.append(f"## {idx}. {label}")
        lines.append("")
        if draft:
            lines.append(draft)
        else:
            lines.append("*Sección no disponible*")
        lines.append("")
        lines.append(f"**Aprobado por:** {approver}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Total estimated value
    total_cop = state.get("total_estimated_value_cop")
    total_usd = state.get("total_estimated_value_usd")

    # Calculate from approved sections
    total_cop_calc = 0.0
    total_usd_calc = 0.0
    for section in approved_sections:
        eval_result = section.get("evaluation_result", {})
        if isinstance(eval_result, str):
            try:
                eval_result = json.loads(eval_result)
            except (json.JSONDecodeError, TypeError):
                eval_result = {}

    lines.append("## Resumen Económico")
    lines.append("")
    if total_cop or total_cop_calc:
        lines.append(f"**Valor total estimado:** COP ${float(total_cop or total_cop_calc):,.0f}")
    if total_usd or total_usd_calc:
        lines.append(f"**Valor total estimado:** USD ${float(total_usd or total_usd_calc):,.0f}")
    lines.append("")
    lines.append("**Pilares de Brasaland:** Calidad consistente, experiencia cálida, velocidad de servicio.")
    lines.append("**Validez de la oferta:** 30 días desde su emisión.")
    lines.append("")

    # CEO approval note if needed
    if state.get("ceo_approval_required") and state.get("ceo_approved"):
        lines.append(f"**Aprobación CEO:** Mariana Restrepo — {state.get('ceo_approved_at', 'Aprobada')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Documento generado automáticamente por el sistema de flujos agénticos de Brasaland.*")

    content = "\n".join(lines)

    state["final_document_content"] = content

    _record_trace(state, "generate_final_document", "graph:final_document",
                  input_data={"approved_sections": len(approved_sections)},
                  output_data={"content_length": len(content)})

    return state


# ---------------------------------------------------------------------------
# Node: Finalize — persist final document and update ticket
# ---------------------------------------------------------------------------


def finalize_node(state: dict) -> dict:
    """Persist the final document and update ticket status to 'terminado'."""
    ticket_id = state["ticket_id"]
    content = state.get("final_document_content", "")

    if not content:
        state.setdefault("errors", []).append("No final document content to persist")
        return state

    # Persist to DB
    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPFinalDocument, RFPEventLog, RFPTicket

        engine = _get_engine()
        with Session(engine) as db:
            # Update ticket
            ticket = db.get(RFPTicket, ticket_id)
            if ticket:
                ticket.status = "terminado"
                ticket.updated_at = datetime.now(timezone.utc)
                db.add(ticket)

            # Save final document
            doc = RFPFinalDocument(
                ticket_id=ticket_id,
                content=content,
                total_estimated_value_cop=state.get("total_estimated_value_cop"),
                total_estimated_value_usd=state.get("total_estimated_value_usd"),
                ceo_approval_required=state.get("ceo_approval_required", False),
                ceo_approved=state.get("ceo_approved", False),
                ceo_approved_at=(
                    datetime.fromisoformat(state["ceo_approved_at"])
                    if state.get("ceo_approved_at") else None
                ),
            )
            db.add(doc)

            # Log event
            event = RFPEventLog(
                ticket_id=ticket_id,
                event="part3_complete",
                detail=f"Documento final generado. Departamentos: {len(state.get('sections', []))}",
            )
            db.add(event)

            db.commit()

        # Clear checkpoints for this ticket
        from data.pipelines.rfp_intake.checkpointer import clear_checkpoints
        clear_checkpoints(ticket_id)

        logger.info("[%s] Final document persisted. Status → terminado", ticket_id)

    except Exception as exc:
        logger.error("[%s] Failed to persist final document: %s", ticket_id, exc)
        state.setdefault("errors", []).append(f"Persist failed: {exc}")

    state["status"] = "terminado"

    _record_trace(state, "finalize", "graph:finalize",
                  input_data={},
                  output_data={"status": "terminado", "content_length": len(content)})

    return state


# ---------------------------------------------------------------------------
# Node: CEO approval interrupt
# ---------------------------------------------------------------------------


def ceo_approval_interrupt_node(state: dict) -> dict:
    """Interrupt for CEO approval when value > $50K USD.

    Saves a checkpoint and waits for CEO human response.
    """
    from data.pipelines.rfp_intake.checkpointer import save_checkpoint

    ticket_id = state["ticket_id"]

    logger.info("[%s] CEO approval required. Saving checkpoint and waiting.",
                ticket_id)

    save_checkpoint(
        ticket_id=ticket_id,
        node_name="ceo_approval_interrupt",
        state_snapshot=dict(state),
    )

    _update_ticket_status(ticket_id, "esperando_aprobacion",
                          "Awaiting CEO approval (Mariana Restrepo)")

    _record_trace(state, "ceo_approval_interrupt", "graph:ceo_interrupt",
                  input_data={"annual_usd": state.get("annual_estimated_usd")},
                  output_data={"status": "esperando_aprobacion"})

    return state


# ---------------------------------------------------------------------------
# Helper: Update ticket status in DB
# ---------------------------------------------------------------------------


def _update_ticket_status(ticket_id: str, status: str, detail: Optional[str] = None) -> None:
    """Update ticket status and log event."""
    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPEventLog, RFPTicket

        engine = _get_engine()
        with Session(engine) as db:
            ticket = db.get(RFPTicket, ticket_id)
            if ticket:
                ticket.status = status
                ticket.updated_at = datetime.now(timezone.utc)
                db.add(ticket)

            event = RFPEventLog(
                ticket_id=ticket_id,
                event=f"part3_{status}",
                detail=detail or f"Status changed to {status}",
            )
            db.add(event)
            db.commit()

        logger.info("[%s] Ticket status updated: %s", ticket_id, status)
    except Exception as exc:
        logger.warning("[%s] Failed to update ticket status: %s", ticket_id, exc)


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------


def build_approval_graph():
    """Build and return the LangGraph StateGraph for Part 3 (approval & final doc)."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        raise ImportError("langgraph is required. Install with: pip install langgraph")

    builder = StateGraph(RFPApprovalState)

    # Nodes
    builder.add_node("enter_part3", enter_part3_node)
    builder.add_node("save_interrupts", save_interrupts_node)
    builder.add_node("resume_from_checkpoint", resume_from_checkpoint_node)
    builder.add_node("process_human_decision", process_human_decision_node)
    builder.add_node("arbitration", arbitration_node)
    builder.add_node("ceo_approval_interrupt", ceo_approval_interrupt_node)
    builder.add_node("generate_final_document", generate_final_document_node)
    builder.add_node("finalize", finalize_node)

    # --- Initial entry edges ---
    builder.add_edge(START, "enter_part3")

    # Route: first run vs resume
    builder.add_conditional_edges(
        "enter_part3",
        _route_after_entry,
        {
            "save_interrupts": "save_interrupts",
            "resume_from_checkpoint": "resume_from_checkpoint",
        },
    )

    # After saving interrupts, end (wait for humans)
    builder.add_edge("save_interrupts", END)

    # Resume flow
    builder.add_edge("resume_from_checkpoint", "process_human_decision")

    # After processing human decision
    builder.add_conditional_edges(
        "process_human_decision",
        route_after_human_decision,
        {
            "arbitration": "arbitration",
            "wait_for_others": END,
            "needs_regeneration": END,
        },
    )

    # After arbitration
    builder.add_conditional_edges(
        "arbitration",
        route_after_arbitration,
        {
            "generate_final_document": "generate_final_document",
            "wait_for_arbitration": END,
            "needs_regeneration": END,
            "ceo_approval": "ceo_approval_interrupt",
        },
    )

    # CEO interrupt → end (wait)
    builder.add_edge("ceo_approval_interrupt", END)

    # Final document flow
    builder.add_edge("generate_final_document", "finalize")
    builder.add_edge("finalize", END)

    graph = builder.compile()
    return graph


def _route_after_entry(state: dict) -> str:
    """Route to resume if is_resume flag is set, otherwise to save_interrupts."""
    if state.get("is_resume"):
        return "resume_from_checkpoint"
    return "save_interrupts"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def run_approval_pipeline(
    ticket_id: str,
    handoff_payload: dict,
    is_resume: bool = False,
    resume_department: Optional[str] = None,
    resume_action: Optional[str] = None,
) -> dict:
    """Run the Part 3 approval pipeline.

    Args:
        ticket_id: The ticket ID.
        handoff_payload: The Part 2 handoff dict (ignored if is_resume=True).
        is_resume: Whether this is a resume from a checkpoint.
        resume_department: The department responding (for resume).
        resume_action: The human decision (approve/reject/request_changes).

    Returns:
        Final state dict with results.
    """
    graph = build_approval_graph()

    if is_resume:
        # For resume, load checkpoint first to get saved state
        from data.pipelines.rfp_intake.checkpointer import load_checkpoint
        saved_state = load_checkpoint(ticket_id, department_id=resume_department)
        if saved_state is None:
            saved_state = load_checkpoint(ticket_id)

        if saved_state:
            initial = dict(saved_state)
        else:
            initial = make_approval_state(ticket_id, handoff_payload)

        initial["is_resume"] = True
        initial["resume_department"] = resume_department
        initial["resume_action"] = resume_action
    else:
        initial = make_approval_state(ticket_id, handoff_payload)

    logger.info("[%s] Running Part 3 pipeline (resume=%s dept=%s action=%s)",
                ticket_id, is_resume, resume_department, resume_action)

    result = graph.invoke(initial)

    return result


# ---------------------------------------------------------------------------
# Trigger Part 3 from Part 2
# ---------------------------------------------------------------------------


def trigger_part3(ticket_id: str) -> dict:
    """Load a completed Part 2 ticket and trigger Part 3 pipeline.

    This is the bridge between Part 2 and Part 3.
    """
    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPTicket

        engine = _get_engine()
        with Session(engine) as db:
            ticket = db.get(RFPTicket, ticket_id)
            if not ticket:
                raise ValueError(f"Ticket not found: {ticket_id}")

            # Allow both needs_human_review and earlier states that have handoff
            if ticket.status == "analisis_completo":
                raise ValueError(
                    f"Ticket {ticket_id} has status '{ticket.status}'. "
                    f"Run Part 2 first (POST /generate)."
                )

            if not ticket.handoff_payload:
                raise ValueError(f"Ticket {ticket_id} has no handoff_payload.")

            handoff = json.loads(ticket.handoff_payload)

        # Run Part 3 pipeline
        result = run_approval_pipeline(ticket_id, handoff)
        return result

    except Exception as exc:
        logger.exception("Failed to trigger Part 3 for ticket %s: %s", ticket_id, exc)
        raise


# ---------------------------------------------------------------------------
# Resume a checkpointed ticket
# ---------------------------------------------------------------------------


def resume_ticket(
    ticket_id: str,
    department_id: str,
    action: str,
) -> dict:
    """Resume a ticket from a checkpoint with a human decision.

    Args:
        ticket_id: The ticket UUID.
        department_id: The department responding.
        action: One of "approve", "reject", "request_changes".

    Returns:
        Final state dict.
    """
    # Validate
    if action not in ("approve", "reject", "request_changes"):
        raise ValueError(f"Invalid action: {action}. Must be approve/reject/request_changes")

    if department_id not in DEPARTMENT_APPROVERS:
        raise ValueError(f"Invalid department: {department_id}. Must be one of {list(DEPARTMENT_APPROVERS.keys())}")

    # Load the handoff payload for context
    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPTicket

        engine = _get_engine()
        with Session(engine) as db:
            ticket = db.get(RFPTicket, ticket_id)
            if not ticket:
                raise ValueError(f"Ticket not found: {ticket_id}")

            handoff_payload = {}
            if ticket.handoff_payload:
                try:
                    handoff_payload = json.loads(ticket.handoff_payload)
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception as exc:
        logger.exception("Failed to load ticket %s for resume: %s", ticket_id, exc)
        raise

    return run_approval_pipeline(
        ticket_id=ticket_id,
        handoff_payload=handoff_payload,
        is_resume=True,
        resume_department=department_id,
        resume_action=action,
    )


# ---------------------------------------------------------------------------
# CEO approval
# ---------------------------------------------------------------------------


def ceo_approve_ticket(ticket_id: str, approved: bool) -> dict:
    """Record CEO approval or rejection for a ticket.

    Args:
        ticket_id: The ticket UUID.
        approved: True to approve, False to reject.

    Returns:
        Final state dict (continues pipeline if approved).
    """
    try:
        from data.pipelines.rfp_intake.checkpointer import load_checkpoint, mark_checkpoint_resumed
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPTicket, RFPFinalDocument, RFPEventLog

        engine = _get_engine()
        with Session(engine) as db:
            ticket = db.get(RFPTicket, ticket_id)
            if not ticket:
                raise ValueError(f"Ticket not found: {ticket_id}")

            if approved:
                # CEO approved: continue pipeline
                logger.info("[%s] CEO approved by Mariana Restrepo", ticket_id)

                # Update state
                saved_state = load_checkpoint(ticket_id)
                if saved_state:
                    state = dict(saved_state)
                    state["ceo_approved"] = True
                    state["ceo_approved_at"] = datetime.now(timezone.utc).isoformat()
                    state["is_resume"] = True
                    state["resume_action"] = "approve"

                    mark_checkpoint_resumed(ticket_id)

                    # Set CEO approval on the final document
                    from sqlmodel import select
                    from rfp_models import RFPFinalDocument
                    doc = db.exec(
                        select(RFPFinalDocument.id)
                        .where(RFPFinalDocument.ticket_id == ticket_id)
                        .order_by(RFPFinalDocument.id.desc())
                        .limit(1)
                    ).first()

                    # Continue to final generation
                    # Run the graph from arbitration / final document
                    from data.pipelines.rfp_intake.graph_part3 import run_approval_pipeline

                    handoff = {}
                    if ticket.handoff_payload:
                        try:
                            handoff = json.loads(ticket.handoff_payload)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # We can reuse the approval pipeline with CEO approved
                    result = run_approval_pipeline(
                        ticket_id=ticket_id,
                        handoff_payload=handoff,
                        is_resume=True,
                        resume_department="ceo",
                        resume_action="approve",
                    )

                    # Update event log
                    event = RFPEventLog(
                        ticket_id=ticket_id,
                        event="ceo_approved",
                        detail="CEO (Mariana Restrepo) approved the proposal",
                    )
                    db.add(event)
                    db.commit()

                    return result
                else:
                    raise ValueError(f"No checkpoint found for ticket {ticket_id}")
            else:
                # CEO rejected
                logger.info("[%s] CEO REJECTED by Mariana Restrepo", ticket_id)
                ticket.status = "descartado"
                ticket.updated_at = datetime.now(timezone.utc)
                db.add(ticket)

                event = RFPEventLog(
                    ticket_id=ticket_id,
                    event="ceo_rejected",
                    detail="CEO (Mariana Restrepo) rejected the proposal",
                )
                db.add(event)
                db.commit()

                return {"ticket_id": ticket_id, "status": "descartado", "message": "CEO rejected the proposal"}

    except Exception as exc:
        logger.exception("CEO approval failed for ticket %s: %s", ticket_id, exc)
        raise