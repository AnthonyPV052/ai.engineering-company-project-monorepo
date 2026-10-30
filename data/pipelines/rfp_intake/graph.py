"""LangGraph pipeline for RFP intake (Parte 1).

Orchestrator → Workers (per department) → Synthesizer.

States:
  analizando → [classifier] → descartado (if invalid)
                            → [orchestrator → workers → synthesizer] → analisis_completo

Handoff to Part 2: ticket_id + handoff_payload (JSON) stored in rfp_ticket.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure the API module is importable
API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

logger = logging.getLogger("rfp_intake.graph")

# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------


class RFPIntakeState(dict):
    """Mutable state dict for the RFP intake graph.

    Keys are accessed as dict items for LangGraph compatibility.
    """

    ticket_id: str
    pdf_path: str
    raw_markdown: str
    status: str
    classification_result: dict
    metadata: dict
    readability_metrics: dict
    departments_needed: list[str]
    worker_results: dict  # department_id → worker output dict
    synthesis: str
    handoff_payload: str
    errors: list[str]


def make_initial_state(ticket_id: str, pdf_path: str) -> dict:
    return {
        "ticket_id": ticket_id,
        "pdf_path": pdf_path,
        "raw_markdown": "",
        "status": "analizando",
        "classification_result": {},
        "metadata": {},
        "readability_metrics": {},
        "departments_needed": [],
        "worker_results": {},
        "synthesis": "",
        "handoff_payload": "",
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Node: PDF → Markdown conversion
# ---------------------------------------------------------------------------


def convert_pdf_node(state: dict) -> dict:
    """Convert PDF to Markdown and compute readability metrics."""
    from data.pipelines.rfp_intake.converter import (
        compute_readability_metrics,
        pdf_to_markdown,
    )

    logger.info("[%s] Converting PDF: %s", state["ticket_id"], state["pdf_path"])

    markdown = pdf_to_markdown(state["pdf_path"])
    readability = compute_readability_metrics(markdown)

    state["raw_markdown"] = markdown
    state["readability_metrics"] = readability

    # Save markdown alongside PDF for debugging
    md_path = Path(state["pdf_path"]).with_suffix(".md")
    md_path.write_text(markdown, encoding="utf-8")
    logger.info("[%s] Markdown saved to %s", state["ticket_id"], md_path)

    return state


# ---------------------------------------------------------------------------
# Node: Classifier
# ---------------------------------------------------------------------------


def classify_node(state: dict) -> dict:
    """Classify document as valid RFP or not."""
    from data.pipelines.rfp_intake.classifier import classify_document

    logger.info("[%s] Classifying document...", state["ticket_id"])

    result = classify_document(state["raw_markdown"])
    state["classification_result"] = result

    if not result.get("is_valid", False):
        state["status"] = "descartado"
        reason = result.get("classification_reason", "Clasificador rechazó el documento")
        logger.info("[%s] Document DESCARTED: %s", state["ticket_id"], reason)
    else:
        # Merge extracted metadata
        meta = result.get("metadata", {})
        meta["classifier_confidence"] = result.get("confidence")
        meta["classification_reason"] = result.get("classification_reason")
        meta["departments_needed"] = json.dumps(result.get("departments_needed", ["marketing"]), ensure_ascii=False)
        # Merge readability metrics
        meta.update(state["readability_metrics"])
        state["metadata"] = meta
        logger.info(
            "[%s] Document ACCEPTED. Departments: %s",
            state["ticket_id"], result.get("departments_needed"),
        )

    return state


# ---------------------------------------------------------------------------
# Node: Orchestrator — decides which workers to invoke
# ---------------------------------------------------------------------------


def orchestrator_node(state: dict) -> dict:
    """Determine which departments are needed and dispatch work."""
    if state["status"] == "descartado":
        logger.info("[%s] Skipping orchestrator — document was discarded.", state["ticket_id"])
        return state

    departments = state["classification_result"].get("departments_needed", ["marketing"])
    state["departments_needed"] = departments
    logger.info("[%s] Orchestrator dispatching to: %s", state["ticket_id"], departments)
    return state


# ---------------------------------------------------------------------------
# Node: Workers (one per department)
# ---------------------------------------------------------------------------


def workers_node(state: dict) -> dict:
    """Run all department workers and collect results."""
    from data.pipelines.rfp_intake.workers import run_worker

    if state["status"] == "descartado":
        return state

    departments = state.get("departments_needed", [])
    worker_results: dict[str, Any] = {}

    for dept_id in departments:
        logger.info("[%s] Running worker: %s", state["ticket_id"], dept_id)
        try:
            result = run_worker(dept_id, state["raw_markdown"], state["metadata"])
            worker_results[dept_id] = result
        except Exception as exc:
            logger.error("[%s] Worker %s failed: %s", state["ticket_id"], dept_id, exc)
            worker_results[dept_id] = {
                "department_id": dept_id,
                "key_aspects": f"Error analizando: {exc}",
                "open_questions": [],
                "needs_clarification": True,
            }
            state.setdefault("errors", []).append(f"Worker {dept_id}: {exc}")

    state["worker_results"] = worker_results
    return state


# ---------------------------------------------------------------------------
# Node: Synthesizer
# ---------------------------------------------------------------------------


def synthesizer_node(state: dict) -> dict:
    """Consolidate worker results into a summary for Sales (Camila)."""
    if state["status"] == "descartado":
        return state

    worker_results = state.get("worker_results", {})
    departments = state.get("departments_needed", [])
    meta = state.get("metadata", {})

    lines: list[str] = []
    lines.append("# Resumen de Análisis de RFP — Parte 1")
    lines.append("")
    lines.append(f"**Ticket:** {state['ticket_id']}")
    lines.append(f"**Cliente:** {meta.get('client_name', 'No especificado')}")
    lines.append(f"**Ubicación:** {meta.get('location', 'No especificada')}")
    lines.append(f"**Tipo de servicio:** {meta.get('service_type', 'No especificado')}")
    lines.append(f"**Alcance:** {meta.get('scope', 'No detallado')}")
    lines.append(f"**Presupuesto:** {meta.get('budget_range', 'No especificado')}")
    lines.append(f"**Fecha límite:** {meta.get('deadline', 'No especificada')}")
    lines.append("")

    if meta.get("word_count"):
        lines.append(f"**Longitud del documento:** {meta['word_count']} palabras")
    if meta.get("flesch_kincaid_grade"):
        lines.append(f"**Legibilidad (Flesch-Kincaid):** grado {meta['flesch_kincaid_grade']}")
    if meta.get("gunning_fog"):
        lines.append(f"**Legibilidad (Gunning Fog):** {meta['gunning_fog']}")
    lines.append("")

    lines.append("## Departamentos Involucrados")
    lines.append("")
    for dept_id in departments:
        label = {
            "marketing": "Marketing — Camila Ospina",
            "operaciones": "Operaciones — Felipe Guerrero",
            "procurement": "Procurement — Lucía Fernández",
            "training": "Training — Jake Morrison",
        }.get(dept_id, dept_id)
        lines.append(f"### {label}")
        result = worker_results.get(dept_id, {})
        key_aspects = result.get("key_aspects", "*No disponible*")
        lines.append("")
        lines.append(key_aspects)
        lines.append("")

        open_qs = result.get("open_questions", [])
        if open_qs:
            lines.append("**Preguntas abiertas:**")
            for q in open_qs:
                lines.append(f"- {q}")
            lines.append("")

        if result.get("needs_clarification"):
            lines.append("> ⚠️ Este departamento necesita aclaraciones adicionales.")
            lines.append("")

    lines.append("---")
    lines.append("**Handoff a Parte 2:** Este ticket está listo para la generación de borradores.")
    lines.append(f"Ticket ID: `{state['ticket_id']}`")

    state["synthesis"] = "\n".join(lines)

    # Build handoff payload
    handoff = {
        "ticket_id": state["ticket_id"],
        "status": "analisis_completo",
        "client_name": meta.get("client_name"),
        "service_type": meta.get("service_type"),
        "departments_needed": departments,
        "department_contacts": {
            "marketing": "Camila Ospina",
            "operaciones": "Felipe Guerrero",
            "procurement": "Lucía Fernández",
            "training": "Jake Morrison",
        },
        "key_aspects_by_department": {
            dept_id: worker_results.get(dept_id, {}).get("key_aspects", "")
            for dept_id in departments
        },
        "open_questions": {
            dept_id: worker_results.get(dept_id, {}).get("open_questions", [])
            for dept_id in departments
        },
        "readability_metrics": {
            k: v for k, v in state["readability_metrics"].items() if v is not None
        },
    }
    state["handoff_payload"] = json.dumps(handoff, indent=2, ensure_ascii=False)
    state["status"] = "analisis_completo"

    logger.info("[%s] Synthesis complete. Status → analisis_completo", state["ticket_id"])
    return state


# ---------------------------------------------------------------------------
# Router: after classifier, decide next step
# ---------------------------------------------------------------------------


def route_after_classifier(state: dict) -> str:
    """Route to orchestrator if valid, or to end if descarted."""
    if state.get("status") == "descartado":
        return "end"
    return "orchestrator"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------


def build_rfp_intake_graph():
    """Build and return the LangGraph StateGraph for RFP intake."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        raise ImportError("langgraph is required. Install with: uv add langgraph")

    builder = StateGraph(RFPIntakeState)

    builder.add_node("convert_pdf", convert_pdf_node)
    builder.add_node("classify", classify_node)
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("workers", workers_node)
    builder.add_node("synthesizer", synthesizer_node)

    builder.add_edge(START, "convert_pdf")
    builder.add_edge("convert_pdf", "classify")
    builder.add_conditional_edges(
        "classify",
        route_after_classifier,
        {
            "orchestrator": "orchestrator",
            "end": END,
        },
    )
    builder.add_edge("orchestrator", "workers")
    builder.add_edge("workers", "synthesizer")
    builder.add_edge("synthesizer", END)

    graph = builder.compile()
    return graph


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def run_pipeline(ticket_id: str, pdf_path: str) -> dict:
    """Run the full RFP intake pipeline for a given PDF.

    This is called by the Celery task or directly from scripts.
    It persists results to PostgreSQL and returns the final state.
    """
    graph = build_rfp_intake_graph()
    initial = make_initial_state(ticket_id, pdf_path)
    result = graph.invoke(initial)

    # Persist to DB (non-blocking — log failures instead of crashing)
    try:
        _persist_results(result)
    except Exception as exc:
        logger.warning('[%s] Failed to persist results: %s', ticket_id, exc)

    return result


