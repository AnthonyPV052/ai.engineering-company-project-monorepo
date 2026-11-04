"""Orquestación de turnos del chat en vivo — Parte 2.

Un **turno** es: mensaje del encargado → generación del *Manager support agent*
→ cierre del mensaje del asistente (completado, interrumpido o fallido).

Este módulo es el productor del canal pub/sub. No escribe en ningún WebSocket:
publica ``generation_started`` / ``token_chunk`` / ``generation_*`` en
``chat.<session_id>`` y las conexiones suscritas los reenvían.

Streaming de tokens
-------------------
``graph.astream(..., stream_mode=["custom", "values"])``. El modo ``custom``
transporta lo que el nodo ``generate`` empuja con ``get_stream_writer()``; el
nodo sólo emite ``{"type": "token", "text": ...}`` cuando el turno activó
``CONFIG_KEY_STREAM_TOKENS`` (ver ``graph/streaming.py``). El modo ``values``
aporta el estado final del turno.

Interrupción (abort real, no HITL)
----------------------------------
``interrupt_requested`` activa la ``AbortSignal`` del turno. El nodo lo consulta
entre deltas del modelo y lanza ``GenerationAborted``: se deja de leer el stream
del modelo (no se generan más ``token_chunk``) y el grafo no produce respuesta
final. **No se usa ``interrupt()`` de LangGraph**: eso pausaría el grafo
guardando un estado a medias y perdería el mensaje parcial que el usuario ya vio.

Tras el abort, el mensaje del asistente se marca ``interrupted`` conservando
sus tokens, la sesión pasa a ``interrupted`` y —si el cliente envió
``new_input``— se arranca un turno **nuevo** con ese texto. El mensaje
interrumpido nunca se borra ni se sobrescribe en el sitio.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from chat import events
from chat.pubsub import hub
from chat.sessions import ensure_session, store
from generation_control import (
    CONFIG_KEY_ABORT_SIGNAL,
    CONFIG_KEY_STREAM_TOKENS,
    AbortSignal,
    GenerationAborted,
)

logger = logging.getLogger("api.chat.generation")

#: Claves del estado que el turno aporta al grafo.
_HISTORY_LIMIT = 40


def _new_trace_id() -> str:
    return str(uuid.uuid4())


class ChatGenerationManager:
    """Coordina los turnos en curso (uno por sesión)."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._signals: dict[str, AbortSignal] = {}
        self._lock = asyncio.Lock()

    # -- estado interno ----------------------------------------------------

    async def is_generating(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        return task is not None and not task.done()

    def signal_for(self, session_id: str) -> AbortSignal | None:
        return self._signals.get(session_id)

    async def cancel_all(self) -> None:
        """Aborta todos los turnos (apagado ordenado del servidor)."""
        for session_id, signal in list(self._signals.items()):
            signal.request_abort("server_shutdown")
            task = self._tasks.get(session_id)
            if task is not None and not task.done():
                task.cancel()

    # -- turnos ------------------------------------------------------------

    async def start_turn(
        self,
        session_id: str,
        text: str,
        *,
        base_language: str = "es",
        user_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra el turno del usuario y arranca la generación del asistente.

        Devuelve el mensaje de usuario canónico. La generación corre en una
        tarea aparte para que el handler WebSocket siga leyendo frames (es lo
        que permite recibir ``interrupt_requested`` a mitad de respuesta).
        """
        session = ensure_session(session_id, user_id=user_id, location_id=location_id)
        if session.get("status") == events.SESSION_STATUS_CLOSED:
            store.set_status(session_id, events.SESSION_STATUS_ACTIVE)

        # Un solo turno activo por sesión: si el anterior seguía vivo se aborta
        # antes, de modo que nunca se mezclan dos generaciones. Se hace fuera
        # del lock porque ``_abort`` puede volver a entrar aquí.
        if await self.is_generating(session_id):
            await self._abort(session_id, new_input=None, reason="superseded")

        user_message = store.append_user_message(session_id, text)
        hub.publish(
            session_id,
            events.CHAT_EVENT_USER_MESSAGE,
            events.user_message_payload(
                session_id=session_id,
                message_id=user_message["message_id"],
                text=text,
            ),
        )

        async with self._lock:
            assistant_message = store.start_assistant_message(session_id)
            signal = AbortSignal()
            self._signals[session_id] = signal
            task = asyncio.create_task(
                self._run_turn(
                    session_id=session_id,
                    message_id=assistant_message["message_id"],
                    question=text,
                    base_language=base_language,
                    signal=signal,
                ),
                name=f"chat-turn:{session_id}",
            )
            self._tasks[session_id] = task

        return user_message

    async def request_interrupt(
        self,
        session_id: str,
        *,
        new_input: str | None = None,
    ) -> bool:
        """Aborta la generación en curso y, si procede, abre un turno nuevo.

        Devuelve ``True`` si había un turno activo que abortar.
        """
        return await self._abort(session_id, new_input=new_input, reason="interrupted")

    async def wait_idle(self, session_id: str) -> None:
        """Espera a que el turno activo termine (usado por tests y shutdown)."""
        task = self._tasks.get(session_id)
        if task is not None:
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):  # noqa: B014 - ya registrado
                pass

    # -- internos ----------------------------------------------------------

    async def _abort(self, session_id: str, *, new_input: str | None, reason: str) -> bool:
        signal = self._signals.get(session_id)
        task = self._tasks.get(session_id)
        if signal is None or task is None or task.done():
            if new_input:
                # No había nada que abortar, pero el texto redirigido sí abre un
                # turno: se considera atendido para no reportar «nothing to
                # interrupt» a un cliente cuyo mensaje ya está en marcha.
                await self.start_turn(session_id, new_input)
                return True
            return False

        signal.request_abort(reason)
        try:
            # El nodo consulta la señal entre deltas y lanza GenerationAborted;
            # al terminar la tarea ya no puede publicar más token_chunk. La
            # tarea es quien publica ``generation_interrupted`` con el mensaje
            # parcial ya ensamblado.
            await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        except Exception:  # pragma: no cover - el error ya se registró en la tarea
            pass

        # Red de seguridad: si el turno murió sin cerrar su mensaje (cancelación
        # forzada o timeout), lo cerramos aquí para que el cliente nunca quede
        # en ``streaming``. Si ya lo cerró, ``active_message_id`` es ``None``.
        message_id = store.active_message_id(session_id)
        if message_id is not None:
            store.finish_message(session_id, message_id, events.MESSAGE_STATUS_INTERRUPTED)
            hub.publish(
                session_id,
                events.CHAT_EVENT_GENERATION_INTERRUPTED,
                events.generation_interrupted_payload(
                    session_id=session_id,
                    message_id=message_id,
                    new_input=new_input,
                ),
            )

        if new_input:
            await self.start_turn(session_id, new_input)
        return True

    async def _run_turn(
        self,
        *,
        session_id: str,
        message_id: str,
        question: str,
        base_language: str,
        signal: AbortSignal,
    ) -> None:
        """Ejecuta el grafo y traduce sus eventos al contrato del chat."""
        from agent_turn_context import prepare_pending_proposal  # import diferido
        from graph.tracing import finish_trace, start_trace
        from graph.workflow import graph

        trace_id = _new_trace_id()
        sequence = 0
        published_tokens: list[str] = []
        interrupted = False

        hub.publish(
            session_id,
            events.CHAT_EVENT_GENERATION_STARTED,
            events.generation_started_payload(session_id=session_id, message_id=message_id),
        )

        try:
            pending_was_present, proposal_notice = prepare_pending_proposal(session_id, question)
            start_trace(trace_id, question)
            history = await self._history_for(session_id)

            payload = {
                "question": question,
                "context": [],
                "answer": "",
                "trace_id": trace_id,
                "session_id": session_id,
                "base_language": base_language,
                "pending_proposal_was_present": pending_was_present,
                "memory_proposal": proposal_notice,
                "turn_id": message_id,
                "user_message_id": None,
                "history": history,
            }
            config = {
                "configurable": {
                    "thread_id": session_id,
                    CONFIG_KEY_ABORT_SIGNAL: signal,
                    CONFIG_KEY_STREAM_TOKENS: True,
                }
            }

            final_state: dict[str, Any] = {}
            stream = graph.astream(payload, config=config, stream_mode=["custom", "values"])
            try:
                async for mode, chunk in stream:
                    if mode == "custom" and isinstance(chunk, dict):
                        if chunk.get("type") == "token":
                            token = chunk.get("text") or ""
                            if not token:
                                continue
                            if signal.is_aborted():
                                # No se publica nada más de esta generación.
                                break
                            sequence += 1
                            store.append_token(session_id, message_id, token)
                            published_tokens.append(token)
                            hub.publish(
                                session_id,
                                events.CHAT_EVENT_TOKEN_CHUNK,
                                events.token_chunk_payload(
                                    session_id=session_id,
                                    token=token,
                                    sequence=sequence,
                                    message_id=message_id,
                                ),
                            )
                        elif chunk.get("type") == "answer_final":
                            final_state["answer"] = chunk.get("text") or ""
                    elif mode == "values" and isinstance(chunk, dict):
                        if chunk.get("answer"):
                            final_state["answer"] = chunk["answer"]
            finally:
                await stream.aclose()  # type: ignore[attr-defined]

            if signal.is_aborted():
                interrupted = True
                raise GenerationAborted(signal.reason or "interrupted")

            answer = str(final_state.get("answer") or "".join(published_tokens))
            store.finish_message(
                session_id,
                message_id,
                events.MESSAGE_STATUS_COMPLETED,
                content=answer or None,
            )
            finish_trace(
                trace_id,
                answer,
                session_id=session_id,
                memory_proposal=final_state.get("memory_proposal"),
            )
            await self._record_turn(session_id, question, answer, message_id)
            hub.publish(
                session_id,
                events.CHAT_EVENT_GENERATION_COMPLETED,
                events.generation_completed_payload(
                    session_id=session_id,
                    message_id=message_id,
                    content_length=len(answer),
                ),
            )
        except GenerationAborted:
            interrupted = True
            logger.info("Turno interrumpido session_id=%s message_id=%s", session_id, message_id)
        except asyncio.CancelledError:
            interrupted = True
            logger.info("Turno cancelado session_id=%s message_id=%s", session_id, message_id)
            raise
        except Exception as exc:
            logger.exception("Turno fallido session_id=%s message_id=%s", session_id, message_id)
            store.finish_message(session_id, message_id, events.MESSAGE_STATUS_FAILED)
            hub.publish(
                session_id,
                events.CHAT_EVENT_GENERATION_FAILED,
                events.generation_failed_payload(
                    session_id=session_id,
                    message_id=message_id,
                    reason=type(exc).__name__,
                ),
            )
            return
        finally:
            self._signals.pop(session_id, None)
            if self._tasks.get(session_id) is asyncio.current_task():
                self._tasks.pop(session_id, None)

        if interrupted:
            # Los tokens ya entregados se conservan: el mensaje queda
            # ``interrupted`` con el texto parcial, nunca vacío ni sobrescrito.
            store.finish_message(session_id, message_id, events.MESSAGE_STATUS_INTERRUPTED)
            hub.publish(
                session_id,
                events.CHAT_EVENT_GENERATION_INTERRUPTED,
                events.generation_interrupted_payload(
                    session_id=session_id,
                    message_id=message_id,
                ),
            )
            await self._record_turn(
                session_id,
                question,
                "".join(published_tokens),
                message_id,
                status=events.MESSAGE_STATUS_INTERRUPTED,
            )

    async def _history_for(self, session_id: str) -> list[dict[str, Any]]:
        """Historial de turnos ya guardado en el checkpoint (rehidratación)."""
        try:
            from graph.workflow import graph

            state = await asyncio.to_thread(
                graph.get_state, {"configurable": {"thread_id": session_id}}
            )
        except Exception:  # pragma: no cover - checkpointer no disponible
            return []
        values = getattr(state, "values", None) or {}
        history = values.get("history")
        if not isinstance(history, list):
            return []
        return history[-_HISTORY_LIMIT:]

    async def _record_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        assistant_message_id: str,
        *,
        status: str = events.MESSAGE_STATUS_COMPLETED,
    ) -> None:
        """Añade el turno al historial del checkpoint del hilo.

        Permite rehidratar la conversación tras reconectar (``session_snapshot``)
        incluso si el fichero de sesión no existe.
        """
        try:
            from graph.workflow import graph

            current = await asyncio.to_thread(
                graph.get_state, {"configurable": {"thread_id": session_id}}
            )
            history = list((getattr(current, "values", None) or {}).get("history") or [])
            history.append(
                {
                    "question": question,
                    "answer": answer,
                    "status": status,
                    "assistant_message_id": assistant_message_id,
                }
            )
            await asyncio.to_thread(
                graph.update_state,
                {"configurable": {"thread_id": session_id}},
                {"history": history[-_HISTORY_LIMIT:]},
            )
        except Exception:  # pragma: no cover - el checkpoint es best-effort
            logger.warning("No se pudo actualizar el historial del hilo %s", session_id, exc_info=True)


#: Gestor único por proceso.
manager = ChatGenerationManager()


__all__ = ["ChatGenerationManager", "manager"]
