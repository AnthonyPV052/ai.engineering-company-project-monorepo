"""Arbitration node for Part 3 of the RFP pipeline.

Handles conflict detection and resolution using FIXED arbiters (not LLM voting).
Dispatches on three trigger IDs defined in the BRIEFING:

1. cost-vs-feasibility: Procurement cost vs Operaciones pricing mismatch
   → Arbiter: Camila Ospina (Marketing, ticket owner)
   → Resolution: raise price or reduce scope

2. setup-sla-breach: Any section promises <10 business days setup
   → Arbiter: Felipe Guerrero (Operaciones) rejects; Camila escalates
   → Resolution: force request_changes until >=10 business days everywhere

3. ceo-threshold: Annual value > $50K USD and CEO approval pending
   → Arbiter: Mariana Restrepo (CEO)
   → Resolution: block ultimate synthesizer until CEO approves; reject path if CEO rejects
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("rfp_intake.arbitration")

# Ensure API module is importable
API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


def detect_conflicts(state: dict) -> list[dict]:
    """Scan the current state for any arbitration triggers.

    Args:
        state: The current pipeline state dict (must contain handoff_payload,
               evaluations, sections, etc.)

    Returns:
        List of conflict dicts, each with:
        - trigger_id: one of CONFLICT_TRIGGER_*
        - description: human-readable explanation
        - departments_involved: list of department_ids
        - arbiter: name of the fixed arbiter
        - auto_resolve: True if this can be auto-resolved deterministically
    """
    conflicts: list[dict] = []

    # --- Load state ---
    handoff = state.get("handoff_payload", {})
    if isinstance(handoff, str):
        try:
            handoff = json.loads(handoff)
        except (json.JSONDecodeError, TypeError):
            handoff = {}

    sections = state.get("sections", [])
    evaluations = state.get("evaluations", state.get("evaluation_results", {}))
    annual_usd = handoff.get("annual_estimated_usd", state.get("annual_estimated_usd"))
    drafts = state.get("drafts", {})

    # --- 1. cost-vs-feasibility ---
    # Check if procurement estimated cost vs operaciones pricing are misaligned
    procurement_eval = evaluations.get("procurement", {})
    operaciones_eval = evaluations.get("operaciones", {})

    # Determine if there's a mismatch between what Procurement estimates
    # and what Operaciones prices per event/cover
    if procurement_eval and operaciones_eval:
        # Simple heuristic: check if procurement flagged cost concerns
        # and operaciones suggests pricing that doesn't cover costs
        proc_compliance = procurement_eval.get("compliance", {})
        op_compliance = operaciones_eval.get("compliance", {})

        # Check draft content for pricing vs cost mentions
        proc_draft = drafts.get("procurement", "")
        op_draft = drafts.get("operaciones", "")

        cost_vs_price_conflict = _detect_cost_vs_price_mismatch(proc_draft, op_draft, procurement_eval, operaciones_eval)
        if cost_vs_price_conflict:
            conflicts.append({
                "trigger_id": "cost-vs-feasibility",
                "description": cost_vs_price_conflict,
                "departments_involved": ["procurement", "operaciones"],
                "arbiter": "Camila Ospina",
                "auto_resolve": False,
            })

    # --- 2. setup-sla-breach ---
    # Check every draft + evaluation for setup/ delivery under 10 business days
    sla_violations = _detect_setup_sla_breaches(drafts, evaluations, sections)
    if sla_violations:
        violations_text = "; ".join(
            v["match"] if isinstance(v, dict) else str(v)
            for v in sla_violations
        )
        departments_with_violations = list(set(
            v.get("department", "unknown") for v in sla_violations
        ))
        conflicts.append({
            "trigger_id": "setup-sla-breach",
            "description": f"Setup/delivery under 10 business days detected: {violations_text}",
            "departments_involved": departments_with_violations or ["marketing", "operaciones", "procurement", "training"],
            "arbiter": "Felipe Guerrero",
            "auto_resolve": True,  # Can auto-force request_changes
        })

    # --- 3. ceo-threshold ---
    # Check if annual estimated value > $50K USD and CEO hasn't approved
    if annual_usd is not None and float(annual_usd) > 50000:
        # Check if CEO already approved
        ceo_approved = state.get("ceo_approved", False)
        if not ceo_approved:
            conflicts.append({
                "trigger_id": "ceo-threshold",
                "description": (
                    f"Annual estimated value USD {float(annual_usd):,.2f} exceeds "
                    f"$50,000 threshold. CEO (Mariana Restrepo) approval required."
                ),
                "departments_involved": [],
                "arbiter": "Mariana Restrepo",
                "auto_resolve": False,  # Must wait for human CEO
            })

    return conflicts


def _detect_cost_vs_price_mismatch(
    proc_draft: str, op_draft: str,
    proc_eval: dict, op_eval: dict,
) -> Optional[str]:
    """Detect if procurement costs don't align with operaciones pricing."""
    import re

    reasons = []

    # Extract numbers from procurement draft (costs)
    proc_numbers = re.findall(r'(?:USD|usd|\$)\s*([\d,]+\.?\d*)', proc_draft)
    op_numbers = re.findall(r'(?:USD|usd|\$)\s*([\d,]+\.?\d*)', op_draft)

    proc_values = []
    for n in proc_numbers:
        try:
            proc_values.append(float(n.replace(",", "")))
        except ValueError:
            pass

    op_values = []
    for n in op_numbers:
        try:
            op_values.append(float(n.replace(",", "")))
        except ValueError:
            pass

    # If procurement mentions costs but operaciones prices don't cover them
    if proc_values and op_values:
        max_cost = max(proc_values)
        min_price = min(op_values)
        if max_cost > min_price * 0.85:  # costs >85% of pricing = thin margin
            reasons.append(
                f"Procurement max cost (${max_cost:,.0f}) is >85% of "
                f"Operaciones min price (${min_price:,.0f}). Margin too thin."
            )

    # Check evaluation compliance for cost/price misalignment
    proc_compliance = proc_eval.get("compliance", {})
    op_compliance = op_eval.get("compliance", {})

    if proc_compliance.get("pass") is False or op_compliance.get("pass") is False:
        reasons.append("One or both department evaluations failed compliance for pricing.")

    return " | ".join(reasons) if reasons else None


