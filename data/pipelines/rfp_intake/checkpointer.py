"""Checkpointer for RFP pipeline interrupt/resume.

Uses PostgreSQL (via SQLModel) to persist checkpoints keyed by thread_id.
Thread IDs are namespaced: rfp-{ticket_id} for global or rfp-{ticket_id}:{department}
for per-department branches.

This allows:
- Tickets to be checkpointed independently (no cross-ticket interference)
- Per-department branches to be checkpointed separately (only the waiting branch blocks)
- Resume to restore exactly where execution left off
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("rfp_intake.checkpointer")

# Ensure API module is importable
API_DIR = Path(__file__).resolve().parents[3] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


def make_thread_id(ticket_id: str, department_id: Optional[str] = None) -> str:
    """Create a namespaced thread_id for checkpoint scoping.

    Args:
        ticket_id: The ticket UUID.
        department_id: Optional department branch.

    Returns:
        e.g. "rfp-abc123" or "rfp-abc123:marketing"
    """
    if department_id:
        return f"rfp-{ticket_id}:{department_id}"
    return f"rfp-{ticket_id}"


def parse_thread_id(thread_id: str) -> tuple[str, Optional[str]]:
    """Parse a thread_id back into ticket_id and optional department_id.

    Returns:
        (ticket_id, department_id_or_None)
    """
    if ":" in thread_id:
        parts = thread_id.split(":", 1)
        # rfp-{ticket_id}:{department}
        ticket_id = parts[0][4:] if parts[0].startswith("rfp-") else parts[0]
        return ticket_id, parts[1]
    ticket_id = thread_id[4:] if thread_id.startswith("rfp-") else thread_id
    return ticket_id, None


def save_checkpoint(
    ticket_id: str,
    node_name: str,
    state_snapshot: dict,
    department_id: Optional[str] = None,
) -> str:
    """Save a checkpoint for the given thread scope.

    Args:
        ticket_id: The ticket UUID.
        node_name: The graph node where this checkpoint is saved.
        state_snapshot: The full state dict to persist.
        department_id: Optional branch department.

    Returns:
        The thread_id used.
    """
    thread_id = make_thread_id(ticket_id, department_id)
    snapshot_json = json.dumps(state_snapshot, indent=2, ensure_ascii=False, default=str)

    try:
        from sqlmodel import Session
        from database import _get_engine
        from rfp_models import RFPCheckpoint

        engine = _get_engine()
        with Session(engine) as db:
            # Create a new checkpoint; the latest non-resumed one is the active one.
            ckpt = RFPCheckpoint(
                thread_id=thread_id,
                ticket_id=ticket_id,
                department_id=department_id,
                node_name=node_name,
                state_snapshot=snapshot_json,
                is_resumed=False,
            )
            db.add(ckpt)
            db.commit()

        logger.info(
            "[%s] Checkpoint saved: node=%s thread=%s",
            ticket_id, node_name, thread_id,
        )
    except Exception as exc:
        logger.warning("[%s] Failed to save checkpoint: %s", ticket_id, exc)
        # Non-fatal — checkpointing is best-effort

    return thread_id


def load_checkpoint(
    ticket_id: str,
    department_id: Optional[str] = None,
) -> Optional[dict]:
    """Load the latest non-resumed checkpoint for a thread scope.

    Args:
        ticket_id: The ticket UUID.
        department_id: Optional branch department.

    Returns:
        The state dict if a checkpoint exists, else None.
    """
    thread_id = make_thread_id(ticket_id, department_id)

    try:
        from sqlmodel import Session, select
        from database import _get_engine
        from rfp_models import RFPCheckpoint

        engine = _get_engine()
        with Session(engine) as db:
            result = db.exec(
                select(RFPCheckpoint)
                .where(
                    RFPCheckpoint.thread_id == thread_id,
                    RFPCheckpoint.is_resumed == False,
                )
                .order_by(RFPCheckpoint.created_at.desc())
                .limit(1)
            ).first()

            if result is None:
                logger.info("[%s] No checkpoint found for thread=%s", ticket_id, thread_id)
                return None

            state = json.loads(result.state_snapshot)
            logger.info(
                "[%s] Checkpoint loaded: node=%s thread=%s",
                ticket_id, result.node_name, thread_id,
            )
            return state

    except Exception as exc:
        logger.warning("[%s] Failed to load checkpoint: %s", ticket_id, exc)
        return None


def mark_checkpoint_resumed(
    ticket_id: str,
    department_id: Optional[str] = None,
) -> bool:
    """Mark the latest checkpoint as resumed (consumed).

    Args:
        ticket_id: The ticket UUID.
        department_id: Optional branch department.

    Returns:
        True if a checkpoint was marked, False otherwise.
    """
    thread_id = make_thread_id(ticket_id, department_id)

    try:
        from datetime import datetime, timezone
        from sqlmodel import Session, select
        from database import _get_engine
        from rfp_models import RFPCheckpoint

        engine = _get_engine()
        with Session(engine) as db:
            result = db.exec(
                select(RFPCheckpoint)
                .where(
                    RFPCheckpoint.thread_id == thread_id,
                    RFPCheckpoint.is_resumed == False,
                )
                .order_by(RFPCheckpoint.created_at.desc())
                .limit(1)
            ).first()

            if result is None:
                return False

            result.is_resumed = True
            result.resumed_at = datetime.now(timezone.utc)
            db.add(result)
            db.commit()

        logger.info("[%s] Checkpoint marked resumed: thread=%s", ticket_id, thread_id)
        return True

    except Exception as exc:
        logger.warning("[%s] Failed to mark checkpoint resumed: %s", ticket_id, exc)
        return False


def clear_checkpoints(
    ticket_id: str,
    department_id: Optional[str] = None,
) -> None:
    """Clear all checkpoints for a thread scope (e.g., after completion)."""
    thread_id = make_thread_id(ticket_id, department_id)

    try:
        from sqlmodel import Session, delete
        from database import _get_engine
        from rfp_models import RFPCheckpoint

        engine = _get_engine()
        with Session(engine) as db:
            stmt = delete(RFPCheckpoint).where(
                RFPCheckpoint.thread_id == thread_id
            )
            db.exec(stmt)
            db.commit()

        logger.info("[%s] Checkpoints cleared: thread=%s", ticket_id, thread_id)
    except Exception as exc:
        logger.warning("[%s] Failed to clear checkpoints: %s", ticket_id, exc)