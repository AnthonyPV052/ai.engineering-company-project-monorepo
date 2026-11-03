"""Tests del chat en vivo por WebSocket (Parte 2 — Sistemas en Tiempo Real).

Cubre, sobre el wire real y sobre el gestor de turnos:

1. **Contrato de eventos** — ``token_chunk``, ``generation_started``,
   ``generation_interrupted``, ``generation_completed``, ``session_snapshot``,
   ``user_message``; y los códigos de cierre de aplicación.
2. **Autenticación** — sin JWT el servidor cierra con ``4401`` antes de enviar
   ningún evento de chat; con JWT (``?token=`` o frame ``auth``) se acepta.
3. **Streaming token a token** — cada ``token_chunk`` trae ``session_id``,
   ``message_id``, ``token`` y ``sequence`` incrementales, y la concatenación
   reproduce la respuesta del agente.
4. **Interrupción a mitad de respuesta** — al abortar dejan de llegar
   ``token_chunk`` de esa generación, el mensaje parcial queda ``interrupted``
   con el texto ya mostrado, y el siguiente turno es uno **nuevo** con el
   ``new_input`` del cliente (el interrumpido no se borra ni se sobrescribe).
5. **Reconexión con el mismo ``session_id``** — ``session_snapshot`` devuelve
   el historial previo (incluido el mensaje interrumpido) en lugar de un chat
   vacío; se rehidrata desde el checkpoint de LangGraph si falta el fichero.
6. **Pub/sub desacoplado** — el productor publica en ``chat.<session_id>`` y
   dos consumidores independientes reciben el mismo evento.

Estrategia (sin pytest-asyncio, igual que ``test_rfp_sse.py``):

- El grafo real se sustituye por uno equivalente de LangGraph (mismo
  ``AgentState``, mismo checkpointer ``MemorySaver``, mismos ``stream_mode``)
  cuyo nodo emite tokens guionizados y honra ``AbortSignal``. Así se prueba la
  integración real con LangGraph (``custom``/``values``, ``update_state``,
  checkpoint) sin llamar al modelo.
- Los tests de wire abren un uvicorn real en un hilo y hablan con el cliente
  ``websockets`` (TCP real, no dicts abstractos).

Verificación manual: docs/chat-websocket.es.md.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.setdefault("DATABASE_URL", "sqlite:///test_chat_ws.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-chat-ws")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")

import anyio
import pytest
import uvicorn
from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

import chat.generation as generation_module
import chat.sessions as sessions_module
from chat import events
from chat.generation import ChatGenerationManager
from chat.pubsub import ChatPubSub, channel_for
from chat.sessions import ChatSessionStore, rehydrate_from_checkpoint
from chat.ws import router as chat_router
from generation_control import GenerationAborted
from graph.state import AgentState
from graph.streaming import emit_token, turn_controls
from langgraph.config import get_config
from langgraph.config import get_config
from partial_json import AnswerFieldExtractor, JsonAnswerStreamer, extract_answer_from_partial
from security import create_access_token

MOCK_USER = {"id": "manager-001", "email": "encargado@brasaland.io", "is_active": True, "role": "user"}

#: Guion de tokens por pregunta. Las preguntas no listadas usan ``DEFAULT_TOKENS``.
SCRIPT: dict[str, list[str]] = {}
DEFAULT_TOKENS = ["Respuesta ", "por ", "defecto."]
#: Pausa entre tokens (s) para poder interrumpir realmente a mitad de stream.
STREAM_DELAY = 0.06


# ===================================================================
# Grafo de prueba (misma forma que el de producción)
# ===================================================================


def _fake_generate_node(state: AgentState) -> dict[str, Any]:
    """Nodo equivalente a ``generate``: emite tokens y honra el aborto."""
    signal, streaming = turn_controls()
    tokens = SCRIPT.get(state["question"], DEFAULT_TOKENS)
    emitted: list[str] = []
    for token in tokens:
        if signal is not None:
            signal.raise_if_aborted()
        if streaming:
            emit_token(token)
        emitted.append(token)
        time.sleep(STREAM_DELAY)
    return {"answer": "".join(emitted)}


def _build_fake_graph():
    builder = StateGraph(AgentState)
    builder.add_node("generate", _fake_generate_node)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", END)
    return builder.compile(checkpointer=MemorySaver())


FAKE_GRAPH = _build_fake_graph()


def _install_stub_modules() -> None:
    """Sustituye las dos dependencias que arrastran los modelos ``JSONB``.

    ``graph.workflow`` importa ``graph.nodes`` → modelos de memoria con columnas
    ``JSONB``, que el ``create_all`` del conftest (SQLite) no puede compilar;
    ``agent_turn_context`` importa ``memory.store``/``memory.classifier`` y
    arrastra los mismos modelos.

    Ninguno de los dos es objeto de este test: ``chat.generation`` y
    ``chat.sessions`` los importan de forma diferida, así que basta con dejar
    los módulos resueltos en ``sys.modules``. El grafo de prueba tiene la misma
    forma que el de producción (``AgentState`` + checkpointer ``MemorySaver``),
    de modo que el resto del camino sí es el código real.
    """
    workflow_stub = types.ModuleType("graph.workflow")
    workflow_stub.graph = FAKE_GRAPH  # type: ignore[attr-defined]
    sys.modules["graph.workflow"] = workflow_stub

    context_stub = types.ModuleType("agent_turn_context")
    context_stub.prepare_pending_proposal = lambda session_id, question: (False, None)  # type: ignore[attr-defined]
    sys.modules["agent_turn_context"] = context_stub


_install_stub_modules()


# ===================================================================
# Aislamiento entre tests
# ===================================================================


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Grafo, almacén de sesiones, hub y trazas aislados por test."""
    # Checkpointer nuevo por test: el historial de un test no se filtra al otro.
    fresh_graph = _build_fake_graph()
    sys.modules["graph.workflow"].graph = fresh_graph  # type: ignore[attr-defined]
    monkeypatch.setenv("CHAT_SESSION_DIR", str(tmp_path / "chat-sessions"))
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path / "agent-traces"))
    # Un store nuevo por test evita que las sesiones de un test se filtren.
    fresh_store = ChatSessionStore()
    monkeypatch.setattr(sessions_module, "store", fresh_store)
    monkeypatch.setattr(generation_module, "store", fresh_store)
    # El WS resuelve el usuario con ``users_service`` (misma pieza que la API).
    monkeypatch.setattr(
        "users_service.get_user_by_id",
        lambda user_id: dict(MOCK_USER) if user_id == MOCK_USER["id"] else None,
    )
    SCRIPT.clear()
    yield


