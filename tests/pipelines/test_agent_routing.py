"""Offline evaluations for automatic support-agent source routing."""
from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for path in (ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from graph.routing import route_sources, route_context  # noqa: E402
from graph.incident_tool_adapter import IncidentToolInput, IncidentToolOutput  # noqa: E402
from graph.nodes import generate_node, no_context_node, retrieve_node  # noqa: E402


def _state(question: str) -> dict[str, str]:
    return {"question": question}


def test_ticket_status_question_routes_to_tool_without_rag() -> None:
    route = route_sources(
        _state("¿Cuál es el estado del ticket 8f14e45f-ea7a-4a12-9c17-000000000001?")
    )

    assert route == "incident_only"


def test_knowledge_question_routes_to_rag_without_incident_tool() -> None:
    route = route_sources(_state("¿Qué alérgenos tiene la Ensalada Tropical?"))

    assert route == "rag_only"


def test_memory_recall_question_routes_to_generation_without_rag_context() -> None:
    state = {
        "question": "¿Recuerdas algo sobre el gerente de Medellín?",
        "context": [],
        "route": "rag_only",
    }

    assert route_context(state) == "generate"


def test_explicit_remember_request_routes_to_generation_without_rag_context() -> None:
    state = {
        "question": "Recuerda esto: Dejamos de ofrecer La Ensalada Tropical en la sede de Medellín.",
        "context": [],
        "route": "rag_only",
    }

    assert route_context(state) == "generate"


def test_non_recall_question_without_context_keeps_no_context_route() -> None:
    state = {"question": "¿Cuál es el clima hoy?", "context": [], "route": "rag_only"}

    assert route_context(state) == "no_context"


def test_memory_recall_passes_only_search_results_to_answer_generator(monkeypatch) -> None:
    from types import SimpleNamespace
    import graph.nodes as nodes
    from memory.generation import MemorySuggestion

    approved_memory = SimpleNamespace(
        summary="El gerente de Medellín prefiere reportes de incidencias por WhatsApp.",
        location="Medellín",
        category="preferencias",
    )
    captured = {}

    search_call = {}

    def fake_search(*args, **kwargs):
        search_call.update(kwargs)
        return [approved_memory]

    monkeypatch.setattr(nodes, "search_memories", fake_search)

    def fake_generate(question, context, memory_context=None, base_language="es"):
        captured["memory_context"] = memory_context
        return "La preferencia guardada es WhatsApp.", MemorySuggestion()

    monkeypatch.setattr(nodes, "generate_answer_with_memory", fake_generate)
    state = {
        "question": "¿Recuerdas algo sobre el gerente de Medellín?",
        "context": [],
        "answer": "",
        "trace_id": "test-memory-recall",
        "route": "rag_only",
    }

    update = generate_node(state)

    assert update["answer"] == "La preferencia guardada es WhatsApp."
    assert captured["memory_context"] == [{
        "summary": approved_memory.summary,
        "location": "Medellín",
        "category": "preferencias",
    }]
    assert search_call["threshold"] == 0.60


def test_memory_recall_without_matches_does_not_invoke_generator(monkeypatch) -> None:
    import graph.nodes as nodes

    monkeypatch.setattr(nodes, "search_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        nodes, "generate_answer_with_memory",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("generator should not run")),
    )
    state = {
        "question": "¿Recuerdas algo sobre el gerente de Medellín?",
        "context": [],
        "answer": "",
        "trace_id": "test-memory-recall-empty",
        "route": "rag_only",
    }

    update = generate_node(state)

    assert "ni memorias aprobadas" in update["answer"]


def test_explicit_remember_request_generates_and_creates_proposal(monkeypatch) -> None:
    from types import SimpleNamespace
    import graph.nodes as nodes
    from memory.generation import MemorySuggestion

    monkeypatch.setattr(nodes, "search_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        nodes,
        "generate_answer_with_memory",
        lambda *args, **kwargs: (
            "Entendido, propongo guardar el cambio.",
            MemorySuggestion(
                should_store=True,
                summary="La Ensalada Tropical dejó de ofrecerse en la sede de Medellín.",
                location="Medellín",
                category="general",
                confidence=0.9,
            ),
        ),
    )
    created = {}

    def fake_create_proposal(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(
            id="proposal-1",
            proposed_summary=kwargs["summary"],
        )

    monkeypatch.setattr(nodes, "create_proposal", fake_create_proposal)
    state = {
        "question": "Recuerda esto: Dejamos de ofrecer La Ensalada Tropical en la sede de Medellín.",
        "context": [],
        "answer": "",
        "trace_id": "test-explicit-memory-request",
        "session_id": "test-session",
        "route": "rag_only",
        "base_language": "es",
    }

    update = generate_node(state)

    assert update["memory_proposal"]["status"] == "pending"
    assert update["memory_proposal"]["summary"] == created["summary"]
    assert created["location"] == "Medellín"
    assert "Responde sí para guardarlo" in update["answer"]


def test_request_for_ticket_and_procedure_routes_tool_then_rag() -> None:
    route = route_sources(
        _state("¿Qué estado tiene el ticket ABC-123 y cuál es el procedimiento para resolverlo?")
    )

    assert route == "incident_then_rag"


def test_explicit_incident_reference_routes_to_live_incident_source() -> None:
    """Evaluation: an explicitly identified case must not be answered from RAG."""
    assert route_sources(_state("Show me ticket INC-204 and its current status")) == "incident_only"


def test_supplier_policy_question_does_not_call_incident_tool() -> None:
    """Evaluation: knowledge-only questions must not trigger an incident lookup."""
    assert route_sources(_state("¿Cuál es la política de descuentos para proveedores?")) == "rag_only"


def test_incident_tool_input_output_contract() -> None:
    assert IncidentToolInput(ticket_id="ABC-123").ticket_id == "ABC-123"
    missing_id = IncidentToolInput()
    assert missing_id.ticket_id is None

    result = IncidentToolOutput(ticket_id="ABC-123", outcome="not_found")
    assert result.incident is None
    assert result.outcome == "not_found"


def test_incident_transport_uses_mcp_adapter(monkeypatch) -> None:
    """Verify the adapter calls the MCP tool via langchain-mcp-adapters."""
    from graph import incident_tool_adapter
    from incident_models import IncidentResponse

    called_with = {}
    expected_incident = IncidentResponse(
        id="ABC-123",
        title="Broken oven",
        description="Oven is not heating",
        category="equipment_failure",
        status="open",
        origin="branch",
        branch="central",
    )

    async def fake_async_call(tool_name, arguments):
        called_with["tool_name"] = tool_name
        called_with["arguments"] = arguments
        return json.loads(expected_incident.model_dump_json())

    monkeypatch.setattr(
        incident_tool_adapter, "_async_call_mcp_tool", fake_async_call
    )
    monkeypatch.setenv("BRASALAND_MCP_SERVER_URL", "http://localhost:8100/mcp")

    result = incident_tool_adapter.lookup_incident(
        IncidentToolInput(ticket_id="ABC-123")
    )
    assert result.outcome == "found"
    assert result.incident is not None
    assert result.incident.id == "ABC-123"
    assert called_with["tool_name"] == "incidents_get"
    assert called_with["arguments"] == {"incident_id": "ABC-123"}

    # Also test list_incidents
    incident_tool_adapter.list_incidents({"status": "open"})
    assert called_with["tool_name"] == "incidents_list"
    assert "status" in called_with["arguments"]


def test_trace_sources_exclude_skipped_rag_and_preserve_execution_order() -> None:
    from graph.tracing import actual_sources

    events = [
        {"event": "node_completed", "node": "source_router", "output": {"sources": ["incident_tool", "rag"]}},
        {"event": "node_completed", "node": "incident_tool", "output": {"outcome": "found"}},
        {"event": "node_completed", "node": "retrieve", "output": {"outcome": "skipped"}},
    ]
    assert actual_sources(events) == ["incident_tool"]
    assert [event["node"] for event in events if event["event"] == "node_completed"] == [
        "source_router", "incident_tool", "retrieve"
    ]


def test_missing_incident_is_reported_as_not_found(monkeypatch) -> None:
    from graph import incident_tool_adapter

    async def fake_not_found(tool_name, arguments):
        return {"error": "not_found", "code": "not_found", "message": "Not found", "http_status": 404}

    monkeypatch.setattr(incident_tool_adapter, "_async_call_mcp_tool", fake_not_found)
    result = incident_tool_adapter.lookup_incident(IncidentToolInput(ticket_id="ABC-404"))
    assert result.outcome == "not_found"
    assert result.incident is None
    assert result.error is None


def test_incident_service_failure_returns_typed_fallback(monkeypatch) -> None:
    from graph import incident_tool_adapter

    async def fake_service_error(tool_name, arguments):
        raise ConnectionError("private infrastructure detail")

    monkeypatch.setattr(incident_tool_adapter, "_async_call_mcp_tool", fake_service_error)
    result = incident_tool_adapter.lookup_incident(IncidentToolInput(ticket_id="ABC-500"))
    assert result.outcome == "service_error"
    assert result.incident is None
    assert result.error == "service_error"


def test_retrieval_failure_produces_safe_no_context_response(monkeypatch) -> None:
    import graph.nodes as nodes

    def fail_retrieval(*args, **kwargs):
        raise ConnectionError("gateway DNS is unavailable")

    monkeypatch.setattr(nodes, "retrieve", fail_retrieval)
    state = {
        "question": "¿Cuál es el protocolo de residuos?",
        "context": [],
        "answer": "",
        "trace_id": "test-retrieval-failure",
        "route": "rag_only",
    }

    update = retrieve_node(state)
    assert update["context"] == []
    assert update["retrieval_error"] == "ConnectionError"
    state.update(update)
    assert no_context_node(state)["answer"].startswith("No pude consultar el servicio")


def test_mixed_request_keeps_confirmed_incident_if_rag_fails(monkeypatch) -> None:
    import graph.nodes as nodes

    def fail_generation(*args, **kwargs):
        raise ConnectionError("gateway DNS is unavailable")

    monkeypatch.setattr(nodes, "generate_answer_with_memory", fail_generation)
    state = {
        "question": "estado del ticket ABC-123 y procedimiento de resolución",
        "context": [],
        "answer": "",
        "trace_id": "test-mixed-failure",
        "route": "incident_then_rag",
        "incident_id": "ABC-123",
        "incident": {"id": "ABC-123", "status": "open"},
        "incident_error": None,
        "retrieval_error": None,
    }

    update = generate_node(state)
    assert "estado: open" in update["answer"]
    assert "No pude completar" in update["answer"]


def test_mixed_request_skips_retrieval_after_confirmed_incident() -> None:
    state = {
        "question": "estado del ticket ABC-123 y el procedimiento",
        "context": [],
        "answer": "",
        "trace_id": "test-mixed-skip",
        "route": "incident_then_rag",
        "incident": {"id": "ABC-123", "status": "open"},
    }

    update = retrieve_node(state)
    assert update["context"] == []
    assert update["retrieval_error"] == "skipped_after_incident"
