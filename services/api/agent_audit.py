"""Agent action audit logging for Brasaland AI systems.

Provides structured logging and tracing for every action taken by an AI agent:
- What question was asked
- What tools were called and their results
- What documents were retrieved
- What answer was returned
- Which human approvals were triggered

This satisfies:
- NIST AI RMF: Govern (transparency), Detect (monitoring), Respond (forensics)
- OWASP LLM06 — Overreliance (traceability)
- Colombia Ley 1581 (data subject access requests)
- FIPA (incident investigation)

All audit events are written to a structured JSON log file AND emitted
as telemetry events for real-time monitoring.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("api.audit")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_AUDIT_LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "/app/data/audit"))
_AUDIT_LOG_FILE = _AUDIT_LOG_DIR / "agent_audit.jsonl"

_lock = threading.Lock()


def _ensure_log_dir() -> None:
    """Create audit log directory if it doesn't exist."""
    try:
        _AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # Will be handled at write time


# ---------------------------------------------------------------------------
# Audit event types
# ---------------------------------------------------------------------------

AUDIT_EVENT_QUERY_RECEIVED = "query.received"
AUDIT_EVENT_TOOL_CALLED = "tool.called"
AUDIT_EVENT_TOOL_RESULT = "tool.result"
AUDIT_EVENT_RAG_RETRIEVAL = "rag.retrieval"
AUDIT_EVENT_ANSWER_GENERATED = "answer.generated"
AUDIT_EVENT_HUMAN_APPROVAL_REQUESTED = "human.approval.requested"
AUDIT_EVENT_HUMAN_APPROVAL_RESOLVED = "human.approval.resolved"
AUDIT_EVENT_MEMORY_PROPOSAL = "memory.proposal"
AUDIT_EVENT_MEMORY_RESOLVED = "memory.resolved"
AUDIT_EVENT_SECURITY_ALERT = "security.alert"
AUDIT_EVENT_ERROR = "system.error"

# ---------------------------------------------------------------------------
# Audit log writer
# ---------------------------------------------------------------------------


