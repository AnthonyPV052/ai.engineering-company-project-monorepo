"""Preparación común de un turno del agente de soporte.

La Parte 1 (ruta HTTP ``POST /knowledge/query``) y la Parte 2 (WebSocket de
chat) atienden al **mismo** agente, así que comparten la resolución de la
propuesta de memoria pendiente: si el mensaje del encargado aprueba, rechaza,
edita o abandona la propuesta del turno anterior, eso se resuelve antes de
generar la respuesta.

Tenerlo en un módulo propio evita que la ruta HTTP y el canal WebSocket
divergen con el tiempo (y que el chat se convierta en una "app paralela").
"""

from __future__ import annotations

import logging
from typing import Any

from memory.classifier import classify_intention
from memory.store import get_pending_proposal, log_audit_event, resolve_proposal

logger = logging.getLogger("api.agent.turn_context")


def prepare_pending_proposal(session_id: str, question: str) -> tuple[bool, dict[str, Any] | None]:
    """Resuelve la propuesta pendiente de ``session_id`` frente a ``question``.

    Devuelve ``(pending_was_present, proposal_notice)``:

    - ``pending_was_present`` alimenta ``state["pending_proposal_was_present"]``
      para que el nodo ``generate`` no cree una propuesta nueva en el mismo
      turno en el que se acaba de resolver otra.
    - ``proposal_notice`` describe el resultado (``approved``/``rejected``/
      ``edited``/``discarded``/``pending``) para que la respuesta lo mencione.

    Nunca lanza: si la BD de memoria no está disponible se comporta como si no
    hubiera propuesta pendiente.
    """
    try:
        pending = get_pending_proposal(session_id)
    except Exception:
        logger.warning(
            "No se pudo consultar propuestas pendientes para session_id=%s (BD no disponible)",
            session_id,
            exc_info=True,
        )
        pending = None

    if not pending:
        return False, None

    classification = classify_intention(pending.proposed_summary, question)
    intention = classification.intention
    log_audit_event(
        event_type="classification_ambiguous" if intention == "unrelated" else "classification_" + intention,
        description="Clasificación del turno frente a propuesta pendiente.",
        event_data={
            "proposal_id": str(pending.id),
            "proposal_summary": pending.proposed_summary,
            "source_message": question,
            "classification": classification.model_dump(),
        },
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
            note=f"Explicit intention classification: {intention}; source_message={question}",
        )
        if resolved:
            return True, {"status": intention, "proposal_id": str(pending.id)}
        return True, None

    if intention == "topic_change":
        resolve_proposal(
            session_id=session_id,
            proposal_id=pending.id,
            resolution="discarded",
            actor="system",
            note=f"Topic change; source_message={question}",
        )
        return True, {"status": "discarded", "proposal_id": str(pending.id)}

    # La ambigüedad nunca es aprobación: se conserva la única propuesta pendiente.
    return True, {
        "status": "pending",
        "proposal_id": str(pending.id),
        "decision": "ambiguous; no change",
    }


__all__ = ["prepare_pending_proposal"]
