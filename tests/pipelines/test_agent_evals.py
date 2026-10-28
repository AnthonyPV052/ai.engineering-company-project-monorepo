"""Evaluaciones offline sobre traces ya persistidos (sin ejecutar el agente)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TRACE_DIR = ROOT / "services" / "api" / "snapshots" / "agent-traces"


def _trace_files() -> list[Path]:
    return sorted(TRACE_DIR.glob("*.jsonl"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _trace_files():
        return
    skip = pytest.mark.skip(reason="No hay traces persistidos; ejecute una corrida del agente primero")
    for item in items:
        if item.module.__name__ == __name__:
            item.add_marker(skip)


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(params=_trace_files(), scope="session")
def trace(request: pytest.FixtureRequest) -> list[dict]:
    return _events(request.param)


def test_trace_has_retrieval_before_answer(trace: list[dict]) -> None:
    nodes = [event["node"] for event in trace if event.get("event") == "node_completed"]
    assert "retrieve" in nodes
    answer_nodes = [node for node in ("generate", "no_context", "incident_answer") if node in nodes]
    assert answer_nodes
    assert nodes.index("retrieve") < nodes.index(answer_nodes[0])


def test_trace_has_one_terminal_answer(trace: list[dict]) -> None:
    terminal_nodes = [
        event["node"]
        for event in trace
        if event.get("node") in {"generate", "no_context", "incident_answer"}
    ]
    assert len(terminal_nodes) == 1
    assert any(event.get("event") == "run_completed" for event in trace)


def test_known_policy_answer_is_anchored_in_rag(trace: list[dict]) -> None:
    """La respuesta de la corrida debe conservar evidencia recuperada."""
    completed = next(event for event in trace if event.get("event") == "run_completed")
    retrieval = next(event for event in trace if event.get("node") == "retrieve")
    context = retrieval.get("output", {}).get("context", [])
    if "Brasa" not in completed.get("answer", "") and "martes" not in completed.get("answer", ""):
        pytest.skip("La corrida no corresponde a la pregunta de política de fidelización")
    assert context
    assert any(item.get("source_document", "").endswith("loyalty-program.es.md") for item in context)
