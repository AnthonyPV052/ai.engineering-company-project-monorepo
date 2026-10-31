"""Generator agents for Part 2 of the RFP intake pipeline.

Each department generator receives the handoff payload from Part 1
(metadata + key_aspects) and produces a draft section for the economic
proposal. Generators do NOT re-ingest the raw PDF as primary input.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("rfp_intake.generators")

# ---------------------------------------------------------------------------
# Generator prompts per department
# ---------------------------------------------------------------------------

GENERATOR_PROMPTS: dict[str, str] = {
    "marketing": """Eres Camila Ospina, responsable de Marketing y Experiencia Digital en Brasaland.

Debes redactar la sección de **Marketing** de una propuesta económica para un cliente.

## Información disponible (del análisis de la Parte 1)
- Cliente, ubicación, tipo de servicio, alcance
- Aspectos clave identificados por tu departamento
- Preguntas abiertas / información faltante

## Lo que debe incluir tu sección:
1. **Términos de marca**: cómo se usará la marca Brasaland (co-branding, exclusividad, etc.)
2. **Validez de la oferta**: incluir un período de validez de 30 días desde su emisión
3. **Pilares de marca**: mencionar los tres pilares: calidad consistente, experiencia cálida, velocidad de servicio
4. **Precios**: expresar cifras en COP y USD cuando aplique
5. **No mencionar competidores** por nombre
6. **No prometer montaje/entrega en menos de 10 días hábiles**

Formato: redacción profesional en markdown, lista de condiciones comerciales, pricing si aplica.

Responde SOLO con un objeto JSON:
{
  "department_id": "marketing",
  "draft_content": "Sección de la propuesta en markdown...",
  "open_questions": ["Pregunta 1"],
  "estimated_value_cop": null,
  "estimated_value_usd": null
}
""",
    "operaciones": """Eres Felipe Guerrero, responsable de Operaciones de Restaurante en Brasaland.

Debes redactar la sección de **Operaciones** de una propuesta económica para un cliente.

## Información disponible (del análisis de la Parte 1)
- Cliente, ubicación, tipo de servicio, alcance
- Aspectos clave identificados por tu departamento

## Lo que debe incluir tu sección:
1. **Plan operativo**: descripción de cómo se ejecutará el servicio
2. **Tiempos**: NO prometer montaje/entrega en menos de 10 días hábiles
3. **Personal requerido**: estimado de personal necesario
4. **Pilares de marca**: mencionar los tres pilares: calidad consistente, experiencia cálida, velocidad de servicio
5. **Precios**: expresar cifras en COP y USD cuando aplique
6. **No mencionar competidores** por nombre

Formato: redacción profesional en markdown.

Responde SOLO con un objeto JSON:
{
  "department_id": "operaciones",
  "draft_content": "Sección de la propuesta en markdown...",
  "open_questions": ["Pregunta 1"],
  "estimated_setup_days": 10,
  "estimated_staff_required": null
}
""",
    "procurement": """Eres Lucía Fernández, responsable de Procurement y Proveedores en Brasaland.

Debes redactar la sección de **Procurement** de una propuesta económica para un cliente.

## Información disponible (del análisis de la Parte 1)
- Cliente, ubicación, tipo de servicio, alcance, volúmenes
- Aspectos clave identificados por tu departamento

## Lo que debe incluir tu sección:
1. **Costo estimado de insumos**: según volumen y tipo de menú
2. **Tiempos de entrega de proveedores**
3. **Precios**: expresar cifras en COP y USD
4. **Pilares de marca**: mencionar los tres pilares: calidad consistente, experiencia cálida, velocidad de servicio
5. **No mencionar competidores** por nombre
6. **No prometer entregas en menos de 10 días hábiles**

Formato: redacción profesional en markdown, tabla de costos si aplica.

Responde SOLO con un objeto JSON:
{
  "department_id": "procurement",
  "draft_content": "Sección de la propuesta en markdown...",
  "open_questions": ["Pregunta 1"],
  "estimated_supply_cost_usd": null,
  "estimated_supply_cost_cop": null
}
""",
    "training": """Eres Jake Morrison, responsable de Training y Estándares de Calidad en Brasaland.

Debes redactar la sección de **Training** de una propuesta económica para un cliente.

## Información disponible (del análisis de la Parte 1)
- Cliente, ubicación, tipo de servicio
- Aspectos clave identificados por tu departamento

## Lo que debe incluir tu sección:
1. **Plan de capacitación**: si aplica, describir el entrenamiento necesario
2. **Tiempos de desarrollo y certificación**
3. **Precios**: expresar cifras en COP y USD cuando aplique
4. **Pilares de marca**: mencionar los tres pilares: calidad consistente, experiencia cálida, velocidad de servicio
5. **No mencionar competidores** por nombre
6. **No prometer desarrollo/montaje en menos de 10 días hábiles**

Si el menú es estándar y no requiere nuevo desarrollo, indicarlo claramente.

Formato: redacción profesional en markdown.

