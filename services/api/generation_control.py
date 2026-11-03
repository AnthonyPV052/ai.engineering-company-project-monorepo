"""Señales de control compartidas entre la capa de agente y el canal de chat.

El chat en vivo (Parte 2) necesita dos cosas que la ruta HTTP tradicional no
tenía:

1. **Streaming de tokens**: el nodo ``generate`` del grafo debe poder emitir
   fragmentos a medida que el modelo los produce. LangGraph expone eso a través
   del *stream writer* en modo ``custom``; el nodo solo tiene que empujar
   ``{"type": "token", "text": ...}``.
2. **Abort real del stream**: cuando el encargado interrumpe, la generación en
   curso debe detenerse — no basta con dejar de enviar frames al cliente,
   también hay que cortar la lectura del stream del modelo y descartar el
   turno. LangGraph ``interrupt()`` (HITL) no sirve para esto: pausa el grafo y
   perdería el mensaje parcial que queremos conservar.

Ambas señales viajan en ``config["configurable"]`` del ``RunnableConfig`` de
LangGraph, así que la capa de agente no depende del transporte WebSocket.
"""

from __future__ import annotations

import threading
from typing import Any

#: Clave en ``config["configurable"]`` con la ``AbortSignal`` del turno.
CONFIG_KEY_ABORT_SIGNAL = "chat_abort_signal"

#: Clave en ``config["configurable"]`` que activa el streaming de tokens.
CONFIG_KEY_STREAM_TOKENS = "chat_stream_tokens"


class GenerationAborted(Exception):
    """La generación se abortó a petición del cliente (interrupción)."""


class AbortSignal:
    """Bandera de aborto segura entre hilos y event loop.

    El nodo del grafo corre en un hilo del executor de LangGraph mientras el
    handler WebSocket vive en el event loop de asyncio; por eso la bandera es
    un ``threading.Event``.
    """

    __slots__ = ("_event", "reason")

    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason: str | None = None

    def request_abort(self, reason: str = "interrupted") -> None:
        if not self._event.is_set():
            self.reason = reason
        self._event.set()

    def is_aborted(self) -> bool:
        return self._event.is_set()

    def raise_if_aborted(self) -> None:
        if self._event.is_set():
            raise GenerationAborted(self.reason or "interrupted")


def abort_signal_from_config(config: dict[str, Any] | None) -> AbortSignal | None:
    """Extrae la ``AbortSignal`` del ``RunnableConfig`` (si existe)."""
    if not config:
        return None
    configurable = config.get("configurable") or {}
    signal = configurable.get(CONFIG_KEY_ABORT_SIGNAL)
    return signal if isinstance(signal, AbortSignal) else None


def stream_tokens_enabled(config: dict[str, Any] | None) -> bool:
    """Indica si el turno actual debe emitir tokens por el stream writer."""
    if not config:
        return False
    configurable = config.get("configurable") or {}
    return bool(configurable.get(CONFIG_KEY_STREAM_TOKENS))


__all__ = [
    "AbortSignal",
    "CONFIG_KEY_ABORT_SIGNAL",
    "CONFIG_KEY_STREAM_TOKENS",
    "GenerationAborted",
    "abort_signal_from_config",
    "stream_tokens_enabled",
]
