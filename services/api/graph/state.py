from typing import NotRequired, TypedDict


class AgentState(TypedDict):
	question: str
	context: list[dict[str, object]]
	answer: str
	trace_id: str
	session_id: NotRequired[str]
	base_language: NotRequired[str]
	memory_proposal: NotRequired[dict[str, object] | None]
	sources: NotRequired[list[str]]
	route: NotRequired[str]
	incident_id: NotRequired[str | None]
	incident: NotRequired[dict[str, object] | None]
	incident_error: NotRequired[str | None]
	incidents: NotRequired[list[dict[str, object]]]
	incidents_truncated: NotRequired[bool]
	retrieval_error: NotRequired[str | None]
	pending_proposal_was_present: NotRequired[bool]
	# --- Chat en vivo (Parte 2) ---------------------------------------------
	# turn_id / user_message_id identifican el turno del asistente en curso para
	# que el canal WebSocket mapee cada token_chunk al mensaje correcto.
	turn_id: NotRequired[str]
	user_message_id: NotRequired[str]
	# Historial de la conversación (checkpoint LangGraph). Permite rehidratar el
	# hilo al reconectar con el mismo session_id/thread_id.
	history: NotRequired[list[dict[str, object]]]