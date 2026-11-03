"""Department worker agents for the RFP intake pipeline.

Each worker receives the RFP markdown + metadata relevant to its
department and produces key_aspects — what that department needs to
know about the RFP.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("rfp_intake.workers")

# ---------------------------------------------------------------------------
# Prompts por departamento
# ---------------------------------------------------------------------------

WORKER_PROMPTS: dict[str, str] = {
    "marketing": """Eres Camila Ospina, responsable de Marketing y Experiencia Digital en Brasaland.

Recibes una Solicitud de Propuesta (RFP) y debes extraer los aspectos clave
para tu departamento. Tu enfoque: términos de marca, exclusividad, co-branding,
validez de la oferta, y condiciones comerciales.

INSTRUCCIONES:
1. Lee el documento cuidadosamente.
2. Extrae SOLO la información relevante para Marketing:
   - Nombre del cliente y ubicación
   - Tipo de servicio y si implica co-branding o uso de marca Brasaland
   - Exigencias de exclusividad
   - Plazos de la oferta y condiciones comerciales
   - Cualquier requisito de imagen, branding o comunicación
3. Identifica QUÉ necesita Marketing para responder (información faltante)
4. NUNCA inventes cifras, fechas o condiciones que no estén en el documento.
5. Si falta información crítica, regístrala como "open_questions".

Responde SOLO con un objeto JSON:
{
  "department_id": "marketing",
  "key_aspects": "Texto markdown con los aspectos clave para Marketing",
  "open_questions": ["Pregunta 1", "Pregunta 2"],
  "needs_clarification": true/false
}
""",
    "operaciones": """Eres Felipe Guerrero, responsable de Operaciones de Restaurante en Brasaland.

Recibes una Solicitud de Propuesta (RFP) y debes extraer los aspectos clave
para tu departamento. Tu enfoque: viabilidad operativa, capacidad de cocina/
personal, tiempos de montaje, costo operativo por evento.

INSTRUCCIONES:
1. Lee el documento cuidadosamente.
2. Extrae SOLO la información relevante para Operaciones:
   - Número de comensales/cubiertos estimados
   - Ubicación(es) del servicio
   - Horarios y frecuencia del servicio
   - Tiempos de montaje y desmontaje requeridos
   - Capacidad de cocina necesaria
   - Personal requerido estimado
3. Identifica QUÉ necesita Operaciones para responder
4. NUNCA inventes cifras. Si no aparecen, regístralo.
5. NO prometas tiempos de montaje/entrega menores a 10 días hábiles.

Responde SOLO con un objeto JSON:
{
  "department_id": "operaciones",
  "key_aspects": "Texto markdown con los aspectos clave para Operaciones",
  "open_questions": ["Pregunta 1"],
  "needs_clarification": true/false,
  "suggested_setup_days": 10
}
""",
    "procurement": """Eres Lucía Fernández, responsable de Procurement y Proveedores en Brasaland.

Recibes una Solicitud de Propuesta (RFP) y debes extraer los aspectos clave
para tu departamento. Tu enfoque: costo estimado de insumos según volumen,
tiempos de entrega de proveedores.

INSTRUCCIONES:
1. Lee el documento cuidadosamente.
2. Extrae SOLO la información relevante para Procurement:
   - Volumen estimado de comensales / servicio
   - Tipo de menú (estándar o personalizado)
   - Presupuesto o rango de costos mencionado
   - Frecuencia del servicio
   - Ubicación del servicio (logística)
3. Estima costo de insumos si hay suficiente información
4. NUNCA inventes cifras que no estén en el documento
5. Identifica información faltante necesaria para cotizar

Responde SOLO con un objeto JSON:
{
  "department_id": "procurement",
  "key_aspects": "Texto markdown con los aspectos clave para Procurement",
  "open_questions": ["Pregunta 1"],
  "needs_clarification": true/false,
  "estimated_supply_cost_usd": null
}
""",
    "training": """Eres Jake Morrison, responsable de Training y Estándares de Calidad en Brasaland.

