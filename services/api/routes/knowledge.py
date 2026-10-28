from __future__ import annotations

import logging
import time
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

# La API y el grafo se ejecutan juntos en services/api (localmente) y se
# copian juntos a /app en la imagen de Docker.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from graph.workflow import graph  # noqa: E402
from graph.tracing import actual_sources, finish_trace, read_trace, start_trace  # noqa: E402
from memory.classifier import classify_intention  # noqa: E402
from memory.store import get_pending_proposal, resolve_proposal, log_audit_event  # noqa: E402

logger = logging.getLogger("api.knowledge")
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    base_language: Literal["es", "en"] = "es"


class KnowledgeQueryResponse(BaseModel):
    answer: str
    trace_id: str
    sources: list[str]
    execution_order: list[str]
    memory_proposal: dict[str, object] | None = None
    session_id: str


@router.post("/query", response_model=KnowledgeQueryResponse)
def knowledge_query(payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
    """Devuelve respuesta, fuentes utilizadas y el orden de ejecución del agente."""
    started_at = time.perf_counter()
    trace_id = str(uuid.uuid4())
    session_id = payload.session_id or trace_id
    try:
        try:
            pending = get_pending_proposal(session_id)
        except Exception:
            logger.warning(
                "No se pudo consultar propuestas pendientes para session_id=%s (BD no disponible)",
                session_id,
            )
            pending = None
        pending_was_present = pending is not None
        proposal_notice = None
        if pending:
            classification = classify_intention(pending.proposed_summary, payload.question)
            intention = classification.intention
            log_audit_event(
                event_type="classification_ambiguous" if intention == "unrelated" else "classification_" + intention,
                description="Clasificación del turno frente a propuesta pendiente.",
                event_data={"proposal_id": str(pending.id), "proposal_summary": pending.proposed_summary,
                            "source_message": payload.question, "classification": classification.model_dump()},
                session_id=session_id,
                actor="system",
                proposal_id=pending.id,
            )
            if intention in {"approved", "rejected", "edited"}:
                resolved = resolve_proposal(
                    session_id=session_id,
                    proposal_id=pending.id,
                    resolution="approved" if intention in {"approved", "edited"} else "rejected",
                    edited_summary=classification.edited_summary if intention == "edited" else "",
                    edited_location=classification.edited_location,
                    edited_category=classification.edited_category,
                    actor="user",
                    note=f"Explicit intention classification: {intention}; source_message={payload.question}",
                )
                if resolved:
                    proposal_notice = {"status": intention, "proposal_id": str(pending.id)}
            elif intention == "topic_change":
                resolve_proposal(
                    session_id=session_id, proposal_id=pending.id, resolution="discarded",
                    actor="system", note=f"Topic change; source_message={payload.question}",
                )
                proposal_notice = {"status": "discarded", "proposal_id": str(pending.id)}
            else:
                # Ambiguity is never approval; preserve the single pending proposal.
                proposal_notice = {"status": "pending", "proposal_id": str(pending.id), "decision": "ambiguous; no change"}
        # Cada petición tiene su propio hilo para que el checkpointer de
        # LangGraph no mezcle el estado de consultas distintas.
        start_trace(trace_id, payload.question)
        result = graph.invoke(
            {
                "question": payload.question,
                "context": [],
                "answer": "",
                "trace_id": trace_id,
                "session_id": session_id,
                "base_language": payload.base_language,
                "pending_proposal_was_present": pending_was_present,
                "memory_proposal": proposal_notice,
            },
            config={"configurable": {"thread_id": trace_id}},
        )
        events = read_trace(trace_id)
        execution_order = [
            event.get("node")
            for event in events
            if event.get("event") == "node_completed"
        ]
        sources = actual_sources(events)
        finish_trace(
            trace_id,
            result["answer"],
            sources=sources,
            execution_order=execution_order,
            memory_proposal=result.get("memory_proposal"),
            session_id=session_id,
        )
        return KnowledgeQueryResponse(
            answer=result["answer"],
            trace_id=trace_id,
            sources=sources,
            execution_order=execution_order,
            memory_proposal=result.get("memory_proposal"),
            session_id=session_id,
        )
    except Exception as exc:
        logger.exception(
            "Error ejecutando agente de soporte trace_id=%s elapsed_ms=%.1f",
            trace_id,
            (time.perf_counter() - started_at) * 1000,
        )
        raise HTTPException(status_code=502, detail="No se pudo consultar la base de conocimiento.") from exc


@router.get("/traces/{trace_id}")
def knowledge_trace(trace_id: str) -> dict[str, object]:
    try:
        return {"trace_id": trace_id, "events": read_trace(trace_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Trace no encontrado.") from exc