# ===================================================================
# 1) Contrato de eventos
# ===================================================================


class TestEventContract:
    """El vocabulario del canal es explícito y estable (BRIEFING §4)."""

    def test_token_chunk_payload_shape(self) -> None:
        payload = events.token_chunk_payload(
            session_id="chat_0044", token="Para", sequence=12, message_id="msg_0090"
        )
        assert payload == {
            "session_id": "chat_0044",
            "agent_id": "manager_support",
            "message_id": "msg_0090",
            "token": "Para",
            "sequence": 12,
        }

    def test_generation_started_and_completed(self) -> None:
        started = events.generation_started_payload(session_id="s1", message_id="m1")
        assert started["status"] == events.MESSAGE_STATUS_STREAMING
        assert started["agent_id"] == events.AGENT_ID_MANAGER_SUPPORT

        completed = events.generation_completed_payload(
            session_id="s1", message_id="m1", content_length=17
        )
        assert completed["status"] == events.MESSAGE_STATUS_COMPLETED
        assert completed["content_length"] == 17

    def test_generation_interrupted_marks_status(self) -> None:
        payload = events.generation_interrupted_payload(
            session_id="s1", message_id="m1", new_input="espera, era Miami"
        )
        assert payload["status"] == events.MESSAGE_STATUS_INTERRUPTED
        assert payload["new_input"] == "espera, era Miami"

    def test_wire_frame_is_event_data_envelope(self) -> None:
        raw = events.encode_event(
            events.CHAT_EVENT_PONG, {"session_id": "chat_0044"}
        )
        assert json.loads(raw) == {"event": "pong", "data": {"session_id": "chat_0044"}}

    def test_encode_rejects_unknown_server_event(self) -> None:
        with pytest.raises(ValueError):
            events.encode_event("rfp_ticket_created", {})

    def test_decode_client_frame_accepts_known_events(self) -> None:
        event, data = events.decode_client_frame(
            '{"event":"user_message","data":{"text":"hola"}}'
        )
        assert event == events.CHAT_EVENT_USER_MESSAGE
        assert data == {"text": "hola"}

    def test_decode_client_frame_rejects_part1_payloads(self) -> None:
        """Un evento RFP de la Parte 1 no es un evento de chat válido."""
        with pytest.raises(events.ChatProtocolError):
            events.decode_client_frame('{"event":"rfp_ticket_created","data":{}}')

    def test_decode_client_frame_rejects_broken_json(self) -> None:
        with pytest.raises(events.ChatProtocolError):
            events.decode_client_frame("not json")

    def test_close_codes_are_application_range(self) -> None:
        assert events.WS_CLOSE_UNAUTHORIZED == 4401
        assert events.WS_CLOSE_BAD_REQUEST == 4400
        assert events.WS_CLOSE_SESSION_CLOSED == 4404

    def test_session_snapshot_uses_briefing_fields(self) -> None:
        payload = events.session_snapshot_payload(
            {
                "session_id": "chat_0044",
                "agent_id": events.AGENT_ID_MANAGER_SUPPORT,
                "user_id": "manager-001",
                "location_id": "brasaland-miami",
                "status": events.SESSION_STATUS_INTERRUPTED,
                "created_at": "2026-01-01T00:00:00+00:00",
                "messages": [],
            }
        )
        assert payload["thread_id"] == "chat_0044"
        assert payload["status"] == "interrupted"
        assert payload["location_id"] == "brasaland-miami"


