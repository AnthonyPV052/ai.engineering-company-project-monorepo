"""Indexación RAG de la base de conocimiento de Brasaland.

El módulo mantiene deliberadamente ``embed`` como única puerta de entrada al
modelo de embeddings: se usa tanto durante la indexación como en las
búsquedas de la aplicación.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI
from qdrant_client import QdrantClient, models

COLLECTION_NAME = "brasaland_knowledge"
COMPANY = "Brasaland"
_MAX_CHUNK_CHARS = 1200
EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("RAG_EMBEDDING_TIMEOUT_SECONDS", "30"))
EMBEDDING_RETRIES = int(os.getenv("RAG_EMBEDDING_RETRIES", "1"))


def _load_local_env() -> None:
    """Carga el .env de la raíz al ejecutar el API fuera de Docker."""
    module_parents = Path(__file__).resolve().parents
    candidates = [Path.cwd() / ".env"]
    # En Docker el módulo está directamente bajo /app, que no tiene una
    # raíz de monorepo. Compose ya inyecta las variables y sólo debe usarse
    # el .env del checkout cuando realmente estamos dentro de él.
    if len(module_parents) > 2:
        candidates.insert(0, module_parents[2] / ".env")
    env_file = next((path for path in candidates if path.is_file()), None)
    if env_file is None:
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


_load_local_env()


def _env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def gateway_model_name(model: str) -> str:
    """Adapta nombres ``litellm/...`` al gateway OpenAI de 4Geeks."""
    return model.removeprefix("litellm/")


def embed(text: str) -> list[float]:
    """Devuelve el embedding dedicado configurado para ``text``.

    ``LLM_GATEWAY`` debe ser un endpoint compatible con la API de OpenAI
    (normalmente termina en ``/v1``). No se usa el modelo de chat para evitar
    mezclar dimensiones o modelos entre indexación y consulta.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text debe ser un texto no vacío")

    client = OpenAI(
        api_key=_env("LLM_API_KEY"),
        base_url=_env("LLM_GATEWAY"),
        timeout=EMBEDDING_TIMEOUT_SECONDS,
        max_retries=0,
    )
    for attempt in range(EMBEDDING_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=gateway_model_name(_env("EMBED_MODEL")), input=text
            )
            break
        except Exception as exc:
            # Only retry a gateway timeout once; DNS/connection/configuration
            # failures cannot be repaired by repeating the same request.
            if type(exc).__name__ != "APITimeoutError" or attempt >= EMBEDDING_RETRIES:
                raise
            time.sleep(min(0.5 * (2**attempt), 2.0))
    vector = response.data[0].embedding
    return [float(value) for value in vector]


@dataclass(frozen=True)
class Chunk:
    source_document: str
    section: str
    text: str
    chunk_index: int


def _source_dir() -> Path:
    # Funciona desde el checkout y desde ``services/api`` dentro del Docker
    # container, sin depender del directorio de trabajo del proceso.
    configured = os.getenv("RAG_SOURCE_DIR")
    if configured:
        return Path(configured)
    module_dir = Path(__file__).resolve().parent
    candidates = [module_dir / "docs" / "company-knowledge-base"]
    # En el checkout, services/api está dos niveles bajo la raíz; en Docker
    # la primera ruta es la que apunta al COPY de la imagen.
    if len(Path(__file__).resolve().parents) > 2:
        candidates.append(Path(__file__).resolve().parents[2] / "docs" / "company-knowledge-base")
    return next((path for path in candidates if path.is_dir()), candidates[0])


def _split_long_block(block: str) -> list[str]:
    """Divide sólo en finales de frase; nunca corta una regla/list item."""
    if len(block) <= _MAX_CHUNK_CHARS:
        return [block]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ0-9¿¡-])", block)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > _MAX_CHUNK_CHARS:
            result.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        result.append(current)
    return result or [block]


def _parse_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if not raw:
        return []

    # Un párrafo/lista es la unidad mínima. Las listas se mantienen juntas,
    # pero cada elemento sigue siendo indivisible y no se corta por caracteres.
    blocks = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()]
    pieces: list[tuple[str, str]] = []
    section = "General"
    for block in blocks:
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", block)
        if heading:
            section = heading.group(1).strip()
            continue
        pieces.extend((section, item) for item in _split_long_block(block))

    # El contrato de indexación exige al menos tres unidades por documento.
    # Sólo se recurre a frases cuando un documento realmente tiene menos de 3
    # bloques; no se divide nunca una línea de regla a mitad.
    while len(pieces) < 3:
        largest = max(range(len(pieces)), key=lambda i: len(pieces[i][1]), default=-1)
        if largest < 0:
            break
        section_name, text = pieces.pop(largest)
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ0-9¿¡-])", text)
        if len(sentences) < 2:
            pieces.insert(largest, (section_name, text))
            break
        midpoint = max(1, len(sentences) // 2)
        pieces[largest:largest] = [
            (section_name, " ".join(sentences[:midpoint]).strip()),
            (section_name, " ".join(sentences[midpoint:]).strip()),
        ]

    document = path.name
    return [
        Chunk(document, section, text, index)
        for index, (section, text) in enumerate(pieces)
        if text
    ]


def _point_id(chunk: Chunk) -> str:
    key = f"{chunk.source_document}:{chunk.chunk_index}:{chunk.text}"
    return str(uuid.UUID(hashlib.md5(key.encode("utf-8")).hexdigest()))


def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


def setup() -> dict[str, int | str]:
    """Recrea e indexa la colección completa de conocimiento.

    La operación es idempotente mediante estrategia *clean-and-reload*: se
    elimina la colección anterior y se crea una nueva antes de insertar todos
    los puntos. Así tampoco quedan chunks obsoletos tras editar un documento.
    """
    documents = sorted(_source_dir().glob("*.md"))
    if not documents:
        raise RuntimeError(f"No hay documentos Markdown en {_source_dir()}")

    chunks = [chunk for path in documents for chunk in _parse_document(path)]
    if not chunks:
        raise RuntimeError("La base de conocimiento no contiene texto indexable")

    vectors = [embed(chunk.text) for chunk in chunks]
    dimension = len(vectors[0])
    if dimension == 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("El modelo de embeddings devolvió dimensiones inconsistentes")

    client = _qdrant_client()
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
    )

    points = [
        models.PointStruct(
            id=_point_id(chunk),
            vector=vector,
            payload={
                "source_document": chunk.source_document,
                "section": chunk.section,
                "company": COMPANY,
                "language": "es",
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    return {"collection": COLLECTION_NAME, "documents": len(documents), "chunks": len(points)}


__all__ = ["COLLECTION_NAME", "embed", "setup"]
