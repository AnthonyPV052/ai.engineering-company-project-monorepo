"""Trazas JSONL persistentes para inspeccionar corridas del agente."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _trace_dir() -> Path:
    directory = Path(os.getenv("AGENT_TRACE_DIR", Path(__file__).resolve().parents[1] / "snapshots" / "agent-traces"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write(trace_id: str, event: dict[str, Any]) -> None:
    with _LOCK, (_trace_dir() / f"{trace_id}.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def start_trace(trace_id: str, question: str) -> None:
    _write(trace_id, {"trace_id": trace_id, "event": "run_started", "question": question, "timestamp": datetime.now(timezone.utc).isoformat()})


def record_node(state: dict[str, Any], node: str, output: dict[str, Any]) -> None:
    _write(state["trace_id"], {"trace_id": state["trace_id"], "event": "node_completed", "node": node, "output": output, "timestamp": datetime.now(timezone.utc).isoformat()})


def finish_trace(
    trace_id: str,
    answer: str,
    *,
    sources: list[str] | None = None,
    execution_order: list[str] | None = None,
    memory_proposal: dict[str, object] | None = None,
    session_id: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "trace_id": trace_id,
        "event": "run_completed",
        "answer": answer,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if sources is not None:
        event["sources"] = sources
    if execution_order is not None:
        event["execution_order"] = execution_order
    if memory_proposal is not None:
        event["memory_proposal"] = memory_proposal
    if session_id is not None:
        event["session_id"] = session_id
    _write(trace_id, event)


def actual_sources(events: list[dict[str, Any]]) -> list[str]:
    """Return sources whose node was actually reached, in first-use order."""
    sources: list[str] = []
    for event in events:
        if event.get("event") != "node_completed":
            continue
        node = event.get("node")
        output = event.get("output") or {}
        used: list[str] = []
        if node == "retrieve" and output.get("outcome") != "skipped":
            used.append("rag")
        elif node == "incident_tool":
            used.append("incident_tool")
        for source in used:
            if source not in sources:
                sources.append(source)
    return sources


def read_trace(trace_id: str) -> list[dict[str, Any]]:
    path = _trace_dir() / f"{trace_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(trace_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]