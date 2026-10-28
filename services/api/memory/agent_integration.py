"""Memory integration layer for the Brasaland agent graph.

This module connects the LangGraph workflow with the Agent Memory System:

1. BEFORE responding: retrieves relevant memories via search_memories()
   and injects them into the agent's context (if score > 0.85 threshold).

2. AFTER responding: the agent self-evaluates whether there is anything
   new or corrected worth remembering, producing a MemorySuggestion
   alongside its answer (single LLM call — no second agent needed).

3. The MemorySuggestion is returned as part of the graph output, and
   the application layer handles proposal creation and confirmation.

Self-evaluation rules (from brasaland-BRIEFING.es.md):
- WHAT TO REMEMBER: location-specific corrections (hours, supplier days,
  local exceptions), resolved escalation context, manager communication
  preferences.
- WHAT NEVER TO REMEMBER: personal customer data beyond strictly
  operational, payroll data, single-use conversation details.

Examples that SHOULD generate a proposal:
- "En realidad el proveedor de vegetales en Medellín entrega los miércoles"
- "La location de Miami Beach cierra a las 11pm los fines de semana"
- "Esa alerta de ventas en cero fue por un apagón programado"

Examples that should NOT generate a proposal:
- "¿Cuál fue el ticket promedio de ayer?" (punctual query, data in telemetry)
- "Gracias, eso resuelve mi duda." (closing, nothing to persist)
- "¿Puedes traducir esto al inglés?" (one-off task, no value in persisting)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from memory.models import (
    MemorySearchResult,
    MemorySuggestion,
)
from memory.store import search_memories

logger = logging.getLogger("brasaland.memory.agent")

# System prompt fragment injected into the agent to enable self-evaluation.
# This is appended to the agent's system prompt so it produces a
# MemorySuggestion in the same response as its answer.
MEMORY_SELF_EVAL_PROMPT = """

## Memory Self-Evaluation

After answering, evaluate if there is anything NEW or CORRECTED in this
conversation that is worth remembering for future interactions.

### What IS worth remembering:
- Corrections to operational facts about a specific location:
  * Actual opening/closing hours
  * Supplier delivery days for a specific location
  * Local exceptions to standard procedures
- Context of a resolved escalation (e.g., "this alert was caused by a
  scheduled power outage, not a POS error")
- Communication preferences of a location manager

### What is NOT worth remembering:
- Personal customer data (lives in CRM)
- Payroll or individual compensation figures
- One-time events without a repeatable pattern
- Punctual data queries (the data lives in telemetry/pipelines)
- Simple acknowledgments or closing remarks
- Translation requests or single-use tasks

Output a JSON object with exactly these fields:
{
  "should_store": false,
  "summary": "",
  "location": "",
  "category": "",
  "confidence": 0.8,
  "reason": ""
}

- should_store: true only if there IS something new or corrected worth
  remembering. Most interactions should be false.
- summary: the fact to remember (e.g., "El proveedor de vegetales de
  Medellín entrega los miércoles, no los martes.")
- location: specific Brasaland location (e.g., "Medellín", "Miami
  Beach"). Empty string if global.
- category: one of "horarios", "proveedores", "incidentes_conocidos",
  "preferencias", or "general".
- confidence: how sure you are (0.0 to 1.0).
- reason: brief explanation of why this is worth remembering.

IMPORTANT: Set should_store to FALSE for most interactions. Only flag
genuinely reusable operational corrections.
"""


def inject_memories_into_context(
    question: str,
    location: str = "",
) -> str:
    """Search for relevant memories and format them for the agent's context.

    Called BEFORE the agent responds. If relevant memories are found
    (with score > threshold), they are formatted and returned as a
    context string to inject into the agent's prompt.

    Args:
        question: The user's current question.
        location: Optional location filter for more precise retrieval.

    Returns:
        A formatted string with relevant memories, or empty string if none found.
    """
    try:
        results = search_memories(
            query_text=question,
            limit=3,
            location_filter=location or None,
        )
    except Exception as exc:
        logger.warning("Memory search failed (non-blocking): %s", exc)
        return ""

    if not results:
        return ""

    lines = [
        "\n\n## Memorias de agente recuperadas (incidencias/soluciones previas)",
        "A continuación hay información de interacciones pasadas que podría",
        "ser relevante para esta consulta. Úsala como contexto adicional",
        "sin asumir que es la respuesta definitiva:\n",
    ]

    for mem in results:
        source = f"[{mem.location}]" if mem.location else "[General]"
        cat_label = {
            "horarios": "Horarios",
            "proveedores": "Proveedores",
            "incidentes_conocidos": "Incidentes conocidos",
            "preferencias": "Preferencias",
        }.get(mem.category, mem.category)
        lines.append(f"- {source} ({cat_label}, confianza: {mem.confidence:.0%}): {mem.summary}")

    return "\n".join(lines)


def parse_memory_suggestion(agent_output: dict[str, Any]) -> MemorySuggestion:
    """Parse a MemorySuggestion from the agent's output.

    The agent produces a JSON object with memory fields alongside its
    answer. This function extracts and validates it.

    Args:
        agent_output: The raw output dict from the agent, which may
            contain a 'memory_suggestion' or '_memory' field.

    Returns:
        A MemorySuggestion, defaulting to should_store=False if none found.
    """
    raw = agent_output.get("memory_suggestion") or agent_output.get("_memory") or {}

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return MemorySuggestion()

    if not isinstance(raw, dict):
        return MemorySuggestion()

    try:
        return MemorySuggestion(**raw)
    except (TypeError, ValueError):
        logger.warning("Invalid memory suggestion format: %s", raw)
        return MemorySuggestion()


def format_memory_proposal_for_user(suggestion: MemorySuggestion) -> str:
    """Format a memory proposal as a user-facing question.

    Args:
        suggestion: The MemorySuggestion from the agent.

    Returns:
        A formatted string asking the user for confirmation.
    """
    category_labels = {
        "horarios": "horario",
        "proveedores": "proveedor",
        "incidentes_conocidos": "incidente conocido",
        "preferencias": "preferencia",
        "general": "informacion general",
    }

    cat_label = category_labels.get(suggestion.category, suggestion.category)
    location_str = f" para {suggestion.location}" if suggestion.location else ""

    return (
        f"\n\n---\n"
        f"**Propuesta de memoria**\n\n"
        f"He notado que hay información corregida/nueva que podría "
        f"ser útil recordar:\n\n"
        f"> {suggestion.summary}\n\n"
        f"*Categoría*: {cat_label}{location_str}\n"
        f"*Confianza*: {suggestion.confidence:.0%}\n"
        f"*Razón*: {suggestion.reason}\n\n"
        f"¿Quieres que guarde esta información para usarla en "
        f"conversaciones futuras?\n"
        f"_(responde **sí** para aprobar, **no** para rechazar, "
        f"o edita el texto para corregirlo)_"
    )