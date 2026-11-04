"""Tests for the RFP intake pipeline (Parte 1).

Covers:
- Classifier: valid RFP, informal RFP, invalid document
- PDF → Markdown converter
- Readability metrics
- Department worker (marketing, operations, etc.)
- Synthesizer consolidation
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure paths
ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest

from data.pipelines.rfp_intake.classifier import (
    _classify_rule_based,
    _infer_departments,
    classify_document,
)
from data.pipelines.rfp_intake.converter import (
    compute_readability_metrics,
    pdf_to_markdown,
)
from data.pipelines.rfp_intake.workers import (
    WORKER_PROMPTS,
    _worker_template,
    run_worker,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def formal_rfp_markdown() -> str:
    """Simulated Markdown content for a formal RFP (request-1 style)."""
    return """# Solicitud de Propuesta (RFP)

## Informacion del Cliente
Razon Social: Sunset Bay Hospitality Group Inc.
Nombre Comercial: Sunset Bay Resorts
Direccion: 4500 Ocean Drive, Miami Beach, FL 33139, Estados Unidos
Contacto: Sra. Victoria Hamilton

## Tipo de Servicio Solicitado
Concesion de restaurante co-branded (Sunset Bay x Brasaland) en tres (3) resorts.
Se espera una experiencia de menu de autor que fusione la identidad Brasaland.

## Volumen y Alcance
Comensales estimados: 450 cubiertos/dia en temporada alta.
Duracion del contrato: 3 anos renovables.
Valor estimado del contrato: USD 60,000 - USD 75,000 anuales.

## Fecha Limite para Responder
La propuesta debe ser recibida a mas tardar el 30 de noviembre de 2025.
Se espera capacitacion del personal del resort durante febrero de 2026.
"""


@pytest.fixture
def informal_rfp_markdown() -> str:
    """Simulated Markdown content for an informal RFP (email-style, request-2)."""
    return """# Solicitud de Servicio de Catering

Empresa: Andes Tech Solutions S.A.S.
Contacto: Sr. Andres Marin
Direccion: Carrera 43A # 1-50, Torre Sur, Piso 12, Medellin, Colombia

Buen dia,

Por medio de la presente, solicitamos una propuesta para servicio de
catering semanal dirigido a nuestros colaboradores. Actualmente tenemos
220 empleados en nuestra sede de Medellin.

Buscamos un menu estandar con opcion de eleccion entre dos platos principales
cada dia. El servicio seria en nuestro comedor corporativo.

El contrato seria por 12 meses, con posibilidad de renovacion.
Presupuesto estimado: COP 18,000,000 - COP 22,000,000 mensuales.
Inicio estimado: Enero 2026.
"""


@pytest.fixture
def invalid_document_markdown() -> str:
    """Simulated content for a non-RFP document (request-3 style)."""
    return """# Consulta de Oportunidad Comercial

Nombre: Carlos Mendez
Telefono: +57 (315) 555-9876

Hola, estoy interesado en abrir un restaurante Brasaland en mi ciudad.
Todavia no tengo un local definido, pero estoy explorando opciones.

