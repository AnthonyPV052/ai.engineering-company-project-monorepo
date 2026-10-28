"""Pipeline público de recuperación y generación para Brasaland."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

# El indexador vive en services/api para compartir embed() y la configuración
# de la colección. Este import funciona tanto desde el checkout como desde el
# contenedor del backend.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_DIR = _REPO_ROOT / "services" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from openai import OpenAI  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

QDRANT_RETRIEVAL_TIMEOUT_SECONDS = float(os.getenv("RAG_QDRANT_TIMEOUT_SECONDS", "20"))
QDRANT_RETRIEVAL_ATTEMPTS = max(1, int(os.getenv("RAG_QDRANT_RETRIEVAL_ATTEMPTS", "2")))

from rag import COLLECTION_NAME, embed, gateway_model_name, setup  # noqa: E402

GEN_MODEL = "litellm/madrid-spain/openrouter/deepseek/deepseek-v4-flash"
DEFAULT_MIN_SCORE = 0.35


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def _qdrant_client() -> QdrantClient:
    return QdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        check_compatibility=False,
        timeout=QDRANT_RETRIEVAL_TIMEOUT_SECONDS,
    )


def retrieve(query: str, *, k: int = 5, min_score: float) -> list[dict]:
    """Recupera payloads de los vecinos semánticos que superen ``min_score``."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query debe ser un texto no vacío")
    if k < 1:
        raise ValueError("k debe ser mayor que cero")

    vector = embed(query)
    points = None
    for attempt in range(QDRANT_RETRIEVAL_ATTEMPTS):
        try:
            points = _qdrant_client().query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=k,
                with_payload=True,
                with_vectors=False,
            ).points
            break
        except Exception as exc:
            # Retry only request timeouts. DNS, connection, and configuration
            # failures are surfaced immediately rather than hidden by retries.
            causes = [exc]
            seen_ids = set()
            is_connect_timeout = False
            while causes:
                cause = causes.pop()
                if id(cause) in seen_ids:
                    continue
                seen_ids.add(id(cause))
                if type(cause).__name__ == "ConnectTimeout":
                    is_connect_timeout = True
                causes.extend(arg for arg in getattr(cause, "args", ()) if isinstance(arg, BaseException))
                nested = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
                if nested is not None:
                    causes.append(nested)
            if not is_connect_timeout or attempt + 1 >= QDRANT_RETRIEVAL_ATTEMPTS:
                raise
            time.sleep(min(0.5 * (2**attempt), 2.0))
    else:
        raise RuntimeError("Qdrant retrieval failed without an exception")
    return [
        dict(point.payload or {})
        for point in points
        if point.score is not None and point.score >= min_score and point.payload
    ]


def _context_text(context: list[dict]) -> str:
    if not context:
        return "[SIN CONTEXTO RECUPERADO]"
    return "\n\n".join(
        f"[{item.get('source_document', 'documento desconocido')} | "
        f"{item.get('section', 'General')}]\n{item.get('text', '')}"
        for item in context
    )


def generate_answer(question: str, context: list[dict]) -> str:
    """Genera una respuesta fundamentada exclusivamente en ``context``."""
    if not context:
        return "No encuentro esa información en la base de conocimiento de Brasaland."

    prompt = f"""Eres el asistente de conocimiento interno de Brasaland.
Responde la pregunta usando únicamente el CONTEXTO proporcionado.
Si el contexto está vacío o no contiene la respuesta, dilo claramente:
"No encuentro esa información en la base de conocimiento de Brasaland."
Nunca inventes políticas, ingredientes, precios, cantidades o procedimientos.

Responde en español, el idioma base del proyecto. Si la pregunta está en otro
idioma, responde en el idioma de la pregunta, conservando fielmente el
contenido fuente.
Para preguntas de alérgenos, nunca digas "sin riesgo": sigue literalmente las
advertencias y la redacción de brasaland-menu-allergens.es.md, incluida la
advertencia de que nunca se garantiza cero riesgo de contaminación cruzada.
Mantén exactamente los montos en USD y COP tal como aparecen en la fuente; no
conviertas monedas ni calcules equivalencias automáticamente.

CONTEXTO:
{_context_text(context)}

PREGUNTA:
{question}
"""
    client = OpenAI(api_key=_required_env("LLM_API_KEY"), base_url=_required_env("LLM_GATEWAY"))
    response = client.chat.completions.create(
        model=gateway_model_name(os.getenv("GEN_MODEL", GEN_MODEL)),
        messages=[
            {
                "role": "system",
                "content": "No respondas con conocimiento externo al contexto recibido.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError("El modelo de generación devolvió una respuesta vacía")
    return answer.strip()


def query(question: str) -> str:
    """Única entrada pública: recupera contexto y genera la respuesta final."""
    return generate_answer(question, retrieve(question, min_score=DEFAULT_MIN_SCORE))


__all__ = ["embed", "generate_answer", "query", "retrieve", "setup"]
