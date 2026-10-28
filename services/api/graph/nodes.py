import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from graph.state import AgentState
from graph.tracing import record_node
# ── MCP-based incident tool (uses langchain-mcp-adapters) ───────────
from graph.incident_tool_adapter import (
    IncidentToolInput,
    extract_incident_filters,
    extract_incident_id,
    list_incidents,
    lookup_incident,
    _INCIDENT_LIST_LIMIT,
)
from graph.routing import route_sources

from data.pipelines.rag import (
    retrieve,
    generate_answer,
    DEFAULT_MIN_SCORE,
)
from memory.generation import generate_answer_with_memory
from memory.store import (
    create_proposal,
    search_memories,
)

logger = logging.getLogger("api.agent")
_RETRIEVAL_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-retrieval")
RETRIEVAL_TIMEOUT_SECONDS = float(os.getenv("AGENT_RAG_RETRIEVAL_TIMEOUT_SECONDS", "75"))


def retrieve_node(state: AgentState) -> dict[str, object]:
    # In mixed queries (incident_then_rag), if the incident was already confirmed
    # by the incident tool, skip the RAG retrieval to reduce latency.
    if state.get("route") == "incident_then_rag" and state.get("incident"):
        logger.info("Incidencia confirmada en ruta mixta; omitiendo RAG")
        output: dict[str, object] = {"context": [], "retrieval_error": "skipped_after_incident"}
        trace_output = {"outcome": "skipped_after_incident"}
        record_node(state, "retrieve", trace_output)
        return output

    try:
        future = _RETRIEVAL_EXECUTOR.submit(
            retrieve,
            state["question"],
            min_score=DEFAULT_MIN_SCORE,
        )
        context = future.result(timeout=RETRIEVAL_TIMEOUT_SECONDS)
        output: dict[str, object] = {"context": context, "retrieval_error": None}
        trace_output = {"context": context, "outcome": "ok", "result_count": len(context)}
    except Exception as exc:
        # Qdrant, embedding gateways and DNS can be temporarily unavailable.
        # Return a traceable empty result rather than failing the entire graph.
        if isinstance(exc, FutureTimeout):
            logger.warning("RAG retrieval excedió %.1fs", RETRIEVAL_TIMEOUT_SECONDS)
        else:
            logger.exception("Falló la recuperación RAG")
        output = {"context": [], "retrieval_error": type(exc).__name__}
        trace_output = {"outcome": "service_error", "error_type": type(exc).__name__}
    record_node(state, "retrieve", trace_output)
    return output


def source_router_node(state: AgentState) -> dict[str, object]:
    route = route_sources(state)
    sources = {
        "rag_only": ["rag"],
        "incident_only": ["incident_tool"],
        "incident_then_rag": ["incident_tool", "rag"],
    }[route]
    output = {"route": route, "sources": sources}
    record_node(state, "source_router", output)
    return output


def incident_tool_node(state: AgentState) -> dict[str, object]:
    incident_id = extract_incident_id(state["question"])
    logger.info(
        "Ejecutando tool de incidencias route=%s id_present=%s",
        state.get("route"), bool(incident_id),
    )

    if incident_id:
        # Consulta de una incidencia concreta por ID
        tool_result = lookup_incident(IncidentToolInput(ticket_id=incident_id))
        incident = tool_result.incident.model_dump(mode="json") if tool_result.incident else None
        output: dict[str, object] = {
            "incident_id": tool_result.ticket_id,
            "incident": incident,
            "incident_error": None if tool_result.outcome == "found" else tool_result.outcome,
            "incidents": None,
            "incidents_truncated": False,
            "sources": ["incident_tool"] if state.get("route") == "incident_only" else ["incident_tool", "rag"],
        }
        record_node(state, "incident_tool", {
            **tool_result.model_dump(mode="json"),
            "method": "GET",
            "endpoint": "/api/incidents/{ticket_id}",
        })
    else:
        # Sin ID explícito: extraer filtros del lenguaje natural y listar
        filters = extract_incident_filters(state["question"])
        logger.info("Filtros extraídos para listado de incidencias: %s", filters)
        try:
            items = list_incidents(filters)
        except Exception:
            logger.exception("Falló el listado de incidencias")
            output = {
                "incident_id": None,
                "incident": None,
                "incident_error": "service_error",
                "incidents": [],
                "incidents_truncated": False,
            }
            record_node(state, "incident_tool", {
                "outcome": "service_error",
                "error": "service_error",
                "method": "GET",
                "endpoint": "/api/incidents",
            })
            return output

        truncated = len(items) > _INCIDENT_LIST_LIMIT
        visible_items = items[:_INCIDENT_LIST_LIMIT]
        output: dict[str, object] = {
            "incident_id": None,
            "incident": None,
            "incident_error": None if visible_items else "not_found",
            "incidents": visible_items,
            "incidents_truncated": truncated,
        }
        trace_incidents = [
            {"id": item.get("id"), "title": item.get("title"), "status": item.get("status")}
            for item in visible_items
        ]
        record_node(state, "incident_tool", {
            "outcome": "found" if items else "not_found",
            "count": len(items),
            "truncated": truncated,
            "filters": filters,
            "incidents": trace_incidents,
            "method": "GET",
            "endpoint": "/api/incidents",
        })
    return output