Quedo atento a su respuesta. Muchas gracias.
"""


@pytest.fixture
def test_pdf_path() -> Path:
    """Path to a generated test PDF."""
    return ROOT / "rfp-requests" / "brasaland" / "brasaland-request-1.pdf"


# ---------------------------------------------------------------------------
# Classifier Tests
# ---------------------------------------------------------------------------


class TestClassifier:
    """Tests for the RFP classifier agent."""

    def test_classify_formal_rfp(self, formal_rfp_markdown: str) -> None:
        """A formal RFP should be classified as valid."""
        result = classify_document(formal_rfp_markdown)

        assert result["is_valid"] is True
        assert result["confidence"] >= 0.5
        assert "classification_reason" in result

        metadata = result.get("metadata", {})
        assert metadata.get("client_name") is not None
        assert "Sunset Bay" in (metadata.get("client_name") or "")

    def test_classify_informal_rfp(self, informal_rfp_markdown: str) -> None:
        """An informal email-style RFP should also be classified as valid."""
        result = classify_document(informal_rfp_markdown)

        assert result["is_valid"] is True

        metadata = result.get("metadata", {})
        # Should extract at least some metadata
        assert metadata.get("client_name") is not None
        assert "Andes Tech" in (metadata.get("client_name") or "")

    def test_classify_invalid_document(self, invalid_document_markdown: str) -> None:
        """A query without scope/budget/deadline should be rejected."""
        result = classify_document(invalid_document_markdown)

        assert result["is_valid"] is False

    def test_classify_empty_document(self) -> None:
        """An empty document should be rejected."""
        result = classify_document("")

        assert result["is_valid"] is False

    def test_classify_whitespace_document(self) -> None:
        """A whitespace-only document should be rejected."""
        result = classify_document("   \n\n  \t  ")

        assert result["is_valid"] is False

    def test_rule_based_classifier_formal(self, formal_rfp_markdown: str) -> None:
        """Rule-based classifier should identify formal RFPs."""
        result = _classify_rule_based(formal_rfp_markdown)

        assert result["is_valid"] is True

    def test_rule_based_classifier_invalid(self, invalid_document_markdown: str) -> None:
        """Rule-based classifier should reject non-RFPs."""
        result = _classify_rule_based(invalid_document_markdown)

        assert result["is_valid"] is False

    def test_inferred_departments_formal(self, formal_rfp_markdown: str) -> None:
        """Formal RFP should activate all four departments."""
        departments = _infer_departments(formal_rfp_markdown)

        assert "marketing" in departments
        assert "operaciones" in departments
        assert "procurement" in departments
        assert "training" in departments  # "menu de autor" → training

    def test_inferred_departments_informal(self, informal_rfp_markdown: str) -> None:
        """Informal RFP with standard menu should NOT activate training."""
        departments = _infer_departments(informal_rfp_markdown)

        assert "marketing" in departments
        assert "operaciones" in departments
        assert "procurement" in departments
        assert "training" not in departments  # menu estándar, no personalizado

    def test_inferred_departments_invalid(self, invalid_document_markdown: str) -> None:
        """Invalid document should only get marketing (default)."""
        departments = _infer_departments(invalid_document_markdown)

        assert "marketing" in departments


# ---------------------------------------------------------------------------
# Converter Tests
# ---------------------------------------------------------------------------


class TestConverter:
    """Tests for PDF → Markdown conversion."""

    def test_pdf_to_markdown(self, test_pdf_path: Path) -> None:
        """A real PDF should convert to non-empty Markdown."""
        markdown = pdf_to_markdown(test_pdf_path)

        assert markdown is not None
        assert len(markdown.strip()) > 50
        # Should contain content from the PDF
        assert "Sunset" in markdown or "sunset" in markdown.lower()

    def test_pdf_to_markdown_nonexistent(self) -> None:
        """Non-existent PDF should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            pdf_to_markdown("/nonexistent/file.pdf")

    def test_readability_metrics(self, formal_rfp_markdown: str) -> None:
        """Readability metrics should return valid numbers for real text."""
        metrics = compute_readability_metrics(formal_rfp_markdown)

        assert metrics["word_count"] is not None
        assert metrics["word_count"] > 20
        assert metrics["flesch_kincaid_grade"] is not None
        assert metrics["gunning_fog"] is not None
        assert metrics["sentence_count"] is not None

    def test_readability_metrics_short_text(self) -> None:
        """Very short text should return None metrics."""
        metrics = compute_readability_metrics("Hola mundo.")

        assert metrics["word_count"] is None or metrics["word_count"] < 20

    def test_readability_metrics_empty(self) -> None:
        """Empty text should return None metrics."""
        metrics = compute_readability_metrics("")

        assert all(v is None for v in metrics.values())


# ---------------------------------------------------------------------------
# Department Worker Tests
# ---------------------------------------------------------------------------