def _write_audit_entry(entry: dict[str, Any]) -> None:
    """Write a single audit entry to the JSONL file.

    Thread-safe: uses a lock to prevent line interleaving.
    """
    _ensure_log_dir()
    entry["_timestamp"] = datetime.now(timezone.utc).isoformat()
    try:
        with _lock:
            with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.error("Failed to write audit entry: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_agent_action(
    event_type: str,
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
    question: str | None = None,
    answer: str | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: str | None = None,
    documents_retrieved: list[dict[str, Any]] | None = None,
    model_name: str | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log an agent action for audit trail.

    Parameters
    ----------
    event_type : str
        One of the ``AUDIT_EVENT_*`` constants.
    session_id : str, optional
        The chat session or user session ID.
    trace_id : str, optional
        The LangGraph trace ID for this turn.
    user_id : str, optional
        The authenticated user who triggered this action.
    question : str, optional
        The user's question or input.
    answer : str, optional
        The agent's answer (truncated to 2000 chars).
    tool_name : str, optional
        Name of the tool called (e.g., ``list_incidents``).
    tool_input : dict, optional
        Parameters passed to the tool.
    tool_output : str, optional
        Truncated output from the tool.
    documents_retrieved : list, optional
        Documents retrieved from RAG (titles/sources only, not full text).
    model_name : str, optional
        The LLM model used for generation.
    latency_ms : float, optional
        Execution time for this action.
    error : str, optional
        Error message if the action failed.
    metadata : dict, optional
        Additional context about the action.
    """
    entry: dict[str, Any] = {
        "event_type": event_type,
        "session_id": session_id,
        "trace_id": trace_id,
        "user_id": user_id,
    }

    # Truncate potentially large fields
    if question:
        entry["question"] = question[:500]
    if answer:
        entry["answer"] = answer[:2000]
    if tool_name:
        entry["tool_name"] = tool_name
    if tool_input:
        entry["tool_input"] = {k: str(v)[:200] for k, v in tool_input.items()}
    if tool_output:
        entry["tool_output"] = tool_output[:1000]
    if documents_retrieved:
        # Log only metadata, not full document text
        entry["documents_retrieved"] = [
            {
                "source": d.get("source_document", d.get("source", "unknown"))[:200],
                "section": d.get("section", "")[:100],
                "text_length": len(d.get("text", "")),
            }
            for d in documents_retrieved[:20]  # Max 20 docs per entry
        ]
    if model_name:
        entry["model_name"] = model_name
    if latency_ms is not None:
        entry["latency_ms"] = round(latency_ms, 1)
    if error:
        entry["error"] = error[:500]
    if metadata:
        entry["metadata"] = metadata

    _write_audit_entry(entry)

    # Also log at INFO level for structured logging consumers
    logger.info(
        "AGENT_AUDIT event=%s session=%s trace=%s user=%s tool=%s latency=%.1fms",
        event_type,
        session_id or "-",
        trace_id or "-",
        user_id or "-",
        tool_name or "-",
        latency_ms or 0,
    )


def log_security_alert(
    alert_type: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log a security-related alert.

    This includes:
    - Detected prompt injection attempts
    - Unauthorized data access attempts
    - Rate limit violations
    - Authentication failures
    """
    entry: dict[str, Any] = {
        "event_type": AUDIT_EVENT_SECURITY_ALERT,
        "alert_type": alert_type,
        "session_id": session_id,
        "user_id": user_id,
        "details": details or {},
    }
    _write_audit_entry(entry)

    # Security alerts also go to WARNING level
    logger.warning(
        "SECURITY_ALERT type=%s session=%s user=%s details=%s",
        alert_type,
        session_id or "-",
        user_id or "-",
        json.dumps(details or {}, default=str)[:500],
    )


def read_audit_trail(
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read audit trail entries matching the given filters.

    Useful for debugging, incident investigation, and data subject
    access requests (Colombia Ley 1581).

    Parameters
    ----------
    session_id : str, optional
        Filter by session ID.
    trace_id : str, optional
        Filter by trace ID.
    user_id : str, optional
        Filter by user ID.
    event_type : str, optional
        Filter by event type.
    limit : int
        Maximum number of entries to return (most recent first).

    Returns
    -------
    list[dict]
        Matching audit entries in reverse chronological order.
    """
    audit_file = _AUDIT_LOG_FILE
    if not audit_file.exists():
        return []

    results: list[dict[str, Any]] = []
    try:
        with _lock:
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Apply filters
                    if session_id and entry.get("session_id") != session_id:
                        continue
                    if trace_id and entry.get("trace_id") != trace_id:
                        continue
                    if user_id and entry.get("user_id") != user_id:
                        continue
                    if event_type and entry.get("event_type") != event_type:
                        continue

                    results.append(entry)
    except OSError:
        logger.exception("Failed to read audit trail")

    # Return most recent first
    results.reverse()
    return results[:limit]


def export_audit_trail(
    output_path: str | None = None,
    *,
    since: str | None = None,
    event_type: str | None = None,
) -> str:
    """Export audit trail to a JSON file for compliance reporting.

    Parameters
    ----------
    output_path : str, optional
        Path for the export file. Defaults to
        ``/app/data/audit/export_{timestamp}.json``.
    since : str, optional
        ISO-8601 timestamp. Only include entries after this time.
    event_type : str, optional
        Filter by event type.

    Returns
    -------
    str
        Path to the exported file.
    """
    entries = read_audit_trail(event_type=event_type, limit=10000)

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            entries = [
                e for e in entries
                if datetime.fromisoformat(e.get("_timestamp", "1970-01-01")) > since_dt
            ]
        except ValueError:
            pass

    if not output_path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = str(_AUDIT_LOG_DIR / f"export_{timestamp}.json")

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, default=str, indent=2)
    except OSError as exc:
        logger.error("Failed to export audit trail: %s", exc)
        raise

    logger.info("Audit trail exported to %s (%d entries)", output_path, len(entries))
    return output_path


__all__ = [
    "AUDIT_EVENT_ANSWER_GENERATED",
    "AUDIT_EVENT_ERROR",
    "AUDIT_EVENT_HUMAN_APPROVAL_REQUESTED",
    "AUDIT_EVENT_HUMAN_APPROVAL_RESOLVED",
    "AUDIT_EVENT_MEMORY_PROPOSAL",
    "AUDIT_EVENT_MEMORY_RESOLVED",
    "AUDIT_EVENT_QUERY_RECEIVED",
    "AUDIT_EVENT_RAG_RETRIEVAL",
    "AUDIT_EVENT_SECURITY_ALERT",
    "AUDIT_EVENT_TOOL_CALLED",
    "AUDIT_EVENT_TOOL_RESULT",
    "export_audit_trail",
    "log_agent_action",
    "log_security_alert",
    "read_audit_trail",
]