def _persist_results(state: dict) -> None:
    """Persist pipeline results to PostgreSQL via SQLModel."""
    try:
        from sqlmodel import Session, select

        from database import _get_engine
        from rfp_models import (
            DepartmentSection,
            RFPEventLog,
            RFPMetadata,
            RFPTicket,
        )

        engine = _get_engine()
        with Session(engine) as db:
            # 1. Update ticket status
            ticket = db.get(RFPTicket, state["ticket_id"])
            if ticket:
                ticket.status = state["status"]
                ticket.handoff_payload = state.get("handoff_payload")
                ticket.updated_at = datetime.now(timezone.utc)
                db.add(ticket)

            # 2. Upsert metadata
            meta = state.get("metadata", {})
            existing_meta = db.exec(
                select(RFPMetadata).where(RFPMetadata.ticket_id == state["ticket_id"])
            ).first()

            if existing_meta:
                for key, value in meta.items():
                    if hasattr(existing_meta, key):
                        setattr(existing_meta, key, value)
                db.add(existing_meta)
            else:
                meta_record = RFPMetadata(
                    ticket_id=state["ticket_id"],
                    raw_markdown=state.get("raw_markdown", ""),
                    **{k: v for k, v in meta.items() if hasattr(RFPMetadata, k)},
                )
                db.add(meta_record)

            # 3. Save department sections
            for dept_id, worker_result in state.get("worker_results", {}).items():
                section = DepartmentSection(
                    ticket_id=state["ticket_id"],
                    department_id=dept_id,
                    key_aspects=worker_result.get("key_aspects", ""),
                )
                db.add(section)

            # 4. Log event
            event = RFPEventLog(
                ticket_id=state["ticket_id"],
                event=f"pipeline_{state['status']}",
                detail=state.get("classification_result", {}).get("classification_reason"),
            )
            db.add(event)

            db.commit()

        logger.info("[%s] Results persisted to DB: status=%s", state["ticket_id"], state["status"])

    except Exception as exc:
        logger.error("[%s] Failed to persist results: %s", state["ticket_id"], exc)
        raise