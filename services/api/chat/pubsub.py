"""Pub/sub en memoria: canal por sesión de chat — Parte 2.

El productor (el turno del agente emitiendo ``token_chunk``) no conoce a los
consumidores (las conexiones WebSocket suscritas). Ambos se encuentran en un
canal con nombre ``chat.<session_id>``.

Por qué importa: con un único WebSocket la tentación es escribir directamente
en el socket desde el generador. Eso acopla el agente al transporte, rompe si
hay dos pestañas abiertas en la misma sesión y hace imposible reconectar a mitad
de stream (el consumidor nuevo no recibiría nada). Con el canal, la generación
sólo publica y cada conexión decide qué hacer.

Alcance: en memoria del proceso. La API corre con un único worker uvicorn en
Compose (igual que el SSE de la Parte 1), así que no hace falta Redis. Si algún
día hay varios workers, se sustituye ``ChatPubSub`` por una implementación con
backplane sin tocar ni el agente ni el WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Iterable

logger = logging.getLogger("api.chat.pubsub")

#: Prefijo del canal por sesión.
CHANNEL_PREFIX = "chat."


def channel_for(session_id: str) -> str:
    """Canal pub/sub de una sesión: ``chat.<session_id>``."""
    return f"{CHANNEL_PREFIX}{session_id}"


class ChatPubSub:
    """Hub de suscriptores por canal (una ``asyncio.Queue`` por consumidor).

    Todas las operaciones se ejecutan en el event loop del servidor. Para
    publicar desde un hilo distinto existe ``publish_threadsafe``.
    """

    def __init__(self, *, queue_maxsize: int = 1024) -> None:
        self._queue_maxsize = queue_maxsize
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    # -- ciclo de vida -----------------------------------------------------

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Registra el event loop del servidor (para publicaciones desde hilos)."""
        self._loop = loop

    # -- suscripción -------------------------------------------------------

    def subscribe(self, session_id: str) -> asyncio.Queue:
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:  # pragma: no cover - fuera de un loop
                pass
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        with self._lock:
            self._subscribers.setdefault(channel_for(session_id), set()).add(queue)
        logger.debug("Suscriptor añadido a %s (%d total)", channel_for(session_id), self.subscriber_count(session_id))
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        channel = channel_for(session_id)
        with self._lock:
            subscribers = self._subscribers.get(channel)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(channel, None)
        logger.debug("Suscriptor retirado de %s", channel)

    def subscriber_count(self, session_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(channel_for(session_id), ()))

    def channels(self) -> Iterable[str]:
        with self._lock:
            return tuple(self._subscribers)

    # -- publicación -------------------------------------------------------

    def publish(self, session_id: str, event: str, data: dict[str, Any]) -> int:
        """Publica un evento en el canal de la sesión.

        Devuelve cuántos consumidores lo recibieron. Si un consumidor está
        saturado se descarta **su** copia en vez de bloquear la generación: el
        frontend se recupera con ``session_snapshot`` al reconectar.
        """
        channel = channel_for(session_id)
        with self._lock:
            subscribers = tuple(self._subscribers.get(channel, ()))

        delivered = 0
        for queue in subscribers:
            try:
                queue.put_nowait({"event": event, "data": data})
                delivered += 1
            except asyncio.QueueFull:  # pragma: no cover - consumidor lento
                logger.warning("Cola llena en %s; evento %s descartado", channel, event)
        return delivered

    def publish_threadsafe(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        """Publica desde un hilo que no es el del event loop."""
        loop = self._loop
        if loop is None:
            logger.debug("Sin event loop registrado; evento %s no publicado", event)
            return
        loop.call_soon_threadsafe(self.publish, session_id, event, data)


#: Hub único por proceso.
hub = ChatPubSub()


__all__ = ["CHANNEL_PREFIX", "ChatPubSub", "channel_for", "hub"]
