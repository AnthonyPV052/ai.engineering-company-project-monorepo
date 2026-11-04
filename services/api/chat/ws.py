"""Endpoint WebSocket del chat en vivo — Parte 2.

Extiende el mismo agente de soporte que ya responde en
``POST /knowledge/query`` (ver ``routes/knowledge.py``) añadiendo el canal
persistente. No es una app paralela: reutiliza el grafo, la preparación del
turno, la memoria y el JWT del backoffice.

Flujo de conexión
-----------------
1. El cliente abre ``/chat/ws?session_id=<id>&token=<jwt>`` (o manda un primer
   frame ``{"event": "auth", "data": {"token": "..."}}`` cuando prefiere no
   poner el token en la URL — los navegadores no pueden enviar
   ``Authorization`` en el handshake de un WebSocket).
2. Si falta el token o es inválido se cierra con ``4401`` **antes** de enviar
   ningún evento de chat. Sin ``session_id`` se cierra con ``4400``.
3. Autenticado: se suscribe al canal ``chat.<session_id>`` y envía un
   ``session_snapshot`` con el historial (rehidratación al reconectar).
4. ``user_message`` inicia un turno; ``interrupt_requested`` aborta el turno en
   curso (opcionalmente con ``new_input``, que abre un turno nuevo);
   ``ping`` responde ``pong``.

Por qué el envío va en una tarea aparte
---------------------------------------
El handler lee frames en un bucle y una tarea ``sender`` drena la cola del
canal pub/sub. Así una respuesta larga nunca bloquea la lectura de
``interrupt_requested``: es justo lo que permite interrumpir a mitad de stream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from chat import events
from chat.generation import manager
from chat.pubsub import hub
from chat.sessions import ensure_session, store
from prompt_injection import scan_user_input
from agent_audit import log_agent_action, log_security_alert, AUDIT_EVENT_QUERY_RECEIVED

logger = logging.getLogger("api.chat.ws")

router = APIRouter(tags=["chat"])

#: Segundos que se espera el primer frame de auth cuando no vino en la URL.
AUTH_FRAME_TIMEOUT_SECONDS = 10.0
#: Cada cuánto se envía un ping de aplicación si no hay tráfico.
HEARTBEAT_INTERVAL_SECONDS = 25.0


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


def authenticate_token(token: str | None) -> dict[str, Any] | None:
    """Valida el JWT del backoffice y devuelve el usuario.

    Usa exactamente la misma pieza que ``security.get_current_user`` (HS256 +
    ``users_service.get_user_by_id`` + ``is_active``) pero sin depender de
    ``OAuth2PasswordBearer``, que no aplica al handshake de un WebSocket.
    """
    if not token:
        return None
    from security import ALGORITHM, get_secret_key  # import diferido: lee .env
    from users_service import get_user_by_id

    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = get_user_by_id(user_id)
    if user is None or not user.get("is_active", True):
        return None
    return user


async def _resolve_user(websocket: WebSocket, query_token: str | None) -> dict[str, Any] | None:
    """Token de la URL o, si no vino, primer frame ``auth``."""
    user = await asyncio.to_thread(authenticate_token, query_token)
    if user is not None or query_token:
        return user

    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AUTH_FRAME_TIMEOUT_SECONDS
        )
    except (asyncio.TimeoutError, WebSocketDisconnect):
        return None

    try:
        event, data = events.decode_client_frame(raw)
    except events.ChatProtocolError:
        return None
    if event != events.CHAT_EVENT_AUTH:
        return None
    return await asyncio.to_thread(authenticate_token, data.get("token"))


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.websocket("/chat/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()

    hub.bind_loop(asyncio.get_running_loop())

    session_id = websocket.query_params.get("session_id")
    user = await _resolve_user(websocket, websocket.query_params.get("token"))

    if user is None:
        # Sin autenticar no se envía ni un solo evento de chat.
        await websocket.close(code=events.WS_CLOSE_UNAUTHORIZED)
        return
    if not session_id:
        await websocket.close(code=events.WS_CLOSE_BAD_REQUEST)
        return

    user_id = str(user.get("id") or "")
    location_id = websocket.query_params.get("location_id")
    session = ensure_session(session_id, user_id=user_id, location_id=location_id)

    if session.get("user_id") and user_id and session["user_id"] != user_id:
        # Una sesión pertenece a un encargado: nadie más puede continuarla.
        await websocket.close(code=events.WS_CLOSE_FORBIDDEN)
        return

    queue = hub.subscribe(session_id)
    sender = asyncio.create_task(_sender(websocket, queue), name=f"chat-ws-send:{session_id}")
    heartbeat = asyncio.create_task(
        _heartbeat(websocket, session_id), name=f"chat-ws-ping:{session_id}"
    )

    try:
        await websocket.send_text(
            events.encode_event(
                events.CHAT_EVENT_SESSION_SNAPSHOT,
                events.session_snapshot_payload(session),
            )
        )
        while True:
            raw = await websocket.receive_text()
            try:
                event, data = events.decode_client_frame(raw)
            except events.ChatProtocolError as exc:
                await websocket.send_text(
                    events.encode_event(
                        events.CHAT_EVENT_ERROR,
                        events.error_payload(session_id=session_id, message=str(exc)),
                    )
                )
                continue

            if event == events.CHAT_EVENT_PING:
                await websocket.send_text(
                    events.encode_event(events.CHAT_EVENT_PONG, {"session_id": session_id})
                )
            elif event == events.CHAT_EVENT_AUTH:
                # Re-autenticación en caliente (token renovado).
                if await asyncio.to_thread(authenticate_token, data.get("token")) is None:
                    await websocket.close(code=events.WS_CLOSE_UNAUTHORIZED)
                    return
            elif event == events.CHAT_EVENT_USER_MESSAGE:
                text = (data.get("text") or "").strip()
                if not text:
                    await websocket.send_text(
                        events.encode_event(
                            events.CHAT_EVENT_ERROR,
                            events.error_payload(
                                session_id=session_id,
                                message="El mensaje no puede estar vacío.",
                                code="empty_message",
                            ),
                        )
                    )
                    continue

                # ── Prompt injection detection ────────────────────────
                injection_result = scan_user_input(text)
                if injection_result.is_suspicious:
                    log_security_alert(
                        "prompt_injection_ws",
                        session_id=session_id,
                        user_id=user_id,
                        details={
                            "matched_patterns": injection_result.matched_patterns,
                            "risk_score": injection_result.risk_score,
                            "text_preview": text[:200],
                        },
                    )
                    await websocket.send_text(
                        events.encode_event(
                            events.CHAT_EVENT_ERROR,
                            events.error_payload(
                                session_id=session_id,
                                message="Tu mensaje fue rechazado por seguridad. "
                                        "Si tienes una pregunta sobre operaciones "
                                        "de Brasaland, por favor reformúlala.",
                                code="prompt_injection",
                            ),
                        )
                    )
                    continue

                await manager.start_turn(
                    session_id,
                    text,
                    user_id=user_id,
                    location_id=location_id,
                )
            elif event == events.CHAT_EVENT_INTERRUPT_REQUESTED:
                new_input = (data.get("new_input") or "").strip() or None
                started = await manager.request_interrupt(session_id, new_input=new_input)
                if not started and new_input:
                    await websocket.send_text(
                        events.encode_event(
                            events.CHAT_EVENT_ERROR,
                            events.error_payload(
                                session_id=session_id,
                                message="No hay una generación en curso que interrumpir.",
                                code="nothing_to_interrupt",
                            ),
                        )
                    )
    except WebSocketDisconnect:
        logger.info("WebSocket de chat desconectado session_id=%s", session_id)
    finally:
        sender.cancel()
        heartbeat.cancel()
        hub.unsubscribe(session_id, queue)
        for task in (sender, heartbeat):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: B014 - cierre best-effort
                pass


async def _sender(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Reenvía al socket todo lo que se publique en el canal de la sesión."""
    try:
        while True:
            item = await queue.get()
            await websocket.send_text(events.encode_event(item["event"], item["data"]))
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        return


async def _heartbeat(websocket: WebSocket, session_id: str) -> None:
    """Ping de aplicación para que proxies no cierren una conexión ociosa."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await websocket.send_text(events.encode_event(events.CHAT_EVENT_PONG, {"session_id": session_id}))
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        return


__all__ = ["AUTH_FRAME_TIMEOUT_SECONDS", "authenticate_token", "router"]