Responde SOLO con un objeto JSON:
{
  "department_id": "training",
  "draft_content": "Sección de la propuesta en markdown...",
  "open_questions": ["Pregunta 1"],
  "requires_new_recipe_development": false,
  "estimated_training_days": null
}
""",
}


def run_generator(
    department_id: str,
    handoff_payload: dict,
    previous_feedback: str | None = None,
) -> dict:
    """Run a department generator agent.

    Args:
        department_id: One of 'marketing', 'operaciones', 'procurement', 'training'.
        handoff_payload: The Part 1 handoff dict with metadata and key_aspects.
        previous_feedback: Optional feedback from evaluator for iteration.

    Returns:
        dict with 'department_id', 'draft_content', etc.
    """
    if department_id not in GENERATOR_PROMPTS:
        raise ValueError(f"Unknown department generator: {department_id}")

    prompt = GENERATOR_PROMPTS[department_id]

    try:
        return _generator_with_llm(department_id, prompt, handoff_payload, previous_feedback)
    except Exception as exc:
        logger.warning("LLM generator %s failed: %s — using template fallback", department_id, exc)
        return _generator_template(department_id, handoff_payload)


def _generator_with_llm(
    department_id: str,
    system_prompt: str,
    handoff_payload: dict,
    previous_feedback: str | None,
) -> dict:
    """Run generator using OpenAI-compatible API."""
    from data.pipelines.rfp_intake.classifier import _build_llm_client

    # Build context from the handoff payload (NOT the raw PDF)
    context_parts: list[str] = []

    context_parts.append("## Metadatos del Cliente (Parte 1)")
    meta = handoff_payload.get("metadata", handoff_payload)
    context_parts.append(json.dumps({
        "client_name": meta.get("client_name"),
        "location": meta.get("location"),
        "service_type": meta.get("service_type"),
        "scope": meta.get("scope"),
        "deadline": meta.get("deadline"),
        "budget_range": meta.get("budget_range"),
        "annual_estimated_usd": meta.get("annual_estimated_usd"),
    }, indent=2, ensure_ascii=False))

    # Key aspects from Part 1 for this department
    aspects_by_dept = handoff_payload.get("key_aspects_by_department", {})
    dept_aspects = aspects_by_dept.get(department_id, "")
    context_parts.append(f"\n## Aspectos Clave ({department_id}) — de la Parte 1")
    context_parts.append(dept_aspects or "No disponibles")

    # Open questions from Part 1 for this department
    open_qs_by_dept = handoff_payload.get("open_questions", {})
    dept_open_qs = open_qs_by_dept.get(department_id, [])
    if dept_open_qs:
        context_parts.append(f"\n## Preguntas abiertas ({department_id})")
        for q in dept_open_qs:
            context_parts.append(f"- {q}")

    # Previous feedback if in iteration
    if previous_feedback:
        context_parts.append(f"\n## Feedback del evaluador (iteración anterior)")
        context_parts.append(previous_feedback)
        context_parts.append("\nPor favor, corrige tu borrador según este feedback.")

    context = "\n".join(context_parts)

    client = _build_llm_client()
    model = os.environ.get("GEN_MODEL", "gpt-4o-mini").replace("litellm/", "")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result = json.loads(raw)

    # Ensure department_id is set
    result["department_id"] = department_id
    return result


def _generator_template(department_id: str, handoff_payload: dict) -> dict:
    """Template-based fallback generator."""
    meta = handoff_payload.get("metadata", handoff_payload)
    client_name = meta.get("client_name", "Cliente")
    location = meta.get("location", "Ubicación no especificada")
    service_type = meta.get("service_type", "No especificado")
    scope = meta.get("scope", "No detallado")
    budget = meta.get("budget_range", "No especificado")
    aspects = handoff_payload.get("key_aspects_by_department", {}).get(department_id, "")

    dept_labels = {
        "marketing": "Marketing y Experiencia Digital",
        "operaciones": "Operaciones de Restaurante",
        "procurement": "Procurement y Proveedores",
        "training": "Training y Estándares de Calidad",
    }
    label = dept_labels.get(department_id, department_id)

    draft = (
        f"## {label}\n\n"
        f"### Resumen Ejecutivo\n\n"
        f"Propuesta para **{client_name}** en {location}.\n"
        f"**Tipo de servicio:** {service_type}\n"
        f"**Alcance:** {scope}\n"
        f"**Presupuesto referenciado:** {budget}\n\n"
        f"### Análisis\n\n"
    )
    if aspects:
        draft += f"{aspects}\n\n"
    draft += (
        "### Condiciones\n\n"
        "- **Pilares de marca:** Calidad consistente, experiencia cálida, velocidad de servicio.\n"
        "- **Validez de la oferta:** 30 días desde su emisión.\n"
        "- **Precios expresados en COP y USD.**\n"
        "- No se mencionan competidores.\n"
        "- Los tiempos de montaje y entrega no serán menores a 10 días hábiles.\n\n"
        "> ⚠️ **Nota:** Este borrador fue generado con plantilla de respaldo. "
        "Requiere revisión manual. Los datos pueden estar incompletos."
    )

    result: dict = {
        "department_id": department_id,
        "draft_content": draft,
        "open_questions": [],
    }

    if department_id == "training":
        result["requires_new_recipe_development"] = False
        result["estimated_training_days"] = None
    elif department_id == "procurement":
        result["estimated_supply_cost_usd"] = None
        result["estimated_supply_cost_cop"] = None
    elif department_id == "operaciones":
        result["estimated_setup_days"] = 10
        result["estimated_staff_required"] = None
    elif department_id == "marketing":
        result["estimated_value_cop"] = None
        result["estimated_value_usd"] = None

    return result