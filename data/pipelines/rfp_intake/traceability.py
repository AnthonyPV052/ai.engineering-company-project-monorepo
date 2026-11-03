"""Traceability: record every node execution in the RFP pipeline.

Each node execution logs: agent, input, output, timestamp, and department branch.
This enables full reconstruction of what happened in any pipeline run.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("rfp_intake.traceability")

# Ensure API module is importable
API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


def record_execution(
    ticket_id: str,
    node_name: str,
    agent: str,
    input_data: Any = None,
    output_data: Any = None,
    department_id: Optional[str] = None,
) -> None:
    """Record a node execution in the trace log.

    Args:
        ticket_id: The ticket UUID.
        node_name: The graph node name.
        agent: The agent identifier (e.g., "generator:marketing", "arbiter:cost-vs-feasibility").
        input_data: Serializable input to the node.
        output_data: Serializable output from the node.
        department_id: Optional branch department.
    """
    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPNodeExecution

        engine = _get_engine()
        with Session(engine) as db:
            exec_record = RFPNodeExecution(
                ticket_id=ticket_id,
                node_name=node_name,
                agent=agent,
                input_snapshot=_safe_json(input_data, max_len=2000),
                output_snapshot=_safe_json(output_data, max_len=5000),
                department_id=department_id,
            )
            db.add(exec_record)
            db.commit()

        logger.debug("[%s] Trace: %s/%s recorded", ticket_id, node_name, agent)
    except Exception as exc:
        logger.warning("[%s] Failed to record trace: %s", ticket_id, exc)


def _safe_json(data: Any, max_len: int = 5000) -> Optional[str]:
    """Serialize data to JSON, truncating if too long."""
    if data is None:
        return None
    try:
        serialized = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        if len(serialized) > max_len:
            serialized = serialized[:max_len] + "\n... [truncated]"
        return serialized
    except (TypeError, ValueError):
        return str(data)[:max_len]


def get_trace_for_ticket(ticket_id: str) -> list[dict]:
    """Retrieve the full execution trace for a ticket.

    Returns list of dicts ordered by creation time.
    """
    try:
        from sqlmodel import Session, select
        from database import _get_engine
        from rfp_models import RFPNodeExecution

        engine = _get_engine()
        with Session(engine) as db:
            results = db.exec(
                select(RFPNodeExecution)
                .where(RFPNodeExecution.ticket_id == ticket_id)
                .order_by(RFPNodeExecution.id.asc())
            ).all()

            return [
                {
                    "id": r.id,
                    "node_name": r.node_name,
                    "agent": r.agent,
                    "department_id": r.department_id,
                    "input_snapshot": r.input_snapshot,
                    "output_snapshot": r.output_snapshot,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in results
            ]
    except Exception as exc:
        logger.warning("[%s] Failed to get trace: %s", ticket_id, exc)
        return []