def _detect_setup_sla_breaches(
    drafts: dict, evaluations: dict, sections: list
) -> list[dict]:
    """Detect any setup/ delivery promises under 10 business days."""
    import re

    violations = []

    # Patterns that indicate a time promise
    patterns = [
        r"(\d+)\s*d[ií]as\s*(?:h[aá]biles\s*)?(?:de\s*)?(?:montaje|entrega|instalaci[oó]n|set-up|setup)",
        r"(?:montaje|entrega|instalaci[oó]n|set-up|setup)(?:\s*de)?\s*(\d+)\s*d[ií]as",
        r"(?:montaje|entrega|instalaci[oó]n|set-up|setup)\s+en\s+(\d+)\s*d[ií]as",
        r"en\s+(\d+)\s*d[ií]as\s*(?:h[aá]biles\s*)?(?:de\s*)?(?:montaje|entrega|instalaci[oó]n|set-up|setup)",
        r"menos\s+de\s+(\d+)\s*d[ií]as",
        r"en\s+s[oó]lo\s+(\d+)\s*d[ií]as",
    ]

    # Check drafts
    for dept_id, draft in drafts.items():
        if not draft:
            continue
        text_lower = draft.lower()
        for pattern in patterns:
            for match in re.finditer(pattern, text_lower):
                days = int(match.group(1))
                if days < 10:
                    context_start = max(0, match.start() - 30)
                    context_end = min(len(text_lower), match.end() + 30)
                    context = text_lower[context_start:context_end]
                    violations.append({
                        "department": dept_id,
                        "match": match.group(),
                        "days": days,
                        "context": context,
                    })

    # Also check sections from handoff
    for section in (sections or []):
        content = section.get("draft_content", "")
        if not content:
            continue
        text_lower = content.lower()
        for pattern in patterns:
            for match in re.finditer(pattern, text_lower):
                days = int(match.group(1))
                if days < 10:
                    violations.append({
                        "department": section.get("department_id", "unknown"),
                        "match": match.group(),
                        "days": days,
                        "context": text_lower[
                            max(0, match.start() - 30):min(len(text_lower), match.end() + 30)
                        ],
                    })

    return violations


def resolve_conflict_auto(
    trigger_id: str,
    conflict: dict,
    state: dict,
) -> dict:
    """Auto-resolve a conflict that has a deterministic resolution.

    Only setup-sla-breach is auto-resolvable (force request_changes).
    Other triggers require human intervention.

    Returns:
        Resolution dict with:
        - resolution: "approve" | "reject" | "request_changes"
        - note: Explanation
        - state_updates: dict of state changes to apply
    """
    if trigger_id == "setup-sla-breach":
        # Auto-resolve: force request_changes on violating departments
        depts = conflict.get("departments_involved", [])
        return {
            "resolution": "request_changes",
            "note": (
                f"Auto-resolved: Section(s) promise setup/delivery under 10 business days. "
                f"Forcing request_changes on: {', '.join(depts)}. "
                f"Felipe Guerrero (Operaciones) rejects; Camila escalates if needed."
            ),
            "state_updates": {
                "arbitration_requested_changes": depts,
                "status": "en_evaluacion",
            },
        }

    # Default: cannot auto-resolve
    return {
        "resolution": "pending",
        "note": f"Trigger {trigger_id} requires human arbitration.",
        "state_updates": {},
    }


def record_arbitration(
    ticket_id: str,
    trigger_id: str,
    arbiter: str,
    description: str,
    resolution: str,
    departments_involved: Optional[list[str]] = None,
    resolved_by: Optional[str] = None,
) -> None:
    """Persist an arbitration decision."""
    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPArbitrationRecord

        engine = _get_engine()
        with Session(engine) as db:
            record = RFPArbitrationRecord(
                ticket_id=ticket_id,
                trigger_id=trigger_id,
                arbiter=arbiter,
                departments_involved=json.dumps(departments_involved or [], ensure_ascii=False),
                description=description,
                resolution=resolution,
                resolved_by=resolved_by,
            )
            db.add(record)
            db.commit()

        logger.info("[%s] Arbitration recorded: trigger=%s resolution=%s by=%s",
                     ticket_id, trigger_id, resolution, resolved_by or arbiter)
    except Exception as exc:
        logger.warning("[%s] Failed to record arbitration: %s", ticket_id, exc)