"""Extracción incremental del campo ``answer`` de un JSON que aún se está escribiendo.

El agente (``memory.generation.generate_answer_with_memory``) pide al modelo un
JSON con ``answer`` + ``propuesta_memoria``. Al activar ``stream=True`` el modelo
devuelve ese JSON por trozos, así que reenviar los deltas tal cual mostraría
fragmentos de JSON en el chat en lugar de la respuesta.

``AnswerFieldExtractor`` acumula los deltas y va decodificando, carácter a
carácter, el literal de cadena del campo ``"answer"``. Respeta los escapes JSON
(``\\"``, ``\\n``, ``\\uXXXX``) incluso cuando el escape queda partido entre dos
deltas, y deja de emitir en la comilla de cierre del valor.
"""

from __future__ import annotations

import re
from typing import Iterable

_ANSWER_KEY = re.compile(r'"answer"\s*:\s*"')

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class AnswerFieldExtractor:
    """Acumula deltas de JSON y devuelve el texto nuevo de ``answer``."""

    def __init__(self) -> None:
        self._buffer = ""
        self._cursor: int | None = None  # posición tras la comilla de apertura
        self._finished = False
        self._decoded = ""

    @property
    def started(self) -> bool:
        """``True`` si ya se encontró el inicio del valor de ``answer``."""
        return self._cursor is not None

    @property
    def finished(self) -> bool:
        """``True`` si ya se consumió la comilla de cierre de ``answer``."""
        return self._finished

    def feed(self, delta: str) -> str:
        """Añade un trozo del JSON y devuelve el texto nuevo ya decodificado."""
        if not delta or self._finished:
            return ""
        self._buffer += delta

        if self._cursor is None:
            match = _ANSWER_KEY.search(self._buffer)
            if match is None:
                return ""
            self._cursor = match.end()

        decoded, consumed_all = self._decode_from_cursor()
        self._decoded += decoded
        return decoded

    def _decode_from_cursor(self) -> tuple[str, bool]:
        assert self._cursor is not None
        out: list[str] = []
        index = self._cursor
        buffer = self._buffer

        while index < len(buffer):
            char = buffer[index]
            if char == '"':
                self._finished = True
                index += 1
                break
            if char != "\\":
                out.append(char)
                index += 1
                continue

            # Secuencia de escape: puede estar incompleta al final del buffer.
            if index + 1 >= len(buffer):
                break
            marker = buffer[index + 1]
            if marker == "u":
                if index + 6 > len(buffer):
                    break  # \uXXXX incompleto: esperar más deltas
                hex_digits = buffer[index + 2:index + 6]
                try:
                    out.append(chr(int(hex_digits, 16)))
                except ValueError:
                    out.append("\\u" + hex_digits)
                index += 6
                continue
            out.append(_SIMPLE_ESCAPES.get(marker, marker))
            index += 2

        self._cursor = index
        return "".join(out), index >= len(buffer)

    def result(self) -> str:
        """Texto completo de ``answer`` extraído hasta ahora."""
        return self._decoded


class JsonAnswerStreamer:
    """Adaptador con callback: convierte deltas del modelo en tokens de chat."""

    def __init__(self, sink) -> None:
        self._extractor = AnswerFieldExtractor()
        self._sink = sink
        self.emitted_any = False

    def push(self, delta: str) -> None:
        fragment = self._extractor.feed(delta)
        if fragment:
            self.emitted_any = True
            self._sink(fragment)


def extract_answer_from_partial(chunks: Iterable[str]) -> str:
    """Utilidad para pruebas: concatena los deltas y devuelve ``answer``."""
    extractor = AnswerFieldExtractor()
    pieces: list[str] = []
    for chunk in chunks:
        pieces.append(extractor.feed(chunk))
    pieces.append(extractor.feed(""))
    return "".join(pieces)


__all__ = ["AnswerFieldExtractor", "JsonAnswerStreamer", "extract_answer_from_partial"]
