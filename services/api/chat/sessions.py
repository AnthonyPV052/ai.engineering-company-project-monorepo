"""Entidad ``ChatSession`` y transcript persistente del chat en vivo — Parte 2.

Campos exigidos por el BRIEFING §3 (mismos nombres, sin ids paralelos):

- ``session_id``  — id de la sesión de chat; **también** el ``thread_id`` de
  LangGraph, para poder rehidratar la conversación al reconectar.
- ``agent_id``    — ``manager_support`` (``chat.events.AGENT_ID_MANAGER_SUPPORT``)
- ``user_id``     — el encargado de local que chatea (``sub`` del JWT)
- ``location_id`` — local sobre el que pregunta
- ``status``      — ``active`` | ``interrupted`` | ``closed``
- ``created_at``  — ISO-8601 UTC

El transcript es una lista de mensajes::

    {"message_id": "msg_…", "role": "user"|"assistant", "content": "…",
     "status": "streaming"|"interrupted"|"completed"|"failed",
     "sequence": 3, "created_at": "…"}

``sequence`` en un **mensaje** es su posición en la conversación. En un
``token_chunk`` el campo ``sequence`` es el índice del token dentro de la
generación (ver ``chat.events.token_chunk_payload``).

Persistencia: un fichero JSON por sesión bajo ``CHAT_SESSION_DIR`` (por defecto
``services/api/snapshots/chat-sessions``). El estado en memoria es la fuente de
verdad durante la vida del proceso; el fichero permite que un reinicio del
proceso no borre la conversación. Además se consulta el checkpoint de LangGraph
para recuperar la traza del agente si el fichero no existiera (ver
``rehydrate_from_checkpoint``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chat.events import (
    AGENT_ID_MANAGER_SUPPORT,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_STATUS_COMPLETED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INTERRUPTED,
    MESSAGE_STATUS_STREAMING,
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_CLOSED,
    SESSION_STATUS_INTERRUPTED,
)

logger = logging.getLogger("api.chat.sessions")

_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "snapshots" / "chat-sessions"


def _session_dir() -> Path:
    directory = Path(os.getenv("CHAT_SESSION_DIR", _DEFAULT_DIR))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ChatSessionStore:
    """Almacén de sesiones + transcript, seguro entre hilos."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        #: Sesión cuyo turno del asistente está generándose ahora mismo.
        self._active_generation: dict[str, str] = {}

    # -- ciclo de vida -----------------------------------------------------

    def get_or_create(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        """Devuelve la sesión existente (rehidratándola) o crea una nueva.

        Un ``session_id`` ya conocido **nunca** se reinicia: el transcript, los
        mensajes interrumpidos y el estado se conservan tal cual, que es lo que
        permite reconectar sin perder la conversación.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = self._load_from_disk(session_id)
            if session is None:
                session = {
                    "session_id": session_id,
                    "agent_id": AGENT_ID_MANAGER_SUPPORT,
                    "user_id": user_id,
                    "location_id": location_id,
                    "status": SESSION_STATUS_ACTIVE,
                    "created_at": _now(),
                    "messages": [],
                }
            else:
                # Datos de contexto que puede aportar el handshake actual.
                if user_id:
                    session["user_id"] = user_id
                if location_id:
                    session["location_id"] = location_id
                if session["status"] == SESSION_STATUS_CLOSED:
                    session["status"] = SESSION_STATUS_ACTIVE
            self._sessions[session_id] = session
            self._save(session)
            return session

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = self._load_from_disk(session_id)
                if session is not None:
                    self._sessions[session_id] = session
            return session

    def set_status(self, session_id: str, status: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session["status"] = status
            self._save(session)

    # -- mensajes ----------------------------------------------------------

    def append_user_message(self, session_id: str, text: str) -> dict[str, Any]:
        with self._lock:
            session = self._require(session_id)
            message = {
                "message_id": _new_id("msg"),
                "role": MESSAGE_ROLE_USER,
                "content": text,
                "status": MESSAGE_STATUS_COMPLETED,
                "sequence": len(session["messages"]),
                "created_at": _now(),
            }
            session["messages"].append(message)
            session["status"] = SESSION_STATUS_ACTIVE
            self._save(session)
            return message

    def start_assistant_message(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require(session_id)
            message = {
                "message_id": _new_id("msg"),
                "role": MESSAGE_ROLE_ASSISTANT,
                "content": "",
                "status": MESSAGE_STATUS_STREAMING,
                "sequence": len(session["messages"]),
                "created_at": _now(),
            }
            session["messages"].append(message)
            self._active_generation[session_id] = message["message_id"]
            self._save(session)
            return message

    def append_token(self, session_id: str, message_id: str, token: str) -> None:
        with self._lock:
            message = self._find_message(session_id, message_id)
            if message is None or message["status"] != MESSAGE_STATUS_STREAMING:
                return
            message["content"] += token

    def finish_message(
        self, session_id: str, message_id: str, status: str, *, content: str | None = None
    ) -> dict[str, Any] | None:
        """Cierra un mensaje del asistente.

        ``content`` sólo se usa para completar el texto final (por ejemplo el
        sufijo de confirmación de memoria que el modelo no generó). Nunca vacía
        lo ya mostrado: un mensaje interrumpido conserva sus tokens.
        """
        with self._lock:
            message = self._find_message(session_id, message_id)
            if message is None:
                return None
            if content is not None and len(content) > len(message["content"]):
                message["content"] = content
            message["status"] = status
            session = self._sessions.get(session_id)
            if session is not None:
                if self._active_generation.get(session_id) == message_id:
                    self._active_generation.pop(session_id, None)
                if status == MESSAGE_STATUS_INTERRUPTED:
                    session["status"] = SESSION_STATUS_INTERRUPTED
                elif status == MESSAGE_STATUS_COMPLETED:
                    session["status"] = SESSION_STATUS_ACTIVE
                self._save(session)
            return message

    def active_message_id(self, session_id: str) -> str | None:
        with self._lock:
            return self._active_generation.get(session_id)

    # -- rehidratación -----------------------------------------------------

    def snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self.get(session_id)
            if session is None:
                return None
            # Copia profunda barata para no exponer estructuras mutables.
            return json.loads(json.dumps(session))

    # -- internos ----------------------------------------------------------

    def _require(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Sesión de chat inexistente: {session_id}")
        return session

    def _find_message(self, session_id: str, message_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        for message in session["messages"]:
            if message["message_id"] == message_id:
                return message
        return None

    def _file_path(self, session_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in session_id)
        return _session_dir() / f"{safe}.json"

    def _load_from_disk(self, session_id: str) -> dict[str, Any] | None:
        path = self._file_path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Sesión de chat ilegible en disco: %s", path, exc_info=True)
            return None

    def _save(self, session: dict[str, Any]) -> None:
        path = self._file_path(session["session_id"])
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            # La persistencia es best-effort: nunca debe tumbar el chat.
            logger.warning("No se pudo persistir la sesión %s", session["session_id"], exc_info=True)


#: Instancia única por proceso (worker único en Compose, igual que el SSE).
store = ChatSessionStore()


def rehydrate_from_checkpoint(session_id: str) -> list[dict[str, Any]]:
    """Reconstruye un transcript desde el checkpoint de LangGraph.

    Sólo se usa cuando el fichero de sesión no existe (proceso reiniciado sin
    volumen, o sesión iniciada en otro worker). El grafo guarda el historial de
    turnos en ``state["history"]``, así que podemos recuperar la conversación
    sin volver a llamar al modelo.
    """
    try:
        from graph.workflow import graph  # import diferido: evita ciclos
    except Exception:  # pragma: no cover - grafo no disponible
        logger.warning("Grafo no disponible para rehidratar %s", session_id, exc_info=True)
        return []

    try:
        state = graph.get_state({"configurable": {"thread_id": session_id}})
    except Exception:  # pragma: no cover - checkpointer no disponible
        logger.warning("Checkpoint ilegible para %s", session_id, exc_info=True)
        return []

    values = getattr(state, "values", None) or {}
    history = values.get("history") or []
    messages: list[dict[str, Any]] = []
    for index, turn in enumerate(history):
        if not isinstance(turn, dict):
            continue
        question = turn.get("question")
        answer = turn.get("answer")
        created_at = turn.get("created_at") or _now()
        if question:
            messages.append(
                {
                    "message_id": turn.get("user_message_id") or _new_id("msg"),
                    "role": MESSAGE_ROLE_USER,
                    "content": question,
                    "status": MESSAGE_STATUS_COMPLETED,
                    "sequence": len(messages),
                    "created_at": created_at,
                }
            )
        if answer:
            messages.append(
                {
                    "message_id": turn.get("assistant_message_id") or _new_id("msg"),
                    "role": MESSAGE_ROLE_ASSISTANT,
                    "content": answer,
                    "status": turn.get("status") or MESSAGE_STATUS_COMPLETED,
                    "sequence": len(messages),
                    "created_at": created_at,
                }
            )
    if messages and len(messages) != len(history) * 2:
        logger.info("Rehidratación parcial desde checkpoint para %s (%d mensajes)", session_id, len(messages))
    return messages


def ensure_session(
    session_id: str, *, user_id: str | None = None, location_id: str | None = None
) -> dict[str, Any]:
    """Devuelve la sesión, rehidratando desde el checkpoint si hace falta."""
    existing = store.get(session_id)
    if existing is not None and existing.get("messages"):
        return store.get_or_create(session_id, user_id=user_id, location_id=location_id)

    session = store.get_or_create(session_id, user_id=user_id, location_id=location_id)
    if not session["messages"]:
        restored = rehydrate_from_checkpoint(session_id)
        if restored:
            session["messages"] = restored
            logger.info("Sesión %s rehidratada desde checkpoint (%d mensajes)", session_id, len(restored))
            with store._lock:  # noqa: SLF001 - misma capa de persistencia
                store._save(session)  # noqa: SLF001
    return session


__all__ = [
    "ChatSessionStore",
    "ensure_session",
    "rehydrate_from_checkpoint",
    "store",
]