class TestPartialJsonStreaming:
    """El agente responde JSON: sólo el texto de ``answer`` viaja como token."""

    def test_only_answer_field_is_streamed(self) -> None:
        chunks = [
            '{"answer": "La Ensalada Tro',
            'pical tiene nueces.", "propuesta_memoria":',
            ' {"should_store": false}}',
        ]
        emitted: list[str] = []
        streamer = JsonAnswerStreamer(emitted.append)
        for chunk in chunks:
            streamer.push(chunk)
        assert "".join(emitted) == "La Ensalada Tropical tiene nueces."
        assert streamer.emitted_any

    def test_extract_answer_from_partial_matches_json(self) -> None:
        raw = '{"answer":"A\\nB\\u00e9","propuesta_memoria":{"should_store":false}}'
        assert extract_answer_from_partial([raw]) == json.loads(raw)["answer"]

    def test_extractor_handles_char_by_char_feed(self) -> None:
        raw = '{"answer":"Hola, mundo."}'
        extractor = AnswerFieldExtractor()
        text = "".join(extractor.feed(char) for char in raw)
        assert text == "Hola, mundo."
        assert extractor.result() == "Hola, mundo."


# ===================================================================
# 2) Pub/sub desacoplado
# ===================================================================


class TestPubSub:
    """El productor publica en ``chat.<session_id>``; los consumidores escuchan."""

    def test_channel_naming(self) -> None:
        assert channel_for("chat_0044") == "chat.chat_0044"

    def test_two_consumers_receive_same_event(self) -> None:
        async def scenario() -> tuple[dict, dict]:
            pubsub = ChatPubSub()
            first = pubsub.subscribe("chat_0044")
            second = pubsub.subscribe("chat_0044")
            delivered = pubsub.publish(
                "chat_0044", events.CHAT_EVENT_TOKEN_CHUNK, {"token": "Para"}
            )
            assert delivered == 2
            return first.get_nowait(), second.get_nowait()

        one, two = anyio.run(scenario)
        assert one == two
        assert one["event"] == events.CHAT_EVENT_TOKEN_CHUNK

    def test_publish_without_subscribers_does_not_fail(self) -> None:
        """La generación nunca depende de que haya un WebSocket escuchando."""
        pubsub = ChatPubSub()
        assert pubsub.publish("chat_0044", events.CHAT_EVENT_TOKEN_CHUNK, {}) == 0

    def test_unsubscribe_stops_delivery(self) -> None:
        async def scenario() -> int:
            pubsub = ChatPubSub()
            queue = pubsub.subscribe("s1")
            pubsub.unsubscribe("s1", queue)
            pubsub.publish("s1", events.CHAT_EVENT_TOKEN_CHUNK, {})
            return queue.qsize()

        assert anyio.run(scenario) == 0


# ===================================================================
# 3) Gestor de turnos (streaming, abort, nuevo turno)
# ===================================================================


