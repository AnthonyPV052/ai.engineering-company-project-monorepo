"""Contrato de eventos WebSocket del chat en vivo — Parte 2.

Este módulo define el vocabulario EXACTO del chat con el *Manager support agent*
(ver ``BRIEFING.md`` §4). No reutiliza los esquemas RFP/SSE de la Parte 1:
aquí no existen ``ticket_id``, ``departments_needed`` ni ``rfp_ticket_created``.

Envoltorio común (un frame de texto por evento)::

    {"event": "token_chunk", "data": {"session_id": "chat_0044", ...}}

Eventos cliente → servidor
--------------------------
- ``auth``               ``{"token": "<jwt>"}`` (solo si no se envió ``?token=``)
- ``user_message``       ``{"session_id": "...", "text": "..."}``
- ``interrupt_requested`` ``{"session_id": "...", "new_input": "..."}``
- ``ping``               ``{}`` → el servidor responde ``pong``

Eventos servidor → cliente
--------------------------
- ``session_snapshot``      historial completo (rehidratación al reconectar)
- ``generation_started``    abre un turno del asistente y anuncia ``message_id``
- ``token_chunk``           fragmento de respuesta (``token`` + ``sequence``)
- ``generation_interrupted`` el mensaje parcial queda marcado ``interrupted``
- ``generation_completed``  el turno terminó normalmente
- ``generation_failed``     el turno falló (conserva parciales mostrados)
- ``user_message``          eco canónico del turno del usuario aceptado
- ``error``                 error de protocolo (no cierra necesariamente)

Los eventos ``generation_*``/``token_chunk`` incluyen ``agent_id`` para dejar
explícito que el productor es ``manager_support``; ``token_chunk`` incluye
además ``message_id`` para que el cliente pueda ensamblar el mensaje aunque se
reconecte en mitad del stream (campo aditivo, no sustituye a ``sequence``).
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Identidad del agente (BRIEFING §3)
# ---------------------------------------------------------------------------

AGENT_ID_MANAGER_SUPPORT = "manager_support"

# Estados de la entidad ChatSession (BRIEFING §3).
SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_INTERRUPTED = "interrupted"
SESSION_STATUS_CLOSED = "closed"

CHAT_SESSION_STATUSES = (
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_INTERRUPTED,
    SESSION_STATUS_CLOSED,
)

# Estados de un mensaje del asistente dentro de la sesión.
MESSAGE_STATUS_STREAMING = "streaming"
MESSAGE_STATUS_INTERRUPTED = "interrupted"
MESSAGE_STATUS_COMPLETED = "completed"
MESSAGE_STATUS_FAILED = "failed"

MESSAGE_ROLE_USER = "user"
MESSAGE_ROLE_ASSISTANT = "assistant"

# ---------------------------------------------------------------------------
# Nombres de evento
# ---------------------------------------------------------------------------

# Cliente → servidor
CHAT_EVENT_AUTH = "auth"
CHAT_EVENT_USER_MESSAGE = "user_message"
CHAT_EVENT_INTERRUPT_REQUESTED = "interrupt_requested"
CHAT_EVENT_PING = "ping"

# Servidor → cliente
CHAT_EVENT_SESSION_SNAPSHOT = "session_snapshot"
CHAT_EVENT_GENERATION_STARTED = "generation_started"
CHAT_EVENT_TOKEN_CHUNK = "token_chunk"
CHAT_EVENT_GENERATION_INTERRUPTED = "generation_interrupted"
CHAT_EVENT_GENERATION_COMPLETED = "generation_completed"
CHAT_EVENT_GENERATION_FAILED = "generation_failed"
CHAT_EVENT_PONG = "pong"
CHAT_EVENT_ERROR = "error"

#: Eventos que un cliente puede enviar.
CLIENT_EVENTS = frozenset(
    {
        CHAT_EVENT_AUTH,
        CHAT_EVENT_USER_MESSAGE,
        CHAT_EVENT_INTERRUPT_REQUESTED,
        CHAT_EVENT_PING,
    }
)

#: Eventos que el servidor puede publicar en el canal de la sesión.
SERVER_EVENTS = frozenset(
    {
        CHAT_EVENT_SESSION_SNAPSHOT,
        CHAT_EVENT_GENERATION_STARTED,
        CHAT_EVENT_TOKEN_CHUNK,
        CHAT_EVENT_GENERATION_INTERRUPTED,
        CHAT_EVENT_GENERATION_COMPLETED,
        CHAT_EVENT_GENERATION_FAILED,
        CHAT_EVENT_USER_MESSAGE,
        CHAT_EVENT_PONG,
        CHAT_EVENT_ERROR,
    }
)

# ---------------------------------------------------------------------------
# Códigos de cierre WebSocket (rango de aplicación 4000-4999)
# ---------------------------------------------------------------------------

WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_BAD_REQUEST = 4400
WS_CLOSE_FORBIDDEN = 4403
WS_CLOSE_SESSION_CLOSED = 4404


class ChatProtocolError(ValueError):
    """Frame de cliente inválido (evento desconocido, payload incompleto…)."""


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


def encode_event(event: str, data: dict[str, Any] | None = None) -> str:
    """Serializa un evento al wire: ``{"event": ..., "data": {...}}``."""
    if event not in SERVER_EVENTS:
        raise ValueError(f"Evento de servidor desconocido: {event!r}")
    payload = {"event": event, "data": dict(data or {})}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_client_frame(raw: str) -> tuple[str, dict[str, Any]]:
    """Parsea un frame de texto del cliente.

    Devuelve ``(event, data)``. Lanza ``ChatProtocolError`` si el frame no es
    JSON, no trae un nombre de evento soportado o ``data`` no es un objeto.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ChatProtocolError("El frame debe ser JSON válido.") from exc

    if not isinstance(payload, dict):
        raise ChatProtocolError("El frame debe ser un objeto JSON.")

    event = payload.get("event")
    if not isinstance(event, str) or not event:
        raise ChatProtocolError("Falta el campo 'event'.")
    if event not in CLIENT_EVENTS:
        raise ChatProtocolError(f"Evento no soportado: {event!r}")

    data = payload.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ChatProtocolError("El campo 'data' debe ser un objeto JSON.")
    return event, data


