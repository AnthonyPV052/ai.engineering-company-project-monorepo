"""Evaluator agents for Part 2 of the RFP intake pipeline.

Three evaluators run in parallel over each generated department section:
- Readability: uses py-readability-metrics
- Relevance: checks that the draft responds to what the RFP asks
- Compliance: checks against the company guidelines from BRIEFING §5

Each evaluator returns an EvaluationResult dict.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("rfp_intake.evaluators")

# ---------------------------------------------------------------------------
# BRIEFING §5 — Compliance rules
# These are the concrete, non-negotiable rules. No subjective judgment.
# ---------------------------------------------------------------------------

COMPLIANCE_RULES: dict[str, dict] = {
    "prices_cop_usd": {
        "id": "prices_cop_usd",
        "description": "Todo precio debe expresarse en COP y en USD.",
        "check": "both_currencies",
    },
    "three_pillars": {
        "id": "three_pillars",
        "description": (
            "Toda propuesta debe mencionar los tres pilares de la marca: "
            "calidad consistente, experiencia cálida, velocidad de servicio."
        ),
        "check": "brand_pillars",
    },
    "min_setup_days": {
        "id": "min_setup_days",
        "description": (
            "Ninguna sección puede prometer tiempos de montaje/entrega "
            "menores a 10 días hábiles."
        ),
        "check": "setup_days",
    },
    "no_competitors": {
        "id": "no_competitors",
        "description": "Ninguna propuesta puede mencionar nombres de competidores.",
        "check": "competitors",
    },
    "offer_validity": {
        "id": "offer_validity",
        "description": (
            "Toda propuesta debe incluir un período de validez de la oferta "
            "(30 días desde su emisión)."
        ),
        "check": "offer_validity",
    },
    "ceo_threshold": {
        "id": "ceo_threshold",
        "description": (
            "Contratos estimados por encima de 50.000 USD/año requieren "
            "aprobación adicional del CEO."
        ),
        "check": "ceo_threshold",
    },
}

# Known competitor names (ES/EN)
_COMPETITOR_NAMES = [
    "mcdonald", "mcdonald's", "burger king", "kfc", "subway", "domino",
    "pizza hut", "starbucks", "dunkin", "chipotle", "wendy", "taco bell",
    "cocacola", "pepsi", "nestlé", "nestle", "unilever",
    "crepes & waffles", "frisby", "el corral", "archies",
    "kokoriko", "papa john", "little caesars",
]

_BRAND_PILLARS = [
    "calidad consistente",
    "experiencia cálida",
    "velocidad de servicio",
]


# ---------------------------------------------------------------------------
# Compliance check implementations
# ---------------------------------------------------------------------------


def _check_both_currencies(text: str) -> tuple[bool, list[str]]:
    """Check that prices appear in both COP and USD."""
    violations: list[str] = []

    has_cop = bool(re.search(r'(?:COP|pesos\s+colombianos|\$\s*[\d,]+\.?\d*\s*COP)', text, re.IGNORECASE))
    has_usd = bool(re.search(r'(?:USD|dólares|\$\s*[\d,]+\.?\d*\s*(?:USD|usd)?)', text, re.IGNORECASE))

    if not has_cop and not has_usd:
        violations.append("No se encontraron precios ni en COP ni en USD.")
    elif not has_cop:
        violations.append("Faltan precios expresados en COP (pesos colombianos).")
    elif not has_usd:
        violations.append("Faltan precios expresados en USD (dólares).")

    return len(violations) == 0, violations


def _check_brand_pillars(text: str) -> tuple[bool, list[str]]:
    """Check that all three brand pillars are mentioned."""
    text_lower = text.lower()
    missing: list[str] = []

    for pillar in _BRAND_PILLARS:
        if pillar not in text_lower:
            missing.append(pillar)

    violations = [f"Falta pilar de marca: '{p}'" for p in missing]
    return len(violations) == 0, violations


def _check_setup_days(text: str) -> tuple[bool, list[str]]:
    """Check that no section promises setup/delivery under 10 business days."""
    violations: list[str] = []
    text_lower = text.lower()

    # Look for patterns like "X días" or "X dias" near montaje/entrega/setup
    patterns = [
        r"(\d+)\s*d[ií]as\s*(?:h[aá]biles\s*)?(?:de\s*)?(?:montaje|entrega|instalaci[oó]n|set-up|setup)",
        r"(?:montaje|entrega|instalaci[oó]n|set-up|setup)(?:\s*de)?\s*(\d+)\s*d[ií]as",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text_lower):
            days = int(match.group(1))
            if days < 10:
                violations.append(
                    f"Promete {days} días hábiles de montaje/entrega "
                    f"(mínimo requerido: 10)."
                )

    # Also check explicit promises like "en menos de X días"
    promesa_patterns = [
        r"menos\s+de\s+(\d+)\s*d[ií]as",
        r"en\s+s[oó]lo\s+(\d+)\s*d[ií]as",
        r"(\d+)\s*d[ií]as\s*(?:h[aá]biles\s*)?\s*(?:despu[eé]s|para)",
    ]
    for pattern in promesa_patterns:
        for match in re.finditer(pattern, text_lower):
            days = int(match.group(1))
            if days < 10:
                # Check it's contextually about setup/installation
                context_start = max(0, match.start() - 50)
                context_end = min(len(text_lower), match.end() + 50)
                context = text_lower[context_start:context_end]
                if any(w in context for w in ["montaje", "entrega", "instalación", "instalacion", "set-up", "setup", "servicio", "entrega"]):
                    violations.append(
                        f"Promete '{match.group()}' ({days} días) en contexto "
                        f"de entrega/montaje — mínimo 10 días hábiles."
                    )

    return len(violations) == 0, violations


def _check_competitors(text: str) -> tuple[bool, list[str]]:
    """Check that no competitor names are mentioned."""
    text_lower = text.lower()
    violations: list[str] = []

    for competitor in _COMPETITOR_NAMES:
        if competitor in text_lower:
            violations.append(f"Menciona al competidor: '{competitor}'.")

    return len(violations) == 0, violations


def _check_offer_validity(text: str) -> tuple[bool, list[str]]:
    """Check that the proposal includes an offer validity period of 30 days."""
    text_lower = text.lower()
    violations: list[str] = []

    # Check for validity period mentions
    validity_patterns = [
        # "validez ... 30 días" (any phrasing: "validez de la oferta", "tiene validez de", "**Validez:**" etc)
        r"validez[^.]*?(\d+)\s*d[ií]as",
        # "30 días de validez" / "30 días de vigencia"
        r"(\d+)\s*d[ií]as\s*(?:de\s*)?(?:validez|vigencia)",
        # "oferta válida por/hasta" / "válido por" / "válida por" (handles bold too)
        r"v[áa]lid[ao]\s+(?:por|hasta)",
        # generic "validez por 30 días" or "vigencia de 30 días"
        r"(?:v[áa]lido?|vigencia|validez)\s+(?:por|de)\s+(\d+)\s*d[ií]as",
    ]

    found_validity = False
    for pattern in validity_patterns:
        if re.search(pattern, text_lower):
            found_validity = True
            break

    if not found_validity:
        violations.append(
            "No se encontró período de validez de la oferta. "
            "Debe incluir 30 días desde su emisión."
        )

    return len(violations) == 0, violations


def _check_ceo_threshold(text: str, annual_estimated_usd: float | None) -> tuple[bool, list[str]]:
    """Flag if the contract exceeds 50K USD and CEO approval is needed."""
    violations: list[str] = []
    if annual_estimated_usd is not None and annual_estimated_usd > 50_000:
        violations.append(
            f"Valor estimado (${annual_estimated_usd:,.0f} USD/año) "
            f"supera USD 50,000/año. Requiere aprobación adicional del CEO."
        )
    return len(violations) == 0, violations


# ---------------------------------------------------------------------------
# Compliance evaluator
# ---------------------------------------------------------------------------


def evaluate_compliance(draft_content: str, metadata: dict) -> dict:
    """Evaluate compliance against BRIEFING §5 rules.

    Returns:
        {
            "pass": bool,
            "rule_ids": [str, ...],        # IDs of all rules checked
            "violations": [str, ...],       # Human-readable violation descriptions
            "details": str,                 # Summary
        }
    """
    violations: list[str] = []
    checked_rules: list[str] = []

    for rule_id, rule in COMPLIANCE_RULES.items():
        checked_rules.append(rule_id)
        check_type = rule["check"]

        if check_type == "both_currencies":
            passed, rule_violations = _check_both_currencies(draft_content)
            violations.extend(rule_violations)
        elif check_type == "brand_pillars":
            passed, rule_violations = _check_brand_pillars(draft_content)
            violations.extend(rule_violations)
        elif check_type == "setup_days":
            passed, rule_violations = _check_setup_days(draft_content)
            violations.extend(rule_violations)
        elif check_type == "competitors":
            passed, rule_violations = _check_competitors(draft_content)
            violations.extend(rule_violations)
        elif check_type == "offer_validity":
            passed, rule_violations = _check_offer_validity(draft_content)
            violations.extend(rule_violations)
        elif check_type == "ceo_threshold":
            annual_usd = metadata.get("annual_estimated_usd") if metadata else None
            passed, rule_violations = _check_ceo_threshold(draft_content, annual_usd)
            violations.extend(rule_violations)

    overall_pass = len(violations) == 0

    return {
        "pass": overall_pass,
        "rule_ids": checked_rules,
        "violations": violations,
        "details": "Cumplimiento OK." if overall_pass else f"Incumplimientos: {'; '.join(violations)}",
    }


# ---------------------------------------------------------------------------
# Readability evaluator
# ---------------------------------------------------------------------------


def evaluate_readability(draft_content: str) -> dict:
    """Evaluate readability using py-readability-metrics.

    Returns:
        {
            "pass": bool,               # True if acceptable readability
            "score": float,             # Flesch-Kincaid grade level
            "details": str,
        }
    """
    try:
        from data.pipelines.rfp_intake.converter import compute_readability_metrics
        metrics = compute_readability_metrics(draft_content)

        grade = metrics.get("flesch_kincaid_grade")
        words = metrics.get("word_count")

        if grade is None or words is None or words < 20:
            return {
                "pass": False,
                "score": 0.0,
                "details": "Texto demasiado corto para evaluar legibilidad.",
            }

        # Acceptable: grade level between 6 and 14 (high school to college)
        # This is a reasonable range for business proposals
        acceptable = 6.0 <= grade <= 14.0
        return {
            "pass": acceptable,
            "score": round(grade, 2),
            "details": (
                f"Grado Flesch-Kincaid: {grade:.1f}. "
                f"{'Legibilidad aceptable.' if acceptable else 'Fuera del rango recomendado (6-14).'}"
            ),
        }

    except Exception as exc:
        logger.warning("Readability evaluation failed: %s", exc)
        return {
            "pass": True,  # Don't block on readability failure
            "score": 0.0,
            "details": f"No se pudo evaluar legibilidad: {exc}",
        }


# ---------------------------------------------------------------------------
# Relevance evaluator
# ---------------------------------------------------------------------------


def evaluate_relevance(draft_content: str, handoff_payload: dict, department_id: str) -> dict:
    """Evaluate whether the draft responds to what the RFP asks.

    Uses the key_aspects from Part 1 to check coverage.

    Returns:
        {
            "pass": bool,
            "missing_aspects": [str, ...],
            "details": str,
        }
    """
    aspects = handoff_payload.get("key_aspects_by_department", {}).get(department_id, "")
    open_questions = handoff_payload.get("open_questions", {}).get(department_id, [])
    meta = handoff_payload.get("metadata", handoff_payload)

    missing: list[str] = []

    # Check that the draft covers client name
    client_name = meta.get("client_name", "")
    if client_name and client_name.lower() not in draft_content.lower():
        missing.append(f"No menciona al cliente '{client_name}'.")

    # Check that the draft covers service type
    service_type = meta.get("service_type", "")
    if service_type and service_type.lower() not in draft_content.lower():
        # Try partial match
        service_words = service_type.lower().split()
        if not any(word in draft_content.lower() for word in service_words if len(word) > 4):
            missing.append(f"No refleja adecuadamente el tipo de servicio '{service_type}'.")

    # Check coverage of key aspects
    if aspects:
        # Extract key sentences from aspects
        key_sentences = [s.strip() for s in aspects.split("\n") if s.strip() and len(s.strip()) > 20]
        # This is a simple heuristic — check if at least some aspects are reflected
        aspect_covered = sum(1 for sentence in key_sentences if any(
            phrase in draft_content.lower()
            for phrase in sentence.lower().split()
            if len(phrase) > 5
        ))

        if len(key_sentences) > 0 and aspect_covered < max(1, len(key_sentences) // 3):
            missing.append(
                "El borrador no cubre adecuadamente los aspectos clave "
                "identificados en el análisis de la RFP."
            )

    # Check open questions — if they exist, draft should acknowledge them
    if open_questions:
        ack_phrases = [
            "falta", "pendiente", "información adicional",
            "no disponible", "por confirmar",
        ]
        has_acknowledgment = any(
            phrase in draft_content.lower()
            for phrase in ack_phrases
        )
        if not has_acknowledgment:
            missing.append(
                "Hay preguntas abiertas del análisis que no se reconocen "
                "en el borrador."
            )

    overall_pass = len(missing) == 0

    return {
        "pass": overall_pass,
        "missing_aspects": missing,
        "details": "Pertinencia OK." if overall_pass else f"Aspectos faltantes: {'; '.join(missing)}",
    }


# ---------------------------------------------------------------------------
# Main evaluation orchestrator
# ---------------------------------------------------------------------------


def evaluate_section(
    draft_content: str,
    handoff_payload: dict,
    department_id: str,
) -> dict:
    """Run all three evaluators and produce a consolidated EvaluationResult.

    Returns:
        {
            "department_id": str,
            "readability": {"pass": bool, "score": float, "details": str},
            "relevance": {"pass": bool, "missing_aspects": [str], "details": str},
            "compliance": {"pass": bool, "rule_ids": [str], "violations": [str], "details": str},
            "overall_pass": bool,
            "feedback_for_generator": str,   # Concrete, actionable feedback
        }
    """
    metadata = handoff_payload.get("metadata", handoff_payload)

    # Run evaluators
    readability_result = evaluate_readability(draft_content)
    relevance_result = evaluate_relevance(draft_content, handoff_payload, department_id)
    compliance_result = evaluate_compliance(draft_content, metadata)

    overall_pass = (
        readability_result["pass"]
        and relevance_result["pass"]
        and compliance_result["pass"]
    )

    # Build consolidated feedback
    feedback_parts: list[str] = []

    if not readability_result["pass"]:
        feedback_parts.append(f"[Legibilidad] {readability_result['details']}")

    if not relevance_result["pass"]:
        for asp in relevance_result["missing_aspects"]:
            feedback_parts.append(f"[Pertinencia] {asp}")

    if not compliance_result["pass"]:
        for v in compliance_result["violations"]:
            feedback_parts.append(f"[Cumplimiento] {v}")

    feedback = "\n".join(feedback_parts) if feedback_parts else "Sección aprobada."

    return {
        "department_id": department_id,
        "readability": readability_result,
        "relevance": relevance_result,
        "compliance": compliance_result,
        "overall_pass": overall_pass,
        "feedback_for_generator": feedback,
    }


# ---------------------------------------------------------------------------
# Clean evaluation function (no handoff_payload dependency for standalone use)
# ---------------------------------------------------------------------------


def clean_evaluate_section(
    draft_content: str,
    metadata: dict | None = None,
    key_aspects: str = "",
    open_questions: list[str] | None = None,
) -> dict:
    """Standalone evaluation without needing the full handoff_payload.

    Useful for testing.
    """
    if metadata is None:
        metadata = {}
    if open_questions is None:
        open_questions = []

    # Build a minimal handoff_payload-like dict
    payload = {
        "metadata": metadata,
        "key_aspects_by_department": {"_": key_aspects},
        "open_questions": {"_": open_questions},
    }

    return evaluate_section(draft_content, payload, "_")