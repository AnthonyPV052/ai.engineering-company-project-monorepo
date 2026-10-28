"""Calcula Recall@3 sobre data/eval/test-queries.json.

Requiere una colección Qdrant ya indexada y las variables del gateway. No se
invoca durante las pruebas unitarias; sirve como evaluación de integración.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.pipelines.rag import retrieve  # noqa: E402

EVAL_FILE = Path(__file__).with_name("test-queries.json")


def evaluate() -> tuple[int, int, float]:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    hits = 0
    for case in cases:
        results = retrieve(case["question"], k=3, min_score=0.35)
        expected_document = case["expected_source_document"]
        expected_text = case["expected_chunk_text"]
        found = any(
            result.get("source_document") == expected_document
            and expected_text in result.get("text", "")
            for result in results
        )
        hits += int(found)
        print(f"{case['id']}: {'hit' if found else 'miss'}")
    total = len(cases)
    return hits, total, hits / total if total else 0.0


if __name__ == "__main__":
    hits, total, recall = evaluate()
    print(f"Recall@3: {hits}/{total} ({recall:.1%})")
    raise SystemExit(0 if recall >= 0.80 else 1)
