"""Question intent routing for the Brasaland support agent."""
from __future__ import annotations

import re

from graph.incident_tool_adapter import extract_incident_id
from graph.state import AgentState

_INCIDENT_INTENT = re.compile(
    r"(?i)\b(ticket|incidencia|incidente|caso|reclamo|reclamaci[oó]n)\w*\b"
)
_KNOWLEDGE_INTENT = re.compile(
    r"(?i)\b(al[eé]rg\w*|ingrediente\w*|men[uú]\w*|plato\w*|receta\w*|proveedor\w*|"
    r"fideliz\w*|descuento\w*|procedimiento\w*|pol[ií]tica\w*|horario\w*|"
    r"pedido\w*|residuo\w*|desperdicio\w*|limpieza\w*|allergen\w*|supplier\w*|"
    r"loyalty\w*|policy\w*|procedure\w*)\b"
)


def route_sources(state: AgentState) -> str:
    """Select incident tool, RAG, or both from the user's question alone."""
    question = state["question"]
    asks_about_incident = bool(_INCIDENT_INTENT.search(question)) or extract_incident_id(question) is not None
    asks_about_knowledge = bool(_KNOWLEDGE_INTENT.search(question))

    if asks_about_incident and asks_about_knowledge:
        return "incident_then_rag"
    if asks_about_incident:
        return "incident_only"
    return "rag_only"


def route_context(state: AgentState) -> str:
    """After retrieval, decide the next node based on whether we have context."""
    # Mixed queries always go through generate_node even when RAG returns empty
    # — the incident data may be sufficient to answer.
    if state.get("route") == "incident_then_rag":
        return "generate"
    if state.get("pending_proposal_was_present"):
        return "generate"
    return "generate" if state["context"] else "no_context"


def route_after_incident(state: AgentState) -> str:
    return "retrieve" if state.get("route") == "incident_then_rag" else "incident_answer"