# ---------------------------------------------------------------------------
# Constructores de payload (una sola fuente de verdad para backend y tests)
# ---------------------------------------------------------------------------


def token_chunk_payload(
    *,
    session_id: str,
    token: str,
    sequence: int,
    message_id: str,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_id": AGENT_ID_MANAGER_SUPPORT,
        "message_id": message_id,
        "token": token,
        "sequence": sequence,
    }


def generation_started_payload(
    *, session_id: str, message_id: str
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_id": AGENT_ID_MANAGER_SUPPORT,
        "message_id": message_id,
        "status": MESSAGE_STATUS_STREAMING,
    }


def generation_interrupted_payload(
    *, session_id: str, message_id: str, new_input: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "agent_id": AGENT_ID_MANAGER_SUPPORT,
        "message_id": message_id,
        "status": MESSAGE_STATUS_INTERRUPTED,
    }
    if new_input is not None:
        payload["new_input"] = new_input
    return payload


def generation_completed_payload(
    *, session_id: str, message_id: str, content_length: int
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_id": AGENT_ID_MANAGER_SUPPORT,
        "message_id": message_id,
        "status": MESSAGE_STATUS_COMPLETED,
        "content_length": content_length,
    }


def generation_failed_payload(
    *, session_id: str, message_id: str, reason: str
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_id": AGENT_ID_MANAGER_SUPPORT,
        "message_id": message_id,
        "status": MESSAGE_STATUS_FAILED,
        "reason": reason,
    }


def user_message_payload(
    *, session_id: str, message_id: str, text: str
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "message_id": message_id,
        "text": text,
    }


def interrupt_requested_payload(
    *, session_id: str, message_id: str | None, new_input: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"session_id": session_id}
    if message_id is not None:
        payload["message_id"] = message_id
    if new_input is not None:
        payload["new_input"] = new_input
    return payload


def session_snapshot_payload(session: dict[str, Any]) -> dict[str, Any]:
    """Payload de rehidratación.

    Contiene los campos de la entidad ``ChatSession`` del BRIEFING y el
    historial de mensajes con sus estados (``interrupted`` incluidos).
    """
    return {
        "session_id": session["session_id"],
        "agent_id": session["agent_id"],
        "user_id": session.get("user_id"),
        "location_id": session.get("location_id"),
        "status": session["status"],
        "created_at": session["created_at"],
        "thread_id": session["session_id"],  # LangGraph: thread_id == session_id
        "messages": session.get("messages", []),
    }


def error_payload(*, session_id: str | None, message: str, code: str = "protocol_error") -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


__all__ = [
    "AGENT_ID_MANAGER_SUPPORT",
    "CHAT_EVENT_AUTH",
    "CHAT_EVENT_ERROR",
    "CHAT_EVENT_GENERATION_COMPLETED",
    "CHAT_EVENT_GENERATION_FAILED",
    "CHAT_EVENT_GENERATION_INTERRUPTED",
    "CHAT_EVENT_GENERATION_STARTED",
    "CHAT_EVENT_INTERRUPT_REQUESTED",
    "CHAT_EVENT_PING",
    "CHAT_EVENT_PONG",
    "CHAT_EVENT_SESSION_SNAPSHOT",
    "CHAT_EVENT_TOKEN_CHUNK",
    "CHAT_EVENT_USER_MESSAGE",
    "CHAT_SESSION_STATUSES",
    "CLIENT_EVENTS",
    "ChatProtocolError",
    "MESSAGE_ROLE_ASSISTANT",
    "MESSAGE_ROLE_USER",
    "MESSAGE_STATUS_COMPLETED",
    "MESSAGE_STATUS_FAILED",
    "MESSAGE_STATUS_INTERRUPTED",
    "MESSAGE_STATUS_STREAMING",
    "SERVER_EVENTS",
    "SESSION_STATUS_ACTIVE",
    "SESSION_STATUS_CLOSED",
    "SESSION_STATUS_INTERRUPTED",
    "WS_CLOSE_BAD_REQUEST",
    "WS_CLOSE_FORBIDDEN",
    "WS_CLOSE_SESSION_CLOSED",
    "WS_CLOSE_UNAUTHORIZED",
    "decode_client_frame",
    "encode_event",
    "error_payload",
    "generation_completed_payload",
    "generation_failed_payload",
    "generation_interrupted_payload",
    "generation_started_payload",
    "interrupt_requested_payload",
    "session_snapshot_payload",
    "token_chunk_payload",
    "user_message_payload",
]
