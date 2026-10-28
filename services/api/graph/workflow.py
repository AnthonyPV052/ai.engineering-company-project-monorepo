from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState
from graph.nodes import (
    source_router_node,
    incident_tool_node,
    incident_answer_node,
    retrieve_node,
    generate_node,
    no_context_node,
)
from graph.routing import route_context, route_after_incident

builder = StateGraph(AgentState)

builder.add_node("source_router", source_router_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("incident_tool", incident_tool_node)
builder.add_node("incident_answer", incident_answer_node)
builder.add_node("generate", generate_node)
builder.add_node("no_context", no_context_node)

builder.add_edge(START, "source_router")
builder.add_conditional_edges(
    "source_router",
    lambda state: state["route"],
    {
        "rag_only": "retrieve",
        "incident_only": "incident_tool",
        "incident_then_rag": "incident_tool",
    },
)
builder.add_conditional_edges(
    "incident_tool",
    route_after_incident,
    {"retrieve": "retrieve", "incident_answer": "incident_answer"},
)

builder.add_conditional_edges(
    "retrieve",
    route_context,
    {
        "generate": "generate",
        "no_context": "no_context",
    },
)

builder.add_edge("generate", END)
builder.add_edge("no_context", END)
builder.add_edge("incident_answer", END)

try:
    # La compilación ocurre al importar el servicio y valida la estructura
    # antes de permitir cualquier ejecución.
    graph = builder.compile(checkpointer=MemorySaver())
except Exception as exc:
    raise RuntimeError(f"Error estructural al compilar el grafo del agente: {exc}") from exc