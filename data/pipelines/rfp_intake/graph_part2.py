"""LangGraph pipeline for RFP response generation (Parte 2).

Consumes the handoff from Part 1 (ticket_id + handoff_payload) and runs:
1. Generators per department (from key_aspects, NOT raw PDF)
2. Evaluators in parallel (readability, relevance, compliance)
3. Generator-evaluator loop with iteration limit
4. Handoff to Part 3 with draft_content + evaluation_results

States:
  analisis_completo → [generators] → generando_borrador
                    → [evaluators]  → en_evaluación
                    → [loop]       → needs_human_review (if limit exceeded)
                    → [done]       → (new state for Part 3)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the API module is importable
API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

logger = logging.getLogger("rfp_intake.graph_part2")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 3  # Max generator-evaluator iterations per section

# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------


class RFPResponseState(dict):
    """Mutable state dict for the RFP response generation graph (Parte 2).

    Extends the handoff from Part 1.
    """

    ticket_id: str
    handoff_payload: dict  # From Part 1 (JSON-parsed)
    status: str
    # Per-department generation state
    drafts: dict[str, str]  # department_id → draft_content
    evaluations: dict[str, dict]  # department_id → EvaluationResult
    iteration_counts: dict[str, int]  # department_id → iteration count
    sections_needing_review: list[str]  # departments that hit iteration limit
    # Final handoff to Part 3
    handoff_to_part3: str  # JSON string
    errors: list[str]


def make_initial_state(ticket_id: str, handoff_payload: dict) -> dict:
    """Create initial state from Part 1 handoff."""
    departments = handoff_payload.get("departments_needed", [])
    return {
        "ticket_id": ticket_id,
        "handoff_payload": handoff_payload,
        "status": "analisis_completo",
        "drafts": {},
        "evaluations": {},
        "iteration_counts": {dept: 0 for dept in departments},
        "sections_needing_review": [],
        "handoff_to_part3": "",
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Node: Generate all drafts (first pass)
# ---------------------------------------------------------------------------


def generate_drafts_node(state: dict) -> dict:
    """Run all department generators to produce first drafts."""
    from data.pipelines.rfp_intake.generators import run_generator

    handoff = state["handoff_payload"]
    departments = handoff.get("departments_needed", [])
    drafts: dict[str, str] = {}
    errors: list[str] = []

    logger.info("[%s] Generating drafts for %d departments", state["ticket_id"], len(departments))

    for dept_id in departments:
        try:
            result = run_generator(dept_id, handoff, previous_feedback=None)
            content = result.get("draft_content", "")
            if not content:
                content = f"*Borrador no disponible para {dept_id}*"
                errors.append(f"Generator {dept_id} returned empty draft")
            drafts[dept_id] = content
            logger.info("[%s] Draft generated for %s (%d chars)", state["ticket_id"], dept_id, len(content))
        except Exception as exc:
            logger.error("[%s] Generator %s failed: %s", state["ticket_id"], dept_id, exc)
            drafts[dept_id] = f"*Error generando borrador: {exc}*"
            errors.append(f"Generator {dept_id} failed: {exc}")

    state["drafts"] = drafts
    state["status"] = "generando_borrador"
    state["errors"] = errors
    return state


# ---------------------------------------------------------------------------
# Node: Evaluate all drafts (parallel evaluators per department)
# ---------------------------------------------------------------------------


def evaluate_drafts_node(state: dict) -> dict:
    """Run all evaluators in parallel over each generated draft."""
    from data.pipelines.rfp_intake.evaluators import evaluate_section

    handoff = state["handoff_payload"]
    departments = handoff.get("departments_needed", [])
    evaluations: dict[str, dict] = {}

    logger.info("[%s] Evaluating %d drafts", state["ticket_id"], len(departments))

    for dept_id in departments:
        draft_content = state.get("drafts", {}).get(dept_id, "")
        if not draft_content:
            logger.warning("[%s] No draft for %s, skipping evaluation", state["ticket_id"], dept_id)
            evaluations[dept_id] = {
                "department_id": dept_id,
                "overall_pass": False,
                "feedback_for_generator": "No hay borrador para evaluar.",
            }
            continue

        try:
            result = evaluate_section(draft_content, handoff, dept_id)
            evaluations[dept_id] = result
            logger.info(
                "[%s] Evaluation for %s: pass=%s",
                state["ticket_id"], dept_id, result.get("overall_pass"),
            )
        except Exception as exc:
            logger.error("[%s] Evaluation for %s failed: %s", state["ticket_id"], dept_id, exc)
            evaluations[dept_id] = {
                "department_id": dept_id,
                "overall_pass": False,
                "feedback_for_generator": f"Error en evaluación: {exc}",
                "readability": {"pass": False, "score": 0, "details": "Error"},
                "relevance": {"pass": False, "missing_aspects": [], "details": "Error"},
                "compliance": {"pass": False, "rule_ids": [], "violations": [], "details": "Error"},
            }

    state["evaluations"] = evaluations
    state["status"] = "en_evaluacion"
    return state


# ---------------------------------------------------------------------------
# Node: Regenerate drafts that failed evaluation
# ---------------------------------------------------------------------------


def regenerate_drafts_node(state: dict) -> dict:
    """Regenerate drafts for departments that failed evaluation (with feedback)."""
    from data.pipelines.rfp_intake.generators import run_generator

    handoff = state["handoff_payload"]
    departments = handoff.get("departments_needed", [])
    evaluations = state.get("evaluations", {})
    drafts = state.get("drafts", {})
    iterations = state.get("iteration_counts", {})

    for dept_id in departments:
        eval_result = evaluations.get(dept_id, {})
        if not eval_result.get("overall_pass", True):
            iterations[dept_id] = iterations.get(dept_id, 0) + 1
            current_iter = iterations[dept_id]

            if current_iter < MAX_ITERATIONS:
                feedback = eval_result.get("feedback_for_generator", "Mejora el borrador.")
                logger.info(
                    "[%s] Regenerating %s (iteration %d/%d)",
                    state["ticket_id"], dept_id, current_iter, MAX_ITERATIONS,
                )
                try:
                    result = run_generator(dept_id, handoff, previous_feedback=feedback)
                    new_draft = result.get("draft_content", "")
                    if new_draft:
                        drafts[dept_id] = new_draft
                except Exception as exc:
                    logger.error("[%s] Regeneration for %s failed: %s", state["ticket_id"], dept_id, exc)
            else:
                logger.info(
                    "[%s] %s hit iteration limit. Marking for human review.",
                    state["ticket_id"], dept_id,
                )
                state["sections_needing_review"] = list(set(state["sections_needing_review"] + [dept_id]))

    state["drafts"] = drafts
    state["iteration_counts"] = iterations
    return state


# ---------------------------------------------------------------------------
# Router: Decide if we need another iteration or we're done
# ---------------------------------------------------------------------------


def route_after_evaluation(state: dict) -> str:
    """Route to regeneration or to finalize."""
    if state["status"] == "needs_human_review":
        return "finalize"

    evaluations = state.get("evaluations", {})
    all_pass = all(
        eval_result.get("overall_pass", False)
        for eval_result in evaluations.values()
        if eval_result  # skip empty
    )

    if all_pass:
        logger.info("[%s] All sections passed. Finalizing.", state["ticket_id"])
        return "finalize"

    # Check if any failed departments can still iterate
    iterations = state.get("iteration_counts", {})

    # Only consider departments that have evaluation results (have been run)
    # and failed evaluation
    failed_departments = [
        dept for dept, eval_result in evaluations.items()
        if eval_result and not eval_result.get("overall_pass", False)
    ]

    any_can_retry = any(
        iterations.get(dept, 0) < MAX_ITERATIONS
        for dept in failed_departments
    )

    if any_can_retry:
        logger.info("[%s] Some sections failed. Regenerating...", state["ticket_id"])
        return "regenerate"

    # All departments exhausted iterations
    logger.info("[%s] Iteration limit reached for all. needs_human_review.", state["ticket_id"])
    state["status"] = "needs_human_review"
    return "finalize"


# ---------------------------------------------------------------------------
# Node: Build handoff to Part 3
# ---------------------------------------------------------------------------


def finalize_node(state: dict) -> dict:
    """Build the handoff payload for Part 3 (draft + evaluations per department)."""
    handoff = state["handoff_payload"]
    evaluations = state.get("evaluations", {})
    drafts = state.get("drafts", {})
    # Only iterate over departments that have evaluation results
    departments = [d for d in handoff.get("departments_needed", []) if d in evaluations and evaluations[d]]
    if not departments:
        departments = list(evaluations.keys())
    meta = handoff.get("metadata", handoff)

    # Build section list for Part 3
    sections = []
    for dept_id in departments:
        eval_result = evaluations.get(dept_id, {})
        draft_content = drafts.get(dept_id, "")
        needs_review = dept_id in state.get("sections_needing_review", [])

        section = {
            "department_id": dept_id,
            "draft_content": draft_content,
            "evaluation_result": eval_result,
            "needs_human_review": needs_review,
            "approval_status": "pendiente",
        }
        sections.append(section)

    # Count metrics
    total_sections = len(sections)
    passed = sum(1 for s in sections if s["evaluation_result"].get("overall_pass", False))
    failed = total_sections - passed
    needs_review_count = len(state.get("sections_needing_review", []))
    avg_iterations = (
        sum(state.get("iteration_counts", {}).values()) / total_sections
        if total_sections > 0 else 0
    )

    part3_payload = {
        "ticket_id": state["ticket_id"],
        "status": state["status"],
        # Original Part 1 context
        "client_name": meta.get("client_name"),
        "service_type": meta.get("service_type"),
        "annual_estimated_usd": meta.get("annual_estimated_usd"),
        "departments_needed": departments,
        "department_contacts": {
            "marketing": "Camila Ospina",
            "operaciones": "Felipe Guerrero",
            "procurement": "Lucía Fernández",
            "training": "Jake Morrison",
        },
        # Part 2 results
        "sections": sections,
        "total_sections": total_sections,
        "sections_passed": passed,
        "sections_failed": failed,
        "sections_needing_human_review": needs_review_count,
        "average_iterations": round(avg_iterations, 1),
        "sections_needing_review": state.get("sections_needing_review", []),
        # Generation info
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    state["handoff_to_part3"] = json.dumps(part3_payload, indent=2, ensure_ascii=False)

    logger.info(
        "[%s] Part 2 complete. Sections: %d/%d passed, %d needs review",
        state["ticket_id"], passed, total_sections, needs_review_count,
    )

    return state


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------


def build_rfp_response_graph():
    """Build and return the LangGraph StateGraph for RFP response generation (Parte 2)."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        raise ImportError("langgraph is required. Install with: pip install langgraph")

    builder = StateGraph(RFPResponseState)

    builder.add_node("generate_drafts", generate_drafts_node)
    builder.add_node("evaluate_drafts", evaluate_drafts_node)
    builder.add_node("regenerate_drafts", regenerate_drafts_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "generate_drafts")
    builder.add_edge("generate_drafts", "evaluate_drafts")
    builder.add_conditional_edges(
        "evaluate_drafts",
        route_after_evaluation,
        {
            "regenerate": "regenerate_drafts",
            "finalize": "finalize",
        },
    )
    builder.add_edge("regenerate_drafts", "evaluate_drafts")
    builder.add_edge("finalize", END)

    graph = builder.compile()
    return graph


