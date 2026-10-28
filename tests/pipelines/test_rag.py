"""Pruebas unitarias del pipeline RAG, sin servicios externos en vivo."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for path in (ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# El entorno raíz no instala las dependencias del servicio API. Estos stubs
# evitan importarlas durante las pruebas unitarias (ningún test llama al SDK).
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub
if "qdrant_client" not in sys.modules:
    qdrant_stub = types.ModuleType("qdrant_client")
    qdrant_stub.QdrantClient = object
    qdrant_stub.models = types.SimpleNamespace()
    sys.modules["qdrant_client"] = qdrant_stub

from data.pipelines import rag  # noqa: E402


@dataclass
class FakePoint:
    score: float | None
    payload: dict | None


class InMemoryQdrant:
    """Stub mínimo de Qdrant: conserva puntos en memoria y registra la consulta."""

    def __init__(self, points: list[FakePoint]) -> None:
        self.points = points
        self.calls: list[dict] = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return type("QueryResult", (), {"points": self.points})()


def test_retrieve_filters_scores_and_can_return_fewer_than_k(monkeypatch):
    client = InMemoryQdrant(
        [
            FakePoint(0.92, {"text": "resultado bueno", "source_document": "a.md"}),
            FakePoint(0.34, {"text": "resultado bajo", "source_document": "b.md"}),
            FakePoint(0.81, {"text": "otro bueno", "source_document": "c.md"}),
            FakePoint(None, {"text": "sin score", "source_document": "d.md"}),
            FakePoint(0.99, None),
        ]
    )
    monkeypatch.setattr(rag, "_qdrant_client", lambda: client)
    monkeypatch.setattr(rag, "embed", lambda text: [1.0, 0.0])

    results = rag.retrieve("¿Qué debo saber?", k=5, min_score=0.8)

    assert results == [
        {"text": "resultado bueno", "source_document": "a.md"},
        {"text": "otro bueno", "source_document": "c.md"},
    ]
    assert len(results) < 5
    assert client.calls[0]["limit"] == 5
    assert client.calls[0]["with_payload"] is True


def test_retrieve_rejects_invalid_query_or_k(monkeypatch):
    monkeypatch.setattr(rag, "_qdrant_client", lambda: InMemoryQdrant([]))
    with pytest.raises(ValueError, match="no vacío"):
        rag.retrieve("  ", min_score=0.35)
    with pytest.raises(ValueError, match="mayor que cero"):
        rag.retrieve("pregunta", k=0, min_score=0.35)


def test_query_returns_generated_model_output(monkeypatch):
    chunks = [{"source_document": "brasaland-loyalty-program.es.md", "text": "5% los martes"}]
    calls: dict[str, object] = {}

    def fake_retrieve(question: str, *, min_score: float):
        calls["question"] = question
        calls["min_score"] = min_score
        return chunks

    def fake_generate(question: str, context: list[dict]) -> str:
        calls["context"] = context
        return "La respuesta generada es: 5% los martes."

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag, "generate_answer", fake_generate)

    result = rag.query("¿Qué descuento tiene Bronce?")

    assert result == "La respuesta generada es: 5% los martes."
    assert result != chunks[0]["text"]
    assert calls == {
        "question": "¿Qué descuento tiene Bronce?",
        "min_score": rag.DEFAULT_MIN_SCORE,
        "context": chunks,
    }


def test_query_does_not_return_raw_chunks_when_generation_is_empty(monkeypatch):
    chunk = {"source_document": "a.md", "text": "contenido recuperado"}
    monkeypatch.setattr(rag, "retrieve", lambda question, *, min_score: [chunk])
    monkeypatch.setattr(rag, "generate_answer", lambda question, context: "respuesta del LLM")

    assert rag.query("pregunta") == "respuesta del LLM"
    assert rag.query("pregunta") != chunk["text"]


def test_empty_retrieval_returns_safe_no_information_answer(monkeypatch):
    """Sin hits, el pipeline responde sin invocar un modelo generativo."""
    def fail_if_called(**kwargs):
        raise AssertionError("no debe llamarse al LLM sin contexto")

    monkeypatch.setattr(rag, "OpenAI", fail_if_called)

    answer = rag.generate_answer("¿Qué política no documentada existe?", [])

    assert answer == "No encuentro esa información en la base de conocimiento de Brasaland."