def _format_incident_list(incidents: list[dict[str, object]]) -> str:
    """Formatea una lista de incidencias para mostrarla como texto."""
    if not incidents:
        return "No encontré incidencias con esos criterios."

    lines: list[str] = []
    for item in incidents:
        tid = item.get("id", "—")
        ttl = item.get("title", "—")
        sts = item.get("status", "—")
        cat = item.get("category", "—")
        brn = item.get("branch", "—")
        lines.append(f"• {tid}  |  *{ttl}*  |  _{sts}_  |  {cat}  |  {brn}")
    return "\n".join(lines)


def incident_answer_node(state: AgentState) -> dict[str, object]:
    # Si es un listado (sin ID explícito)
    incidents = state.get("incidents")
    if incidents is not None:
        truncated = state.get("incidents_truncated", False)
        answer_parts: list[str] = []
        if incidents:
            answer_parts.append("Estas son las incidencias que encontré:\n")
            answer_parts.append(_format_incident_list(incidents))
            if truncated:
                answer_parts.append(
                    f"\n\n⚠️ Solo te muestro los primeros {_INCIDENT_LIST_LIMIT} resultados. "
                    "Hay más incidencias que coinciden con tu búsqueda. "
                    "Puedes preguntar con más detalles para acotar la lista."
                )
        else:
            answer_parts.append("No encontré incidencias con esos criterios.")
        answer = "".join(answer_parts)
        output = {"answer": answer}
        record_node(state, "incident_answer", output)
        return output

    # Consulta de una incidencia concreta por ID
    incident = state.get("incident")
    logger.info(
        "Construyendo respuesta de incidencia outcome=%s",
        "error" if state.get("incident_error") else "found" if incident else "missing",
    )
    if state.get("incident_error") or incident is None or not incident.get("status"):
        answer = "No pude confirmar el estado de ese ticket ahora mismo."
    else:
        answer = f"El ticket {incident.get('id', state.get('incident_id', 'solicitado'))} tiene estado: {incident['status']}."
        if incident.get("title"):
            answer += f" Título: {incident['title']}."
        if incident.get("updated_at"):
            answer += f" Última actualización: {incident['updated_at']}."
        if state.get("route") == "incident_then_rag" and state.get("retrieval_error"):
            answer += " No pude consultar la documentación complementaria ahora mismo."
    output = {"answer": answer}
    record_node(state, "incident_answer", output)
    return output


