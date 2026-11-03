"""Emisión de tokens desde los nodos del grafo hacia el canal de chat.

LangGraph permite que un nodo publique eventos propios con el *stream writer*
(modo ``custom``). El canal WebSocket (Parte 2) es el único consumidor de esos
eventos; la ruta HTTP tradicional (``POST /knowledge/query``) usa ``invoke()``,
donde el writer es un no-op, así que emitir tokens no cambia su contrato.

Contrato del evento en crudo:

```python
{"type": "token", "text": "…"}   # fragmento de la respuesta del asistente
{"type": "answer_final", "text": "…"}  # opcional, respuesta completa ya cerrada
```

La capa de chat lo traduce a ``token_chunk`` agregando ``session_id``,
``message_id`` y ``sequence`` (ver ``chat/events.py``).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from generation_control import (
    AbortSignal,
    abort_signal_from_config,
    stream_tokens_enabled,
)

logger = logging.getLogger("api.agent.streaming")

try:  # pragma: no cover - import defensivo
    from langgraph.config import get_config, get_stream_writer
except Exception:  # pragma: no cover
    get_config = None  # type: ignore[assignment]
    get_stream_writer = None  # type: ignore[assignment]

#: Tamaño objetivo de los trozos cuando la respuesta no viene del modelo
#: (respuestas deterministas: incidencias, sin contexto, errores). El frontend
#: las anima igual que los tokens reales.
DETERMINISTIC_CHUNK_CHARS = 18

_WORD_RE = re.compile(r"\S+\s*")


def stream_writer() -> Any:
    """Devuelve el writer del grafo o ``None`` si no hay streaming activo."""
    if get_stream_writer is None:
        return None
    try:
        return get_stream_writer()
    except Exception:  # pragma: no cover - fuera de un nodo
        return None


def turn_controls() -> tuple[AbortSignal | None, bool]:
    """Señal de aborto y flag de streaming del turno en curso."""
    config: dict[str, Any] | None = None
    if get_config is not None:
        try:
            config = get_config()  # type: ignore[assignment]
        except Exception:  # pragma: no cover - fuera de un nodo
            config = None
    return abort_signal_from_config(config), stream_tokens_enabled(config)


def emit_token(text: str) -> None:
    """Publica un fragmento de respuesta (no-op si el streaming está apagado)."""
    if not text:
        return
    writer = stream_writer()
    if writer is None:
        return
    writer({"type": "token", "text": text})


def chunk_text(text: str, size: int = DETERMINISTIC_CHUNK_CHARS) -> Iterator[str]:
    """Parte un texto en trozos de tamaño similar respetando los espacios."""
    if not text:
        return
    buffer = ""
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        if buffer and len(buffer) + len(word.rstrip()) > size:
            yield buffer
            buffer = word
        else:
            buffer += word
    if buffer:
        yield buffer
    return


def emit_text_chunks(text: str) -> None:
    """Emite una respuesta ya calculada como si fuera un stream de tokens."""
    for piece in chunk_text(text):
        emit_token(piece)


def emit_answer_final(text: str) -> None:
    """Publica la respuesta final cerrada del turno (útil para reconciliar)."""
    writer = stream_writer()
    if writer is None or not text:
        return
    writer({"type": "answer_final", "text": text})


__all__ = [
    "DETERMINISTIC_CHUNK_CHARS",
    "chunk_text",
    "emit_answer_final",
    "emit_text_chunks",
    "emit_token",
    "stream_writer",
    "turn_controls",
]