# ---------------------------------------------------------------------------
# Standalone runner — entry point from Celery task
# ---------------------------------------------------------------------------


def run_response_pipeline(ticket_id: str, handoff_payload: dict) -> dict:
    """Run the full Part 2 response generation pipeline.

    Args:
        ticket_id: The ticket ID from Part 1.
        handoff_payload: The handoff dict from Part 1.

    Returns:
        Final state dict with results persisted to DB.
    """
    graph = build_rfp_response_graph()
    initial = make_initial_state(ticket_id, handoff_payload)
    result = graph.invoke(initial)

    # Persist to DB (non-blocking)
    try:
        _persist_part2_results(result)
    except Exception as exc:
        logger.warning("[%s] Failed to persist Part 2 results: %s", ticket_id, exc)

    return result


def _persist_part2_results(state: dict) -> None:
    """Persist Part 2 results to PostgreSQL via SQLModel."""
    try:
        from sqlmodel import Session, select

        from database import _get_engine
        from rfp_models import (
            DepartmentSection,
            RFPEventLog,
            RFPTicket,
        )

        engine = _get_engine()
        with Session(engine) as db:
            ticket_id = state["ticket_id"]

            # 1. Update ticket status
            ticket = db.get(RFPTicket, ticket_id)
            if ticket:
                ticket.status = state["status"]
                if state.get("handoff_to_part3"):
                    # Store handoff in the ticket (using handoff_payload field)
                    ticket.handoff_payload = state["handoff_to_part3"]
                ticket.updated_at = datetime.now(timezone.utc)
                db.add(ticket)

            # 2. Update department sections with drafts + evaluations
            handoff = state["handoff_payload"]
            departments = handoff.get("departments_needed", [])
            drafts = state.get("drafts", {})
            evaluations = state.get("evaluations", {})

            for dept_id in departments:
                existing = db.exec(
                    select(DepartmentSection).where(
                        DepartmentSection.ticket_id == ticket_id,
                        DepartmentSection.department_id == dept_id,
                    )
                ).first()

                if existing:
                    existing.draft_content = drafts.get(dept_id, existing.draft_content)
                    eval_result = evaluations.get(dept_id)
                    if eval_result:
                        existing.evaluation_results = json.dumps(eval_result, ensure_ascii=False)
                    existing.updated_at = datetime.now(timezone.utc)
                    db.add(existing)
                else:
                    # Create section if it doesn't exist (shouldn't happen but handle gracefully)
                    section = DepartmentSection(
                        ticket_id=ticket_id,
                        department_id=dept_id,
                        draft_content=drafts.get(dept_id, ""),
                        evaluation_results=json.dumps(evaluations.get(dept_id, {}), ensure_ascii=False),
                    )
                    db.add(section)

            # 3. Log event
            event = RFPEventLog(
                ticket_id=ticket_id,
                event=f"part2_{state['status']}",
                detail=(
                    f"Sections: {len(departments)}, "
                    f"needs_review: {len(state.get('sections_needing_review', []))}"
                ),
            )
            db.add(event)

            db.commit()

        logger.info("[%s] Part 2 results persisted: status=%s", ticket_id, state["status"])

    except Exception as exc:
        logger.error("[%s] Failed to persist Part 2 results: %s", ticket_id, exc)
        raise


# ---------------------------------------------------------------------------
# Trigger Part 2 from Part 1 — called when a ticket reaches analisis_completo
# ---------------------------------------------------------------------------


def trigger_part2(ticket_id: str) -> dict:
    """Load a completed Part 1 ticket and trigger Part 2 pipeline.

    This is the bridge between Part 1 and Part 2.
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

            if ticket.status != "analisis_completo":
                raise ValueError(
                    f"Ticket {ticket_id} has status '{ticket.status}'. "
                    f"Expected 'analisis_completo'."
                )

            if not ticket.handoff_payload:
                raise ValueError(f"Ticket {ticket_id} has no handoff_payload.")

            handoff = json.loads(ticket.handoff_payload)

        # Run Part 2 pipeline
        return run_response_pipeline(ticket_id, handoff)

    except Exception as exc:
        logger.exception("Failed to trigger Part 2 for ticket %s: %s", ticket_id, exc)
        raise