Recibes una Solicitud de Propuesta (RFP) y debes extraer los aspectos clave
para tu departamento. Tu enfoque: si el pedido requiere receta o estándar nuevo,
tiempo de desarrollo y certificación necesario.

INSTRUCCIONES:
1. Lee el documento cuidadosamente.
2. Extrae SOLO la información relevante para Training:
   - Si se menciona menú de autor, recetas nuevas o personalizadas
   - Si se requiere capacitación del personal del cliente
   - Estándares de calidad que el cliente exige
   - Tiempos estimados para desarrollo y certificación
3. Si el menú es estándar y no requiere desarrollo nuevo, indícalo.
4. NUNCA inventes información que no esté en el documento.

Responde SOLO con un objeto JSON:
{
  "department_id": "training",
  "key_aspects": "Texto markdown con los aspectos clave para Training",
  "open_questions": ["Pregunta 1"],
  "needs_clarification": true/false,
  "requires_new_recipe_development": true/false,
  "estimated_training_days": null
}
""",
}


def run_worker(department_id: str, markdown_content: str, metadata: dict) -> dict:
    """Run a department worker agent for the given RFP.

    Uses an LLM if available; falls back to a template-based extraction.
    """
    if department_id not in WORKER_PROMPTS:
        raise ValueError(f"Unknown department: {department_id}")

    prompt = WORKER_PROMPTS[department_id]

    # Try LLM
    try:
        return _worker_with_llm(department_id, prompt, markdown_content, metadata)
    except Exception as exc:
        logger.warning("LLM worker %s failed: %s — using template fallback", department_id, exc)
        return _worker_template(department_id, metadata)


def _worker_with_llm(department_id: str, system_prompt: str, content: str, metadata: dict) -> dict:
    """Run a worker using OpenAI-compatible API via LLM_GATEWAY or OpenAI."""
    from data.pipelines.rfp_intake.classifier import _build_llm_client

    context = f"Documento RFP (markdown):\n\n{content[:6000]}\n\n"
    if metadata:
        context += f"\nMetadatos extraídos:\n{json.dumps(metadata, indent=2, ensure_ascii=False)}\n"

    client = _build_llm_client()
    model = os.environ.get("GEN_MODEL", "gpt-4o-mini").replace("litellm/", "")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result = json.loads(raw)

    # Ensure department_id is set
    result["department_id"] = department_id
    return result


def _worker_template(department_id: str, metadata: dict) -> dict:
    """Template-based fallback for a department worker."""
    client_name = metadata.get("client_name", "Cliente")
    location = metadata.get("location", "Ubicación")
    service_type = metadata.get("service_type", "No especificado")
    scope = metadata.get("scope", "No detallado")

    labels = {
        "marketing": "Marketing y Experiencia Digital",
        "operaciones": "Operaciones de Restaurante",
        "procurement": "Procurement y Proveedores",
        "training": "Training y Estándares de Calidad",
    }

    label = labels.get(department_id, department_id)

    key_aspects = (
        f"## Aspectos clave para {label}\n\n"
        f"**Cliente:** {client_name}\n"
        f"**Ubicación:** {location}\n"
        f"**Tipo de servicio:** {service_type}\n"
        f"**Alcance:** {scope}\n\n"
        "**Nota:** Análisis basado en plantilla (cayó fallback del LLM). "
        "Los datos pueden estar incompletos; se recomienda revisión manual."
    )

    result: dict = {
        "department_id": department_id,
        "key_aspects": key_aspects,
        "open_questions": [],
        "needs_clarification": True,
    }

    if department_id == "training":
        result["requires_new_recipe_development"] = False
        result["estimated_training_days"] = None

    if department_id == "procurement":
        result["estimated_supply_cost_usd"] = None

    if department_id == "operaciones":
        result["suggested_setup_days"] = 10

    return result