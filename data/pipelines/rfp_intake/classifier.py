"""RFP Classifier Agent — decides whether a document is a legitimate RFP.

Uses an LLM (OpenAI / compatible) to classify the document and extract
initial metadata. Returns structured classification results.
Supports both Spanish and English documents.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("rfp_intake.classifier")

# ---------------------------------------------------------------------------
# Classification schema (returned as dict)
# ---------------------------------------------------------------------------

CLASSIFICATION_PROMPT = """You are a document classifier for Brasaland Food Group.

Your task is to determine whether the following document is a valid **Request for
Proposal (RFP)** for Brasaland, or if it should be rejected. The document may be
in Spanish or English.

## Criteria to ACCEPT (valid RFP):
- The document comes from a potential client requesting a food service
  (catering, concession, co-branding, recurring service, etc.)
- It includes at least: client/company name, a requested service, and scope/volume
- It includes a deadline or timeframe to respond (even if informal)
- It may be formal (structured letter) or informal (email)

## Criteria to REJECT:
- No clearly requested food service
- Totally missing scope, budget, or deadline
- It is a general inquiry (franchise, information, etc.) with no intention to hire
- Not related to food/restaurant/catering services

## Instructions:
1. Carefully analyze the document.
2. Decide if it is a valid RFP (is_valid=True) or not (is_valid=False).
3. If valid, extract the requested metadata from the document ONLY if present.
   NEVER invent figures, dates, or names that do not appear in the document.
4. Provide a brief reason for the classification (in English or Spanish as appropriate).
5. Identify which Brasaland departments should participate based on content:
   - "marketing": almost always applies (brand terms, exclusivity)
   - "operaciones": if there are setup details, kitchen capacity, staff
   - "procurement": if there are supply volumes, costs, suppliers
   - "training": if new recipes, signature menu, training, new standards are mentioned