def generate_node(state: AgentState) -> dict[str, object]:
    if not state.get("context") and not state.get("incident") and not state.get("incidents"):
        # A proposal decision may be bundled with an ordinary question. Keep
        # the normal no-context answer for that question, but report the
        # proposal outcome rather than silently dropping it.
        outcome = state.get("memory_proposal")
        answer = "No encontré información suficiente en la base de conocimiento de Brasaland."
        if outcome:
            status = outcome.get("status")
            if status == "approved":
                answer = "La memoria propuesta quedó guardada. No encontré información suficiente para la pregunta adicional en la base de conocimiento de Brasaland."
            elif status == "rejected":
                answer = "La propuesta de memoria fue descartada. No encontré información suficiente para la pregunta adicional en la base de conocimiento de Brasaland."
            elif status == "edited":
                answer = "La propuesta editada quedó guardada. No encontré información suficiente para la pregunta adicional en la base de conocimiento de Brasaland."
            elif status == "discarded":
                answer = "La propuesta anterior fue descartada. No encontré información suficiente para la pregunta adicional en la base de conocimiento de Brasaland."
            elif status == "pending":
                answer = "La propuesta sigue pendiente de una respuesta clara. No encontré información suficiente para la pregunta adicional en la base de conocimiento de Brasaland."
        output = {"answer": answer, "memory_proposal": outcome}
        record_node(state, "generate", output)
        return output

    if state.get("retrieval_error"):
        if state.get("incident") and state["incident"].get("status"):
            incident = state["incident"]
            answer = (
                f"El ticket {incident.get('id', state.get('incident_id', 'solicitado'))} "
                f"tiene estado: {incident['status']}. No pude consultar la documentación "
                "complementaria ahora mismo."
            )
        else:
            answer = "No pude consultar el servicio de conocimiento ahora mismo. Inténtalo de nuevo más tarde."
        output = {"answer": answer}
        record_node(state, "generate", output)
        return output

    if state.get("incident_error") and not state.get("incidents"):
        # Mixed request, but a failed live lookup: do not let the model infer a
        # current status from RAG or from its prior knowledge.
        output = {"answer": "No pude confirmar el estado de ese ticket ahora mismo."}
        record_node(state, "generate", output)
        return output

    context = list(state["context"])
    session_id = state.get("session_id", state["trace_id"])
    try:
        memories = search_memories(state["question"], location_filter=None)
    except Exception:
        logger.exception("No se pudo recuperar la memoria episódica (BD no disponible)")
        memories = []

    # Para consultas mixtas: añadir la lista de incidencias al contexto del RAG
    incidents = state.get("incidents")
    if incidents:
        text_lines = ["Incidencias encontradas:"]
        for item in incidents:
            parts = [f"- {item.get('id', '—')} ({item.get('title', '—')})"]
            if item.get("status"):
                parts.append(f"Estado: {item['status']}")
            if item.get("category"):
                parts.append(f"Categoría: {item['category']}")
            if item.get("branch"):
                parts.append(f"Sucursal: {item['branch']}")
            if item.get("origin"):
                parts.append(f"Origen: {item['origin']}")
            text_lines.append(". ".join(parts))
        if state.get("incidents_truncated"):
            text_lines.append(
                f"(Solo se muestran los primeros {_INCIDENT_LIST_LIMIT} — "
                "hay más incidencias que coinciden con la búsqueda.)"
            )
        context.append({
            "source_document": "GET /api/incidents",
            "section": "Listado de incidencias",
            "text": "\n".join(text_lines),
        })

    incident = state.get("incident")
    if incident:
        context.append({
            "source_document": "GET /api/incidents/{id}",
            "text": "\n".join(
                f"{key}: {value}" for key, value in incident.items()
                if key in {"id", "title", "description", "status", "category", "origin", "branch", "created_at", "updated_at"}
            ),
        })
    try:
        memories = search_memories(state["question"], location_filter=None)
    except Exception:
        logger.exception("No se pudo recuperar la memoria episódica")
        memories = []
    try:
        answer, suggestion = generate_answer_with_memory(
            state["question"], context,
            memory_context=[{"summary": item.summary, "location": item.location, "category": item.category} for item in memories],
            base_language=state.get("base_language", "es"),
        )
    except Exception as exc:
        logger.exception("No se pudo generar una respuesta RAG")
        if incident and incident.get("status"):
            answer = (
                f"El ticket {incident.get('id', state.get('incident_id', 'solicitado'))} "
                f"tiene estado: {incident['status']}. No pude completar la respuesta "
                "con la documentación ahora mismo."
            )
        else:
            answer = "No pude consultar el servicio de conocimiento ahora mismo. Inténtalo de nuevo más tarde."
        output = {"answer": answer, "generation_error": type(exc).__name__}
        record_node(state, "generate", output)
        return output
    memory_proposal = None
    if suggestion.should_store and suggestion.summary.strip() and not state.get("pending_proposal_was_present", False):
        proposal = create_proposal(
            session_id=session_id,
            summary=suggestion.summary,
            location=suggestion.location,
            category=suggestion.category,
            confidence=suggestion.confidence,
            trigger_message=state["question"],
        )
        if proposal:
            confirmation = (
                f"\n\nWould you like me to remember this for future conversations? “{proposal.proposed_summary}” Reply yes to save it or no to discard it."
                if state.get("base_language", "es") == "en"
                else f"\n\n¿Quieres que recuerde esto para futuras conversaciones? «{proposal.proposed_summary}» Responde sí para guardarlo o no para descartarlo."
            )
            answer += confirmation
            memory_proposal = {"id": str(proposal.id), "summary": proposal.proposed_summary, "status": "pending"}
    output = {"answer": answer, "memory_proposal": memory_proposal or state.get("memory_proposal")}
    record_node(state, "generate", output)
    return output


def no_context_node(state: AgentState) -> dict[str, object]:
    if state.get("incident_error") or state.get("incident"):
        return incident_answer_node(state)
    if state.get("retrieval_error"):
        output = {
            "answer": "No pude consultar el servicio de conocimiento ahora mismo. Inténtalo de nuevo más tarde."
        }
        record_node(state, "no_context", output)
        return output
    output = {
        "answer": (
            "No encontré información suficiente "
            "en la base de conocimiento de Brasaland."
        ),
    }
    record_node(state, "no_context", output)
    return output