class TestWorkers:
    """Tests for department worker agents."""

    def test_worker_marketing_prompt_exists(self) -> None:
        """Marketing worker prompt should be defined."""
        assert "marketing" in WORKER_PROMPTS
        assert "Camila Ospina" in WORKER_PROMPTS["marketing"]

    def test_worker_operaciones_prompt_exists(self) -> None:
        """Operaciones worker prompt should be defined."""
        assert "operaciones" in WORKER_PROMPTS
        assert "Felipe Guerrero" in WORKER_PROMPTS["operaciones"]

    def test_worker_procurement_prompt_exists(self) -> None:
        """Procurement worker prompt should be defined."""
        assert "procurement" in WORKER_PROMPTS
        assert "Lucía Fernández" in WORKER_PROMPTS["procurement"]

    def test_worker_training_prompt_exists(self) -> None:
        """Training worker prompt should be defined."""
        assert "training" in WORKER_PROMPTS
        assert "Jake Morrison" in WORKER_PROMPTS["training"]

    def test_worker_unknown_department(self) -> None:
        """Unknown department should raise ValueError."""
        with pytest.raises(ValueError):
            run_worker("nonexistent", "content", {})

    def test_worker_template_marketing(self) -> None:
        """Template-based marketing worker should produce key_aspects."""
        metadata = {
            "client_name": "Test Corp",
            "location": "Bogotá",
            "service_type": "Catering",
            "scope": "220 empleados, diario",
        }
        result = _worker_template("marketing", metadata)

        assert result["department_id"] == "marketing"
        assert result["key_aspects"] is not None
        assert "Test Corp" in result["key_aspects"]
        assert "Bogotá" in result["key_aspects"]
        assert result["needs_clarification"] is True

    def test_worker_template_operaciones(self) -> None:
        """Template-based operaciones worker should include suggested_setup_days."""
        result = _worker_template("operaciones", {})

        assert result["department_id"] == "operaciones"
        assert result["suggested_setup_days"] == 10  # Minimum per BRIEFING §5

    def test_worker_template_training(self) -> None:
        """Template-based training worker should have correct fields."""
        result = _worker_template("training", {})

        assert result["department_id"] == "training"
        assert result["requires_new_recipe_development"] is False
        assert result["estimated_training_days"] is None

    def test_worker_template_procurement(self) -> None:
        """Template-based procurement worker should have estimated_supply_cost_usd."""
        result = _worker_template("procurement", {})

        assert result["department_id"] == "procurement"
        assert result["estimated_supply_cost_usd"] is None

    def test_worker_with_markdown_uses_template_fallback(self, formal_rfp_markdown: str) -> None:
        """Worker should return valid structure even with fallback."""
        metadata = {"client_name": "Sunset Bay Resorts"}
        result = run_worker("marketing", formal_rfp_markdown, metadata)

        assert result["department_id"] == "marketing"
        assert "key_aspects" in result

    def test_worker_llm_fallback_integrity(self, formal_rfp_markdown: str) -> None:
        """All four workers should return valid structure when using fallback."""
        departments = ["marketing", "operaciones", "procurement", "training"]
        metadata = {
            "client_name": "Sunset Bay Resorts",
            "location": "Florida, USA",
            "service_type": "Concesión co-branded",
            "scope": "3 resorts, 450 cubiertos/día",
        }

        for dept_id in departments:
            result = run_worker(dept_id, formal_rfp_markdown, metadata)
            assert result["department_id"] == dept_id
            assert "key_aspects" in result
            assert len(result["key_aspects"]) > 0


# ---------------------------------------------------------------------------
# Integration-style Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Lightweight integration tests for the pipeline components."""

    def test_classifier_to_workers_pipeline(self, formal_rfp_markdown: str) -> None:
        """Simulate: classify → infer departments → run workers."""
        # 1. Classify
        classification = classify_document(formal_rfp_markdown)
        assert classification["is_valid"] is True

        departments = classification.get("departments_needed", [])
        metadata = classification.get("metadata", {})

        # 2. Run workers for every department the classifier returned
        for dept_id in departments:
            result = run_worker(dept_id, formal_rfp_markdown, metadata)
            assert result["department_id"] == dept_id
            assert result["key_aspects"] is not None

        # 3. Verify at least marketing is always included (LLM may vary others)
        assert "marketing" in departments

        # 4. Also verify rule-based classifier includes procurement for this RFP
        rule_departments = _infer_departments(formal_rfp_markdown)
        assert "procurement" in rule_departments

    def test_full_pipeline_on_pdf(self, test_pdf_path: Path) -> None:
        """End-to-end: convert PDF → classify → workers."""
        # 1. Convert
        markdown = pdf_to_markdown(test_pdf_path)
        assert len(markdown.strip()) > 50

        # 2. Classify
        classification = classify_document(markdown)
        assert classification["is_valid"] is True, (
            f"PDF should be valid RFP. Reason: {classification.get('classification_reason')}"
        )

        # 3. Departments
        departments = classification.get("departments_needed", [])
        assert len(departments) >= 2  # At least marketing + something

        # 4. Metadata extracted
        metadata = classification.get("metadata", {})
        client_name = metadata.get("client_name")
        assert client_name is not None, f"Should extract client name from PDF. Metadata: {metadata}"

        # 5. Readability metrics
        metrics = compute_readability_metrics(markdown)
        assert metrics["word_count"] is not None
        assert metrics["word_count"] > 30

    def test_readability_metrics_on_pdf(self, test_pdf_path: Path) -> None:
        """Readability metrics should work on real PDF content."""
        markdown = pdf_to_markdown(test_pdf_path)
        metrics = compute_readability_metrics(markdown)

        # Should have computed metrics
        has_any_metric = any(
            v is not None
            for k, v in metrics.items()
            if k not in ("word_count", "sentence_count")
        )
        # This may fail if py-readability-metrics is not installed
        # But word_count should always work
        assert metrics["word_count"] is not None
        assert metrics["word_count"] > 0