Respond ONLY with a valid JSON object with this exact structure:
{
  "is_valid": true/false,
  "classification_reason": "Brief reason",
  "confidence": 0.0-1.0,
  "metadata": {
    "client_name": "Client name or null",
    "location": "Location or null",
    "service_type": "Service type or null",
    "scope": "Scope description or null",
    "deadline": "Deadline or null",
    "budget_range": "Budget range or null",
    "annual_estimated_usd": 0.0 (null if not in document)
  },
  "departments_needed": ["marketing", "operaciones", ...]
}
"""


def _build_llm_client():
    """Build an OpenAI-compatible client using LLM_GATEWAY + LLM_API_KEY or OPENAI_API_KEY."""
    from openai import OpenAI

    gateway = os.environ.get("LLM_GATEWAY", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()

    if gateway and api_key:
        logger.info("Using LLM_GATEWAY at %s", gateway)
        return OpenAI(base_url=gateway, api_key=api_key)
    elif os.environ.get("OPENAI_API_KEY"):
        logger.info("Using OpenAI (OPENAI_API_KEY)")
        return OpenAI()
    else:
        raise RuntimeError(
            "No LLM credentials available. Set LLM_GATEWAY + LLM_API_KEY "
            "or OPENAI_API_KEY in environment."
        )


def classify_document(markdown_content: str) -> dict:
    """Classify a document as valid RFP or not, extracting metadata.

    Uses OpenAI-compatible API. Falls back to a rule-based heuristic
    if the API is unavailable.
    """
    if not markdown_content or not markdown_content.strip():
        return {
            "is_valid": False,
            "classification_reason": "Documento vacío / Empty document",
            "confidence": 1.0,
            "metadata": {},
            "departments_needed": [],
        }

    # Truncate very long content to avoid token limits
    content_preview = markdown_content[:8000]

    # Try LLM-based classification
    try:
        return _classify_with_llm(content_preview)
    except Exception as exc:
        logger.warning("LLM classification failed: %s — falling back to rule-based", exc)
        return _classify_rule_based(markdown_content)


def _classify_with_llm(content: str) -> dict:
    """Classify using OpenAI-compatible API via LLM_GATEWAY or OpenAI."""
    client = _build_llm_client()

    response = client.chat.completions.create(
        model=os.environ.get("GEN_MODEL", "gpt-4o-mini").replace("litellm/", ""),
        messages=[
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": f"Document to classify:\n\n{content}"},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result = json.loads(raw)

    # Validate structure
    if "is_valid" not in result:
        raise ValueError(f"LLM response missing is_valid key: {raw[:200]}")

    # Ensure departments_needed is a list
    if "departments_needed" not in result or not isinstance(result["departments_needed"], list):
        result["departments_needed"] = _infer_departments(content)

    return result


def _classify_rule_based(content: str) -> dict:
    """Rule-based fallback classifier. Supports Spanish and English."""
    content_lower = content.lower()

    # Heuristics for valid RFP — bilingual (ES + EN)
    rfp_indicators = [
        # Spanish
        r"(solicitud\s+de\s+propuesta|rfp|propuesta|servicio\s+de\s+catering|concesión|concesion|co-branded|contrato)",
        r"(comensales|cubiertos|empleados|personas)\s*(estimados|diarios|semanales)?",
        r"(fecha\s*(límite|limite|maxima|tope)|responder\s+a\s+más\s+tardar|deadline)",
        r"(presupuesto|budget|rango|valor\s+estimado|costos?\s+estimados)",
        # English
        r"(request\s+for\s+proposal|rfp|proposal|catering|concession|co-branded|contract)",
        r"(estimated\s+(annual\s+)?contract\s+value|budget|annual\s+value|usd)",
        r"(proposal\s+due\s+date|deadline|submission\s+date|due\s+date|respond\s+by)",
        r"(scope\s+of\s+work|services\s+requested|statement\s+of\s+work)",
    ]

    # Indicators for rejection — bilingual (ES + EN)
    invalid_indicators = [
        r"(franquicia|información\s+general|requisitos\s+y\s+costos|abrir\s+un\s+restaurante)",
        r"(sin\s+(alcance|presupuesto|fecha|límite|limite))",
        r"(franchise|general\s+information|franchise\s+inquiry|opening\s+a\s+restaurant)",
        r"(without\s+(scope|budget|deadline))",
    ]

    valid_score = sum(1 for pat in rfp_indicators if re.search(pat, content_lower))
    invalid_score = sum(1 for pat in invalid_indicators if re.search(pat, content_lower))

    is_valid = valid_score >= 2 and invalid_score == 0

    # Extract basic metadata with regex — bilingual
    metadata: dict = {}
    if is_valid:
        metadata["client_name"] = (
            _extract_first(r"(?:empresa|razón\s+social|nombre\s*(?:comercial)?)[:\s]+(.+)", content)
            or _extract_first(r"(?:issuing\s+organization|company|organization|client)[:\s]+(.+)", content)
        )
        metadata["location"] = (
            _extract_first(r"(?:dirección|direccion|ubicación|ubicacion)[:\s]+(.+)", content)
            or _extract_first(r"(?:location|address)[:\s]+(.+)", content)
        )
        metadata["service_type"] = (
            _extract_first(
                r"(?:tipo\s+de\s+)?servicio\s+(?:solicitado|requerido)[:\s]*\n+(.+?)(?:\n##|\Z)", content
            )
            or _extract_first(
                r"(?:tipo\s+de\s+)?servicio\s+(?:solicitado|requerido)[:\s]+(.+)", content
            )
            or _extract_first(
                r"(?:scope\s+of\s+work|services\s+requested)[:\s]*\n+(.+?)(?:\n\d+\.|\Z)", content
            )
            or _extract_first(
                r"(?:scope\s+of\s+work|services\s+requested)[:\s]+(.+)", content
            )
        )
        metadata["deadline"] = (
            _extract_first(r"(?:fecha\s*(?:límite|limite|tope))[:\s]+(.+)", content)
            or _extract_first(r"(?:proposal\s+due\s+date|deadline|due\s+date|submission\s+date)[:\s]+(.+)", content)
        )

    departments = _infer_departments(content) if is_valid else []

    reason = (
        "RFP válida (reglas)" if is_valid else "Documento inválido (reglas)"
    )

    return {
        "is_valid": is_valid,
        "classification_reason": reason,
        "confidence": 0.7 if is_valid else 0.8,
        "metadata": metadata,
        "departments_needed": departments,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_first(pattern: str, text: str) -> Optional[str]:
    """Extract the first regex match group from text."""
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _infer_departments(content: str) -> list[str]:
    """Infer which departments are needed based on content keywords (ES + EN)."""
    content_lower = content.lower()
    departments: list[str] = []

    # marketing casi siempre aplica
    departments.append("marketing")

    if any(kw in content_lower for kw in [
        "cocina", "personal", "montaje", "operativo", "capacidad", "horario",
        "comedor", "instalaciones", "km",
        "kitchen", "staff", "setup", "operational", "capacity", "installation",
    ]):
        departments.append("operaciones")

    if any(kw in content_lower for kw in [
        "insumos", "proveedores", "costos", "volumen", "presupuesto",
        "costo", "precio", "tarifa", "revenue",
        "supplies", "suppliers", "costs", "volume", "budget",
        "pricing", "contract value", "procurement",
    ]):
        departments.append("procurement")

    if any(kw in content_lower for kw in [
        "receta", "menú de autor", "menu de autor",
        "capacitación", "capacitacion", "certificación", "certificacion",
        "entrenamiento", "training", "nuevo plato", "personalizado",
        "signature menu", "new recipe", "certification", "staff training",
    ]):
        departments.append("training")

    return departments
