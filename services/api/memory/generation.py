"""Single-call answer generation with an optional structured memory proposal."""
from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from data.pipelines.rag import _context_text, _required_env, gateway_model_name, GEN_MODEL


class MemorySuggestion(BaseModel):
    should_store: bool = False
    summary: str = ""
    location: str = ""
    category: str = "general"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v):
        if isinstance(v, str):
            mapping = {
                "alta": 0.9, "media": 0.6, "baja": 0.3,
                "high": 0.9, "medium": 0.6, "low": 0.3,
                "muy alta": 0.95, "muy baja": 0.1,
                "ninguna": 0.0, "nula": 0.0,
            }
            return mapping.get(v.strip().lower(), 0.0)
        return v


class GeneratedResponse(BaseModel):
    model_config = {"extra": "ignore"}
    answer: str
    propuesta_memoria: MemorySuggestion = Field(default_factory=MemorySuggestion)


def generate_answer_with_memory(
    question: str, context: list[dict[str, Any]], memory_context: list[dict[str, Any]] | None = None,
    base_language: str = "es",
) -> tuple[str, MemorySuggestion]:
    memories = "\n".join(f"- {item['summary']}" for item in (memory_context or [])) or "[ninguna]"
    language_name = "English" if base_language == "en" else "espanol"
    context_text = _context_text(context) if context else "[SIN CONTEXTO RAG RECUPERADO]"
    prompt = f"""Eres el asistente de conocimiento interno de Brasaland. El idioma base elegido para esta sesion es {language_name}.
Responde usando unicamente el CONTEXTO de empresa para los hechos corporativos. Las memorias operativas confirmadas pueden contextualizar practicas locales, pero no son politica corporativa ni fuentes RAG.
Si no hay base suficiente, dilo claramente. Nunca inventes politicas, ingredientes, precios, cantidades o procedimientos.
Responde en el idioma de la pregunta y presenta cualquier propuesta en el idioma base elegido. Manten exactamente los montos USD/COP, sin conversiones.
Para alergenos sigue literalmente las advertencias, nunca garantices cero riesgo de contaminacion cruzada.

AUTOVALORACION: Devuelve should_store=true solo para (1) correcciones operativas recurrentes por location: horario, dia de entrega de proveedor o excepcion local; (2) contexto repetible de escalacion resuelta; o (3) preferencia de comunicacion de un gerente. No guardes datos personales de clientes de Brasa Points mas alla de lo estrictamente operativo, cifras de nomina o compensacion individual, ni hechos de una conversacion puntual sin patron repetible. Consultas puntuales (p. ej. ticket promedio de ayer), agradecimientos/cierres y traducciones de una vez deben tener should_store=false. Ante duda, false. Propon un solo hecho especifico y asigna categoria entre horarios, proveedores, incidentes_conocidos, preferencias, general. confidence debe ser un numero float entre 0.0 y 1.0 (ej: 0.9, 0.5, 0.2), NO texto como "alta" o "media".
Devuelve JSON con answer y propuesta_memoria (should_store, summary, location, category, confidence, reason). La respuesta debe ofrecer la propuesta al usuario si should_store=true; la API agregara el texto de confirmacion en el idioma de la pregunta.

MEMORIAS CONFIRMADAS (contexto independiente, no RAG):
{memories}

CONTEXTO RAG:
        {context_text}

PREGUNTA:
{question}
"""
    client = OpenAI(api_key=_required_env("LLM_API_KEY"), base_url=_required_env("LLM_GATEWAY"))
    response = client.chat.completions.create(
        model=gateway_model_name(os.getenv("GEN_MODEL", GEN_MODEL)),
        messages=[{"role": "system", "content": "Devuelve exclusivamente JSON valido segun el esquema solicitado."},
                  {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("El modelo de generacion devolvio una respuesta vacia")
    parsed = GeneratedResponse.model_validate(json.loads(content))
    return parsed.answer.strip(), parsed.propuesta_memoria