async def _collect_until(queue, predicate, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Acumula eventos del canal hasta que ``predicate(evento)`` sea cierto."""
    import asyncio

    collected: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.01, deadline - time.monotonic())
        try:
            event = await asyncio.wait_for(queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        collected.append(event)
        if predicate(event):
            return collected
    raise AssertionError(f"No se alcanzó el evento esperado. Recibidos: {collected}")


class TestGenerationManager:
    """Turnos del agente: tokens, interrupción y arranque del turno siguiente."""

    def test_token_chunks_stream_with_increasing_sequence(self) -> None:
        SCRIPT["¿Qué alergenos tiene la ensalada?"] = ["La ", "Ensalada ", "Tropical ", "tiene ", "nueces."]

        async def scenario() -> list[dict[str, Any]]:
            from chat.pubsub import hub

            manager = ChatGenerationManager()
            queue = hub.subscribe("chat_1000")
            await manager.start_turn("chat_1000", "¿Qué alergenos tiene la ensalada?")
            events_seen = await _collect_until(
                queue, lambda e: e["event"] == events.CHAT_EVENT_GENERATION_COMPLETED
            )
            await manager.wait_idle("chat_1000")
            hub.unsubscribe("chat_1000", queue)
            return events_seen

        events_seen = anyio.run(scenario)
        names = [event["event"] for event in events_seen]
        assert names[0] == events.CHAT_EVENT_USER_MESSAGE
        assert events.CHAT_EVENT_GENERATION_STARTED in names
        assert names[-1] == events.CHAT_EVENT_GENERATION_COMPLETED

        chunks = [e["data"] for e in events_seen if e["event"] == events.CHAT_EVENT_TOKEN_CHUNK]
        assert [chunk["sequence"] for chunk in chunks] == [1, 2, 3, 4, 5]
        assert {chunk["message_id"] for chunk in chunks} == {chunks[0]["message_id"]}
        assert {chunk["session_id"] for chunk in chunks} == {"chat_1000"}
        assert "".join(chunk["token"] for chunk in chunks) == "La Ensalada Tropical tiene nueces."
        assert all(chunk["agent_id"] == "manager_support" for chunk in chunks)

    def test_interrupt_stops_tokens_and_preserves_partial_message(self) -> None:
        SCRIPT["cuéntame el protocolo de residuos"] = [f"paso{i} " for i in range(40)]
        SCRIPT["espera, era el local de Miami"] = ["Claro, ", "para ", "Miami."]

        async def scenario() -> dict[str, Any]:
            import asyncio

            from chat.pubsub import hub

            manager = ChatGenerationManager()
            queue = hub.subscribe("chat_2000")
            await manager.start_turn("chat_2000", "cuéntame el protocolo de residuos")

            # Se interrumpe en cuanto llegan 3 tokens: a mitad de stream.
            seen = await _collect_until(
                queue,
                lambda e: e["event"] == events.CHAT_EVENT_TOKEN_CHUNK
                and e["data"]["sequence"] >= 3,
            )
            first_message_id = next(
                e["data"]["message_id"]
                for e in seen
                if e["event"] == events.CHAT_EVENT_GENERATION_STARTED
            )
            await manager.request_interrupt(
                "chat_2000", new_input="espera, era el local de Miami"
            )

            rest = await _collect_until(
                queue,
                lambda e: e["event"] == events.CHAT_EVENT_GENERATION_COMPLETED
                and e["data"]["message_id"] != first_message_id,
            )
            await manager.wait_idle("chat_2000")
            hub.unsubscribe("chat_2000", queue)
            return {
                "seen": seen,
                "rest": rest,
                "first_message_id": first_message_id,
                "snapshot": generation_module.store.snapshot("chat_2000"),
            }

        result = anyio.run(scenario)
        first_message_id = result["first_message_id"]
        rest = result["rest"]
        all_events = result["seen"] + rest

        interrupted = [
            e for e in all_events if e["event"] == events.CHAT_EVENT_GENERATION_INTERRUPTED
        ]
        assert len(interrupted) == 1
        assert interrupted[0]["data"]["message_id"] == first_message_id
        assert interrupted[0]["data"]["status"] == events.MESSAGE_STATUS_INTERRUPTED

        # No hay más token_chunk de la generación abortada después del cierre.
        index_interrupt = all_events.index(interrupted[0])
        after = [
            e
            for e in all_events[index_interrupt:]
            if e["event"] == events.CHAT_EVENT_TOKEN_CHUNK
            and e["data"]["message_id"] == first_message_id
        ]
        assert after == [], f"llegaron tokens tras la interrupción: {after}"

        # La generación se detuvo de verdad (no se emitieron los 40 tokens).
        first_tokens = [
            e["data"]["token"]
            for e in all_events
            if e["event"] == events.CHAT_EVENT_TOKEN_CHUNK
            and e["data"]["message_id"] == first_message_id
        ]
        assert 0 < len(first_tokens) < 40

        # El turno siguiente es NUEVO (otro message_id) y responde al new_input.
        second_tokens = [
            e["data"]
            for e in rest
            if e["event"] == events.CHAT_EVENT_TOKEN_CHUNK
            and e["data"]["message_id"] != first_message_id
        ]
        assert second_tokens, "el new_input no abrió un turno nuevo"
        assert "".join(chunk["token"] for chunk in second_tokens) == "Claro, para Miami."
        assert {chunk["sequence"] for chunk in second_tokens} == {1, 2, 3}

        # Transcript: el parcial interrumpido se conserva tal cual y no se
        # sobrescribe con la respuesta del turno nuevo.
        messages = result["snapshot"]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
        first_assistant = messages[1]
        assert first_assistant["message_id"] == first_message_id
        assert first_assistant["status"] == events.MESSAGE_STATUS_INTERRUPTED
        assert first_assistant["content"] == "".join(first_tokens)
        assert first_assistant["content"].startswith("paso0")
        assert messages[2]["content"] == "espera, era el local de Miami"
        assert messages[3]["status"] == events.MESSAGE_STATUS_COMPLETED

    def test_interrupt_without_active_generation_is_harmless(self) -> None:
        async def scenario() -> bool:
            manager = ChatGenerationManager()
            return await manager.request_interrupt("chat_3000")

        assert anyio.run(scenario) is False

    def test_new_input_without_active_generation_starts_turn(self) -> None:
        SCRIPT["hola de nuevo"] = ["Hola."]

        async def scenario() -> dict[str, Any]:
            from chat.pubsub import hub

            manager = ChatGenerationManager()
            queue = hub.subscribe("chat_3100")
            handled = await manager.request_interrupt("chat_3100", new_input="hola de nuevo")
            await _collect_until(
                queue, lambda e: e["event"] == events.CHAT_EVENT_GENERATION_COMPLETED
            )
            await manager.wait_idle("chat_3100")
            hub.unsubscribe("chat_3100", queue)
            return {
                "handled": handled,
                "snapshot": generation_module.store.snapshot("chat_3100"),
            }

        result = anyio.run(scenario)
        # Se informa como atendido: el cliente no debe recibir
        # `nothing_to_interrupt` por un mensaje que sí se está procesando.
        assert result["handled"] is True
        snapshot = result["snapshot"]
        assert [m["content"] for m in snapshot["messages"]] == ["hola de nuevo", "Hola."]


# ===================================================================
# 4) Endpoint WebSocket real (uvicorn en hilo + cliente websockets)
# ===================================================================


class _StoppableServer(uvicorn.Server):
    """Permite correr uvicorn en un hilo sin signal handlers."""

    def install_signal_handlers(self) -> None:  # pragma: no cover - sólo tests
        pass


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def ws_server():
    """App mínima con el router de chat, servida por uvicorn en un hilo."""
    app = FastAPI()
    app.include_router(chat_router)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = _StoppableServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(300):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started, "uvicorn no arrancó"
    yield f"ws://127.0.0.1:{port}/chat/ws"
    server.should_exit = True
    thread.join(timeout=5)


async def _recv_event(socket) -> tuple[str, dict[str, Any]]:
    raw = await socket.recv()
    payload = json.loads(raw)
    return payload["event"], payload["data"]


async def _recv_until(socket, name: str, *, limit: int = 500, timeout: float = 25.0) -> tuple[list, tuple[str, dict]]:
    """Lee frames hasta encontrar ``name``; devuelve (frames previos, evento)."""
    import asyncio

    collected: list[tuple[str, dict]] = []
    deadline = time.monotonic() + timeout
    while len(collected) < limit and time.monotonic() < deadline:
        remaining = max(0.01, deadline - time.monotonic())
        name_seen, data = await asyncio.wait_for(_recv_event(socket), timeout=remaining)
        if name_seen == name:
            return collected, (name_seen, data)
        collected.append((name_seen, data))
    raise AssertionError(f"No llegó el evento {name!r}. Recibidos: {collected}")


class TestWebSocketAuth:
    """Rechazo antes de cualquier evento de chat (BRIEFING §3)."""

    def test_close_4401_without_token(self, ws_server: str) -> None:
        async def scenario() -> tuple[int, list[str]]:
            async with connect(f"{ws_server}?session_id=chat_auth") as socket:
                frames: list[str] = []
                try:
                    async for raw in socket:
                        frames.append(raw)
                except ConnectionClosed:
                    pass
                return socket.close_code or 1000, frames

        code, frames = anyio.run(scenario)
        assert code == events.WS_CLOSE_UNAUTHORIZED
        # Ni un solo evento de chat antes del cierre.
        assert frames == []

    def test_invalid_token_closes_4401(self, ws_server: str) -> None:
        async def scenario() -> int:
            async with connect(f"{ws_server}?session_id=chat_bad&token=not-a-jwt") as socket:
                try:
                    async for _ in socket:
                        pass
                except ConnectionClosed:
                    pass
                return socket.close_code or 1000

        assert anyio.run(scenario) == events.WS_CLOSE_UNAUTHORIZED

    def test_missing_session_id_closes_4400(self, ws_server: str) -> None:
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> int:
            async with connect(f"{ws_server}?token={token}") as socket:
                try:
                    async for _ in socket:
                        pass
                except ConnectionClosed:
                    pass
                return socket.close_code or 1000

        assert anyio.run(scenario) == events.WS_CLOSE_BAD_REQUEST

    def test_token_in_query_is_accepted(self, ws_server: str) -> None:
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> tuple[str, dict]:
            async with connect(f"{ws_server}?session_id=chat_ok&token={token}") as socket:
                return await _recv_event(socket)

        name, data = anyio.run(scenario)
        assert name == events.CHAT_EVENT_SESSION_SNAPSHOT
        assert data["session_id"] == "chat_ok"
        assert data["agent_id"] == "manager_support"
        assert data["thread_id"] == "chat_ok"

    def test_first_auth_frame_is_accepted(self, ws_server: str) -> None:
        """Alternativa al ``?token=``: los navegadores no pueden poner headers."""
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> tuple[str, dict]:
            async with connect(f"{ws_server}?session_id=chat_frame") as socket:
                await socket.send(
                    json.dumps({"event": "auth", "data": {"token": token}})
                )
                return await _recv_event(socket)

        name, data = anyio.run(scenario)
        assert name == events.CHAT_EVENT_SESSION_SNAPSHOT
        assert data["session_id"] == "chat_frame"


class TestWebSocketChat:
    """Contrato en el wire + interrupción + reconexión."""

    def test_token_chunk_contract_over_the_wire(self, ws_server: str) -> None:
        SCRIPT["¿Qué proveedor entrega los lunes?"] = ["El ", "proveedor ", "es ", "FrescoSur."]
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> list[tuple[str, dict]]:
            async with connect(f"{ws_server}?session_id=chat_wire&token={token}") as socket:
                await _recv_event(socket)  # session_snapshot
                await socket.send(
                    json.dumps(
                        {
                            "event": events.CHAT_EVENT_USER_MESSAGE,
                            "data": {
                                "session_id": "chat_wire",
                                "text": "¿Qué proveedor entrega los lunes?",
                            },
                        }
                    )
                )
                frames, _ = await _recv_until(socket, events.CHAT_EVENT_GENERATION_COMPLETED)
                return frames

        frames = anyio.run(scenario)
        names = [name for name, _ in frames]
        assert names[0] == events.CHAT_EVENT_USER_MESSAGE
        assert names[1] == events.CHAT_EVENT_GENERATION_STARTED

        chunks = [data for name, data in frames if name == events.CHAT_EVENT_TOKEN_CHUNK]
        assert len(chunks) == 4
        assert [chunk["sequence"] for chunk in chunks] == [1, 2, 3, 4]
        assert all(chunk["session_id"] == "chat_wire" for chunk in chunks)
        assert all(chunk["agent_id"] == "manager_support" for chunk in chunks)
        assert len({chunk["message_id"] for chunk in chunks}) == 1
        assert "".join(chunk["token"] for chunk in chunks) == "El proveedor es FrescoSur."

    def test_interrupt_over_the_wire_stops_stream_and_opens_new_turn(self, ws_server: str) -> None:
        SCRIPT["protocolo de residuos paso a paso"] = [f"paso{i} " for i in range(40)]
        SCRIPT["espera, pregunté por el local de Miami"] = ["Para ", "Miami ", "es ", "otro."]
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> dict[str, Any]:
            async with connect(f"{ws_server}?session_id=chat_int&token={token}") as socket:
                await _recv_event(socket)  # session_snapshot
                await socket.send(
                    json.dumps(
                        {
                            "event": events.CHAT_EVENT_USER_MESSAGE,
                            "data": {
                                "session_id": "chat_int",
                                "text": "protocolo de residuos paso a paso",
                            },
                        }
                    )
                )
                frames: list[tuple[str, dict]] = []
                first_message_id = None
                while True:
                    name, data = await _recv_event(socket)
                    frames.append((name, data))
                    if name == events.CHAT_EVENT_GENERATION_STARTED:
                        first_message_id = data["message_id"]
                    if (
                        name == events.CHAT_EVENT_TOKEN_CHUNK
                        and data["sequence"] >= 3
                    ):
                        break

                await socket.send(
                    json.dumps(
                        {
                            "event": events.CHAT_EVENT_INTERRUPT_REQUESTED,
                            "data": {
                                "session_id": "chat_int",
                                "new_input": "espera, pregunté por el local de Miami",
                            },
                        }
                    )
                )

                # Se recogen los eventos hasta que el turno nuevo termine.
                while True:
                    name, data = await _recv_event(socket)
                    frames.append((name, data))
                    if (
                        name == events.CHAT_EVENT_GENERATION_COMPLETED
                        and data["message_id"] != first_message_id
                    ):
                        break

                # Reconexión para comprobar la rehidratación del transcript.
                snapshot = None
                async with connect(f"{ws_server}?session_id=chat_int&token={token}") as second:
                    name, snapshot = await _recv_event(second)
                    assert name == events.CHAT_EVENT_SESSION_SNAPSHOT
                return {
                    "frames": frames,
                    "first_message_id": first_message_id,
                    "snapshot": snapshot,
                }

        result = anyio.run(scenario)
        frames = result["frames"]
        first_message_id = result["first_message_id"]

        interrupted = [data for name, data in frames if name == events.CHAT_EVENT_GENERATION_INTERRUPTED]
        assert len(interrupted) == 1
        assert interrupted[0]["message_id"] == first_message_id
        assert interrupted[0]["status"] == "interrupted"

        first_tokens = [
            data["token"]
            for name, data in frames
            if name == events.CHAT_EVENT_TOKEN_CHUNK and data["message_id"] == first_message_id
        ]
        assert 0 < len(first_tokens) < 40, "el abort no detuvo la generación del modelo"

        second_tokens = [
            data["token"]
            for name, data in frames
            if name == events.CHAT_EVENT_TOKEN_CHUNK and data["message_id"] != first_message_id
        ]
        assert "".join(second_tokens) == "Para Miami es otro."
        assert [data["sequence"] for name, data in frames
                if name == events.CHAT_EVENT_TOKEN_CHUNK and data["message_id"] != first_message_id] == [1, 2, 3, 4]

        # El mensaje interrumpido conserva el texto mostrado y NO se sobrescribe.
        messages = result["snapshot"]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[1]["message_id"] == first_message_id
        assert messages[1]["status"] == "interrupted"
        assert messages[1]["content"] == "".join(first_tokens)
        assert messages[2]["content"] == "espera, pregunté por el local de Miami"
        assert messages[3]["content"] == "Para Miami es otro."

    def test_reconnect_restores_history_instead_of_empty_chat(self, ws_server: str) -> None:
        SCRIPT["¿Cuál es el horario del proveedor?"] = ["De ", "8:00 ", "a ", "17:00."]
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> dict[str, Any]:
            async with connect(f"{ws_server}?session_id=chat_recon&token={token}") as socket:
                await _recv_event(socket)  # snapshot vacío inicial
                await socket.send(
                    json.dumps(
                        {
                            "event": events.CHAT_EVENT_USER_MESSAGE,
                            "data": {
                                "session_id": "chat_recon",
                                "text": "¿Cuál es el horario del proveedor?",
                            },
                        }
                    )
                )
                await _recv_until(socket, events.CHAT_EVENT_GENERATION_COMPLETED)

            # Reconexión: mismo session_id → historial previo, no chat vacío.
            async with connect(f"{ws_server}?session_id=chat_recon&token={token}") as second:
                name, snapshot = await _recv_event(second)
                assert name == events.CHAT_EVENT_SESSION_SNAPSHOT
                await second.send(json.dumps({"event": "ping", "data": {}}))
                pong_name, pong = await _recv_event(second)
                return {"snapshot": snapshot, "pong_name": pong_name, "pong": pong}

        result = anyio.run(scenario)
        messages = result["snapshot"]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "¿Cuál es el horario del proveedor?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "completed"
        assert messages[1]["content"] == "De 8:00 a 17:00."
        assert result["pong_name"] == events.CHAT_EVENT_PONG
        assert result["pong"]["session_id"] == "chat_recon"

    def test_unknown_event_returns_error_without_closing(self, ws_server: str) -> None:
        token = create_access_token(user_id=MOCK_USER["id"])

        async def scenario() -> tuple[str, dict]:
            async with connect(f"{ws_server}?session_id=chat_err&token={token}") as socket:
                await _recv_event(socket)  # snapshot
                await socket.send(json.dumps({"event": "rfp_ticket_created", "data": {}}))
                return await _recv_event(socket)

        name, data = anyio.run(scenario)
        assert name == events.CHAT_EVENT_ERROR
        assert data["session_id"] == "chat_err"

    def test_second_listener_receives_the_same_generation(self, ws_server: str) -> None:
        """Dos conexiones a la misma ``session_id``: el publi­sher no las conoce.

        Es la prueba en el wire de que producción y consumo están desacoplados:
        el turno sólo publica en ``chat.<session_id>`` y ambas pestañas reciben
        exactamente los mismos ``token_chunk``.
        """
        SCRIPT["¿Quién aprueba los pedidos?"] = ["El ", "encargado ", "del ", "local."]
        token = create_access_token(user_id=MOCK_USER["id"])

        async def collect(socket) -> list[dict[str, Any]]:
            await _recv_event(socket)  # session_snapshot
            await socket.send(
                json.dumps(
                    {
                        "event": events.CHAT_EVENT_USER_MESSAGE,
                        "data": {
                            "session_id": "chat_two",
                            "text": "¿Quién aprueba los pedidos?",
                        },
                    }
                )
            )
            frames, _ = await _recv_until(socket, events.CHAT_EVENT_GENERATION_COMPLETED)
            return [
                data for name, data in frames if name == events.CHAT_EVENT_TOKEN_CHUNK
            ]

        async def scenario() -> tuple[list[dict], list[dict]]:
            async with connect(f"{ws_server}?session_id=chat_two&token={token}") as first:
                async with connect(f"{ws_server}?session_id=chat_two&token={token}") as second:
                    # ``anyio`` no trae ``gather``: se usa un grupo de tareas.
                    results: dict[int, list[dict]] = {}

                    async def run(index: int, socket) -> None:
                        results[index] = await collect(socket)

                    async with anyio.create_task_group() as group:
                        group.start_soon(run, 0, first)
                        group.start_soon(run, 1, second)
                    return results[0], results[1]

        first_chunks, second_chunks = anyio.run(scenario)
        assert first_chunks == second_chunks
        assert "".join(chunk["token"] for chunk in first_chunks) == "El encargado del local."


# ===================================================================
# 5) Rehidratación desde el checkpoint de LangGraph
# ===================================================================


class TestCheckpointRehydration:
    """Sin fichero de sesión, la conversación se recupera del checkpoint."""

    def test_snapshot_rebuilt_from_checkpoint_history(self) -> None:
        SCRIPT["¿Qué política de fidelización aplica?"] = ["Aplica ", "el ", "programa."]

        async def first_run() -> None:
            manager = ChatGenerationManager()
            await manager.start_turn("chat_checkpoint", "¿Qué política de fidelización aplica?")
            await manager.wait_idle("chat_checkpoint")

        anyio.run(first_run)

        # Se simula un proceso reiniciado: sin transcript en disco ni memoria.
        assert rehydrate_from_checkpoint("chat_checkpoint") != []

        from chat.sessions import ensure_session

        sessions_module.store._sessions.pop("chat_checkpoint", None)  # noqa: SLF001
        snapshot = ensure_session("chat_checkpoint")
        assert [message["role"] for message in snapshot["messages"]] == ["user", "assistant"]
        assert snapshot["messages"][0]["content"] == "¿Qué política de fidelización aplica?"
        assert snapshot["messages"][1]["content"] == "Aplica el programa."


__all__ = [
    "TestCheckpointRehydration",
    "TestEventContract",
    "TestGenerationManager",
    "TestPartialJsonStreaming",
    "TestPubSub",
    "TestWebSocketAuth",
    "TestWebSocketChat",
]
