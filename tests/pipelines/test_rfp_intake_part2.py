"""Tests for the RFP response generation pipeline (Parte 2).

Covers:
- Generator agents (template fallback per department)
- Evaluator agents (readability, relevance, compliance)
- Generator-evaluator loop logic
- Compliance failure anchored to BRIEFING §5 rules
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

from data.pipelines.rfp_intake.generators import (
    GENERATOR_PROMPTS,
    _generator_template,
    run_generator,
)
from data.pipelines.rfp_intake.evaluators import (
    COMPLIANCE_RULES,
    evaluate_compliance,
    evaluate_readability,
    evaluate_relevance,
    evaluate_section,
    clean_evaluate_section,
    _check_both_currencies,
    _check_brand_pillars,
    _check_setup_days,
    _check_competitors,
    _check_offer_validity,
)
from data.pipelines.rfp_intake.graph_part2 import (
    MAX_ITERATIONS,
    RFPResponseState,
    generate_drafts_node,
    evaluate_drafts_node,
    regenerate_drafts_node,
    route_after_evaluation,
    make_initial_state,
    finalize_node,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handoff_payload() -> dict:
    """Simulated Part 1 handoff payload (like from request-1, Sunset Bay)."""
    return {
        "ticket_id": "test-ticket-123",
        "status": "analisis_completo",
        "client_name": "Sunset Bay Resorts",
        "service_type": "Concesión co-branded",
        "departments_needed": ["marketing", "operaciones", "procurement", "training"],
        "department_contacts": {
            "marketing": "Camila Ospina",
            "operaciones": "Felipe Guerrero",
            "procurement": "Lucía Fernández",
            "training": "Jake Morrison",
        },
        "key_aspects_by_department": {
            "marketing": (
                "Cliente: Sunset Bay Resorts (Florida). "
                "Solicita concesión co-branded en 3 resorts. "
                "Exclusividad de marca. Valor estimado USD 60,000-75,000/año. "
                "Se requiere menú de autor."
            ),
            "operaciones": (
                "450 cubiertos/día en temporada alta. "
                "3 ubicaciones en Florida. "
                "Requiere personal de cocina y servicio."
            ),
            "procurement": (
                "Volumen: 450 cubiertos/día. "
                "Menú de autor requiere insumos premium. "
                "3 ubicaciones: logística a Florida."
            ),
            "training": (
                "Menú de autor requiere desarrollo de recetas nuevas. "
                "Capacitación del personal del resort necesaria. "
                "Nuevos estándares de calidad."
            ),
        },
        "open_questions": {
            "marketing": [],
            "operaciones": ["¿Cuánto personal por turno?"],
            "procurement": ["¿Proveedores locales en Florida?"],
            "training": ["¿Tiempo estimado para certificación?"],
        },
        "metadata": {
            "client_name": "Sunset Bay Resorts",
            "location": "Florida, USA",
            "service_type": "Concesión co-branded",
            "scope": "3 resorts, 450 cubiertos/día, 3 años renovables",
            "deadline": "30 de noviembre de 2025",
            "budget_range": "USD 60,000 - USD 75,000 anuales",
            "annual_estimated_usd": 45000.0,
        },
        "readability_metrics": {
            "flesch_kincaid_grade": 10.2,
            "word_count": 350,
        },
    }


@pytest.fixture
def simple_handoff() -> dict:
    """Simpler handoff for testing a subset of departments."""
    return {
        "ticket_id": "test-ticket-456",
        "status": "analisis_completo",
        "client_name": "Andes Tech Solutions",
        "service_type": "Catering semanal",
        "departments_needed": ["marketing", "operaciones", "procurement"],
        "department_contacts": {
            "marketing": "Camila Ospina",
            "operaciones": "Felipe Guerrero",
            "procurement": "Lucía Fernández",
        },
        "key_aspects_by_department": {
            "marketing": (
                "Cliente: Andes Tech Solutions (Medellín). "
                "Catering semanal para 220 empleados. "
                "Menú estándar. Contrato 12 meses."
            ),
            "operaciones": (
                "220 comensales/día. Comedor corporativo en Medellín. "
                "Servicio semanal."
            ),
            "procurement": (
                "220 cubiertos/día, menú estándar. "
                "COP 18-22M/mes presupuesto."
            ),
        },
        "open_questions": {
            "marketing": [],
            "operaciones": [],
            "procurement": [],
        },
        "metadata": {
            "client_name": "Andes Tech Solutions",
            "location": "Medellín, Colombia",
            "service_type": "Catering semanal",
            "scope": "220 empleados, 12 meses",
            "deadline": "Enero 2026",
            "budget_range": "COP 18,000,000 - COP 22,000,000 mensuales",
            "annual_estimated_usd": None,
        },
        "readability_metrics": {
            "flesch_kincaid_grade": 9.5,
            "word_count": 200,
        },
    }


@pytest.fixture
def compliant_draft() -> str:
    """A draft that should pass all compliance checks."""
    return """
## Propuesta de Marketing — Sunset Bay Resorts

**Cliente:** Sunset Bay Resorts en Florida, USA.

**Resumen Ejecutivo:** Esta propuesta incluye una concesión co-branded para el resort. Usa los pilares de Brasaland: calidad consistente, experiencia cálida y velocidad de servicio. La marca Brasaland sera el proveedor exclusivo de alimentos.

**Precios:**
- USD 60,000 a USD 75,000 por ano.
- COP 240,000,000 a COP 300,000,000 por ano.

**Validez de la Oferta:** La oferta tiene validez de 30 dias.

**Montaje:** El montaje se hara en 10 dias habiles como minimo.

**Informacion Pendiente:** Falta confirmar el volumen de comensales mensuales. El cliente debe dar esta informacion. Esto ayuda a ajustar la produccion y el personal que se requiere.

No hay competidores en esta propuesta. Todos los precios estan en COP y USD.
""".strip()


@pytest.fixture
def non_compliant_draft() -> str:
    """A draft that violates multiple BRIEFING §5 rules."""
    return """
## Marketing — Propuesta Rápida

**Cliente:** Test Corp

Podemos hacer el montaje en solo 5 días hábiles.
Nuestro servicio es superior a McDonald's y Burger King.

**Precio:** USD 45,000 anuales.

Listo para firmar.
""".strip()


# ---------------------------------------------------------------------------
# Generator Tests
# ---------------------------------------------------------------------------


class TestGeneratorAgents:
    """Tests for department generator agents."""

    def test_generator_prompts_exist(self) -> None:
        """All four department generator prompts should be defined."""
        assert "marketing" in GENERATOR_PROMPTS
        assert "operaciones" in GENERATOR_PROMPTS
        assert "procurement" in GENERATOR_PROMPTS
        assert "training" in GENERATOR_PROMPTS

    def test_generator_prompt_mentions_briefing(self) -> None:
        """Generator prompts should reference BRIEFING rules."""
        mkt_prompt = GENERATOR_PROMPTS["marketing"]
        assert "30 días" in mkt_prompt
        assert "calidad consistente" in mkt_prompt
        assert "competidores" in mkt_prompt
        assert "10 días hábiles" in mkt_prompt

    def test_generator_template_marketing(self, handoff_payload: dict) -> None:
        """Template-based marketing generator should produce draft_content."""
        result = _generator_template("marketing", handoff_payload)

        assert result["department_id"] == "marketing"
        assert result["draft_content"] is not None
        assert "Sunset Bay" in result["draft_content"]
        assert "10 días hábiles" in result["draft_content"]
        assert "30 días" in result["draft_content"]

    def test_generator_template_operaciones(self, handoff_payload: dict) -> None:
        """Template-based operaciones generator should produce draft_content."""
        result = _generator_template("operaciones", handoff_payload)

        assert result["department_id"] == "operaciones"
        assert result["draft_content"] is not None
        assert result["estimated_setup_days"] == 10

    def test_generator_template_procurement(self, handoff_payload: dict) -> None:
        """Template-based procurement generator should produce draft_content."""
        result = _generator_template("procurement", handoff_payload)

        assert result["department_id"] == "procurement"
        assert result["draft_content"] is not None
        assert result["estimated_supply_cost_usd"] is None

    def test_generator_template_training(self, handoff_payload: dict) -> None:
        """Template-based training generator should produce draft_content."""
        result = _generator_template("training", handoff_payload)

        assert result["department_id"] == "training"
        assert result["draft_content"] is not None
        assert result["requires_new_recipe_development"] is False
        assert result["estimated_training_days"] is None

    def test_generator_unknown_department(self) -> None:
        """Unknown department should raise ValueError."""
        with pytest.raises(ValueError):
            run_generator("nonexistent", {}, previous_feedback=None)


# ---------------------------------------------------------------------------
# Compliance Evaluator Tests
# ---------------------------------------------------------------------------


class TestComplianceEvaluator:
    """Tests for the compliance evaluator (BRIEFING §5 rules)."""

    def test_compliance_rules_defined(self) -> None:
        """All BRIEFING §5 rules should be defined."""
        assert "prices_cop_usd" in COMPLIANCE_RULES
        assert "three_pillars" in COMPLIANCE_RULES
        assert "min_setup_days" in COMPLIANCE_RULES
        assert "no_competitors" in COMPLIANCE_RULES
        assert "offer_validity" in COMPLIANCE_RULES

    def test_compliant_draft_passes(self, compliant_draft: str) -> None:
        """A draft that follows all rules should pass compliance."""
        result = evaluate_compliance(compliant_draft, {"annual_estimated_usd": 45000.0})
        assert result["pass"] is True
        assert len(result["violations"]) == 0

    def test_non_compliant_draft_fails(self, non_compliant_draft: str) -> None:
        """A draft violating rules should fail compliance."""
        result = evaluate_compliance(non_compliant_draft, {"annual_estimated_usd": 45000.0})

        assert result["pass"] is False
        assert len(result["violations"]) > 0

    def test_compliance_failure_competitors(self, non_compliant_draft: str) -> None:
        """Draft mentioning competitors should flag no_competitors rule."""
        result = evaluate_compliance(non_compliant_draft, {})
        competitor_violations = [v for v in result["violations"] if "competidor" in v.lower()]
        assert len(competitor_violations) > 0
        assert "no_competitors" in result["rule_ids"]

    def test_compliance_failure_setup_days(self, non_compliant_draft: str) -> None:
        """Draft promising setup under 10 days should flag min_setup_days."""
        result = evaluate_compliance(non_compliant_draft, {})
        setup_violations = [v for v in result["violations"] if "5 días" in v]
        assert len(setup_violations) > 0
        assert "min_setup_days" in result["rule_ids"]

    def test_compliance_check_both_currencies(self) -> None:
        """_check_both_currencies should detect missing COP or USD."""
        text_only_usd = "Precio: USD 10,000 anuales."
        passed, violations = _check_both_currencies(text_only_usd)
        assert not passed
        assert any("COP" in v for v in violations)

        text_both = "Precio: USD 10,000 (COP 40,000,000)."
        passed, violations = _check_both_currencies(text_both)
        assert passed
        assert len(violations) == 0

    def test_compliance_check_brand_pillars(self) -> None:
        """_check_brand_pillars should detect missing pillars."""
        text_missing = "Ofrecemos calidad consistente y velocidad de servicio."
        passed, violations = _check_brand_pillars(text_missing)
        assert not passed
        assert any("experiencia cálida" in v for v in violations)

        text_all = "calidad consistente, experiencia cálida y velocidad de servicio."
        passed, violations = _check_brand_pillars(text_all)
        assert passed

    def test_compliance_check_setup_days(self) -> None:
        """_check_setup_days should flag under-10-day promises."""
        text_ok = "El montaje se realizará en 10 días hábiles."
        passed, violations = _check_setup_days(text_ok)
        assert passed

        text_violation = "Podemos hacer el montaje en solo 5 días hábiles."
        passed, violations = _check_setup_days(text_violation)
        assert not passed

    def test_compliance_check_competitors(self) -> None:
        """_check_competitors should detect competitor names."""
        text_ok = "Ofrecemos servicio de calidad superior."
        passed, violations = _check_competitors(text_ok)
        assert passed

        text_violation = "Somos mejores que McDonald's y Burger King."
        passed, violations = _check_competitors(text_violation)
        assert not passed

    def test_compliance_check_offer_validity(self) -> None:
        """_check_offer_validity should detect missing validity period."""
        text_ok = "Validez de la oferta: 30 días desde su emisión."
        passed, violations = _check_offer_validity(text_ok)
        assert passed

        text_missing = "Ofrecemos nuestros servicios."
        passed, violations = _check_offer_validity(text_missing)
        assert not passed

    def test_compliance_empty_text(self) -> None:
        """Empty draft should fail compliance."""
        result = evaluate_compliance("", {})
        assert result["pass"] is False

    def test_compliance_ceo_threshold_triggered(self) -> None:
        """Annual estimated value > 50K USD should flag CEO approval needed."""
        text = "Servicio por USD 60,000 anuales. calidad consistente, experiencia cálida, velocidad de servicio. Validez: 30 días. COP: $240,000,000."
        result = evaluate_compliance(text, {"annual_estimated_usd": 67500.0})
        # Should pass all rules except CEO threshold triggers a flag (not a compliance violation)
        # Actually, in our implementation _check_ceo_threshold adds a violation
        # Let's check if CEO threshold adds a violation or just informational
        ceo_violations = [v for v in result["violations"] if "CEO" in v]
        assert len(ceo_violations) > 0


# ---------------------------------------------------------------------------
# Readability Evaluator Tests
# ---------------------------------------------------------------------------


class TestReadabilityEvaluator:
    """Tests for the readability evaluator."""

    def test_readability_long_text(self) -> None:
        """Longer text should get a readability score."""
        text = (
            "This is a test paragraph with multiple sentences. "
            "It should be long enough to compute readability metrics. "
            "We need at least twenty words for a valid score. "
            "The quick brown fox jumps over the lazy dog. "
            "This sentence contains more words. And another one too."
        ) * 5
        result = evaluate_readability(text)
        assert "score" in result
        assert result["score"] > 0

    def test_readability_short_text(self) -> None:
        """Very short text should not pass readability."""
        result = evaluate_readability("Hola mundo.")
        assert result["pass"] is False


# ---------------------------------------------------------------------------
# Relevance Evaluator Tests
# ---------------------------------------------------------------------------


class TestRelevanceEvaluator:
    """Tests for the relevance evaluator."""

    def test_relevance_mentions_client(self, handoff_payload: dict) -> None:
        """Draft mentioning client should not flag missing client."""
        draft = (
            "Propuesta para Sunset Bay Resorts en Florida como concesión co-branded. "
            "Este documento presenta una propuesta integral de servicios de alimentación "
            "para el complejo turístico Sunset Bay Resorts ubicado en el estado de Florida. "
            "Nuestra oferta incluye servicios de desayuno, almuerzo y cena para huéspedes "
            "y visitantes, con opciones de menú personalizadas según las preferencias del cliente. "
            "El equipo de Brasaland se compromete a entregar una experiencia culinaria de primera clase, "
            "manteniendo los más altos estándares de calidad y servicio. "
            "Además, se proporcionará personal capacitado y entrenado en atención al cliente "
            "para garantizar una experiencia cálida y memorable. "
            "Los tiempos de entrega y montaje se realizarán en un plazo mínimo de 10 días hábiles "
            "para asegurar una correcta instalación y puesta en marcha de todas las operaciones. "
            "Se presentarán precios tanto en COP como en USD para facilitar la facturación internacional, "
            "y la oferta tendrá una validez de 30 días desde su emisión. "
            "Información pendiente sobre volumen mensual de comensales por confirmar. "
            "No se mencionan competidores en esta propuesta, y todos los costos están claramente detallados "
            "en las secciones siguientes del documento."
        )
        result = evaluate_relevance(draft, handoff_payload, "marketing")
        assert result["pass"] is True

    def test_relevance_missing_client(self, handoff_payload: dict) -> None:
        """Draft not mentioning client should flag missing client."""
        draft = "Propuesta para un cliente genérico."
        result = evaluate_relevance(draft, handoff_payload, "marketing")
        missing = [m for m in result["missing_aspects"] if "Sunset" in m]
        assert len(missing) > 0

    def test_relevance_empty_draft(self, handoff_payload: dict) -> None:
        """Empty draft should not pass relevance."""
        result = evaluate_relevance("", handoff_payload, "marketing")
        assert result["pass"] is False


# ---------------------------------------------------------------------------
# Evaluator Integration Tests
# ---------------------------------------------------------------------------


class TestEvaluatorIntegration:
    """Tests for the full evaluation pipeline."""

    def test_compliant_section_passes_all(self, compliant_draft: str, handoff_payload: dict) -> None:
        """A compliant draft should pass all three evaluators."""
        result = evaluate_section(compliant_draft, handoff_payload, "marketing")

        assert result["department_id"] == "marketing"
        assert result["readability"]["pass"] is True
        assert result["relevance"]["pass"] is True
        assert result["compliance"]["pass"] is True
        assert result["overall_pass"] is True

    def test_non_compliant_section_fails(self, non_compliant_draft: str, handoff_payload: dict) -> None:
        """A non-compliant draft should fail evaluation."""
        result = evaluate_section(non_compliant_draft, handoff_payload, "marketing")

        assert result["overall_pass"] is False
        assert result["compliance"]["pass"] is False
        assert result["feedback_for_generator"] != "Sección aprobada."
        assert "competidor" in result["feedback_for_generator"].lower()

    def test_evaluation_result_structure(self, compliant_draft: str, handoff_payload: dict) -> None:
        """Evaluation result should have the expected structure."""
        result = evaluate_section(compliant_draft, handoff_payload, "marketing")

        assert "department_id" in result
        assert "readability" in result
        assert "relevance" in result
        assert "compliance" in result
        assert "overall_pass" in result
        assert "feedback_for_generator" in result

        # Sub-structures
        readability = result["readability"]
        assert "pass" in readability
        assert "score" in readability
        assert "details" in readability

        relevance = result["relevance"]
        assert "pass" in relevance
        assert "missing_aspects" in relevance
        assert "details" in relevance

        compliance = result["compliance"]
        assert "pass" in compliance
        assert "rule_ids" in compliance
        assert "violations" in compliance
        assert "details" in compliance

    def test_clean_evaluate_section(self, compliant_draft: str) -> None:
        """clean_evaluate_section should work without full handoff."""
        result = clean_evaluate_section(
            compliant_draft,
            metadata={"annual_estimated_usd": 45000.0},
        )
        assert "overall_pass" in result
        assert "feedback_for_generator" in result


# ---------------------------------------------------------------------------
# Graph Node Tests
# ---------------------------------------------------------------------------


class TestGraphNodes:
    """Tests for Part 2 LangGraph nodes."""

    def test_generate_drafts_node(self, handoff_payload: dict) -> None:
        """generate_drafts_node should produce drafts for all departments."""
        state = make_initial_state("test-123", handoff_payload)
        result = generate_drafts_node(state)

        assert result["status"] == "generando_borrador"
        assert "marketing" in result["drafts"]
        assert "operaciones" in result["drafts"]
        assert "procurement" in result["drafts"]
        assert "training" in result["drafts"]
        assert all(len(d) > 0 for d in result["drafts"].values())

    def test_generate_drafts_node_simple(self, simple_handoff: dict) -> None:
        """generate_drafts_node should handle fewer departments."""
        state = make_initial_state("test-456", simple_handoff)
        result = generate_drafts_node(state)

        assert result["status"] == "generando_borrador"
        assert "marketing" in result["drafts"]
        assert "operaciones" in result["drafts"]
        assert "procurement" in result["drafts"]
        assert "training" not in result["drafts"]

    def test_evaluate_drafts_node(self, handoff_payload: dict) -> None:
        """evaluate_drafts_node should evaluate all generated drafts."""
        # First generate drafts
        state = make_initial_state("test-123", handoff_payload)
        state = generate_drafts_node(state)

        # Then evaluate
        result = evaluate_drafts_node(state)

        assert result["status"] == "en_evaluacion"
        assert "marketing" in result["evaluations"]
        assert "operaciones" in result["evaluations"]
        assert "procurement" in result["evaluations"]
        assert "training" in result["evaluations"]

        # All evaluations should have the expected structure
        for dept_id in ["marketing", "operaciones", "procurement", "training"]:
            eval_result = result["evaluations"][dept_id]
            assert "overall_pass" in eval_result
            assert "feedback_for_generator" in eval_result

    def test_route_after_evaluation_all_pass(self, handoff_payload: dict) -> None:
        """route_after_evaluation should go to 'finalize' when all pass."""
        state = make_initial_state("test-123", handoff_payload)
        state["evaluations"] = {
            "marketing": {"overall_pass": True},
            "operaciones": {"overall_pass": True},
        }
        route = route_after_evaluation(state)
        assert route == "finalize"

    def test_route_after_evaluation_some_fail(self, handoff_payload: dict) -> None:
        """route_after_evaluation should go to 'regenerate' when some fail."""
        state = make_initial_state("test-123", handoff_payload)
        state["evaluations"] = {
            "marketing": {"overall_pass": True},
            "operaciones": {"overall_pass": False},
        }
        route = route_after_evaluation(state)
        assert route == "regenerate"

    def test_route_after_evaluation_limit_reached(self, handoff_payload: dict) -> None:
        """route_after_evaluation should go to 'finalize' when all iterations exhausted."""
        state = make_initial_state("test-123", handoff_payload)
        state["evaluations"] = {
            "marketing": {"overall_pass": False},
        }
        state["iteration_counts"] = {"marketing": MAX_ITERATIONS}
        route = route_after_evaluation(state)
        assert route == "finalize"

    def test_route_after_evaluation_some_can_still_retry(self, handoff_payload: dict) -> None:
        """route_after_evaluation should regenerate if some departments can retry."""
        state = make_initial_state("test-123", handoff_payload)
        state["evaluations"] = {
            "marketing": {"overall_pass": True},
            "operaciones": {"overall_pass": False},
        }
        state["iteration_counts"] = {
            "marketing": 0,
            "operaciones": 2,  # has one retry left (MAX=3)
        }
        route = route_after_evaluation(state)
        assert route == "regenerate"

    def test_regenerate_drafts_node(self, handoff_payload: dict) -> None:
        """regenerate_drafts_node should increment iteration for failed sections."""
        state = make_initial_state("test-123", handoff_payload)
        state["drafts"] = {"marketing": "test", "operaciones": "test"}
        state["evaluations"] = {
            "marketing": {"overall_pass": True},
            "operaciones": {"overall_pass": False, "feedback_for_generator": "Fix this."},
        }

        result = regenerate_drafts_node(state)
        assert result["iteration_counts"]["operaciones"] == 1
        assert result["iteration_counts"]["marketing"] == 0

    def test_regenerate_mark_sections_for_review(self, handoff_payload: dict) -> None:
        """regenerate_drafts_node should mark for review when limit reached."""
        state = make_initial_state("test-123", handoff_payload)
        state["drafts"] = {"marketing": "test"}
        state["evaluations"] = {
            "marketing": {"overall_pass": False, "feedback_for_generator": "Fix this."},
        }
        state["iteration_counts"] = {"marketing": MAX_ITERATIONS - 1}

        result = regenerate_drafts_node(state)
        assert "marketing" in result["sections_needing_review"]

    def test_finalize_node(self, handoff_payload: dict) -> None:
        """finalize_node should produce the Part 3 handoff payload."""
        state = make_initial_state("test-123", handoff_payload)
        state["drafts"] = {
            "marketing": "Draft marketing",
            "operaciones": "Draft operaciones",
        }
        state["evaluations"] = {
            "marketing": {"overall_pass": True, "department_id": "marketing"},
            "operaciones": {"overall_pass": False, "department_id": "operaciones"},
        }
        state["sections_needing_review"] = []

        result = finalize_node(state)
        assert result["handoff_to_part3"] is not None
        assert len(result["handoff_to_part3"]) > 0

        # Parse and verify structure
        payload = json.loads(result["handoff_to_part3"])
        assert payload["ticket_id"] == "test-123"
        assert len(payload["sections"]) == 2
        assert payload["sections_passed"] == 1
        assert payload["sections_failed"] == 1


# ---------------------------------------------------------------------------
# Pipeline Integration Tests
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """Tests for the full Part 2 pipeline."""

    def test_make_initial_state(self, handoff_payload: dict) -> None:
        """make_initial_state should set up correct initial state."""
        state = make_initial_state("test-123", handoff_payload)

        assert state["ticket_id"] == "test-123"
        assert state["status"] == "analisis_completo"
        assert state["handoff_payload"] is not None
        assert len(state["drafts"]) == 0
        assert state["sections_needing_review"] == []
        assert state["iteration_counts"]["marketing"] == 0
        assert state["iteration_counts"]["operaciones"] == 0
        assert state["iteration_counts"]["procurement"] == 0
        assert state["iteration_counts"]["training"] == 0


# ---------------------------------------------------------------------------
# Compliance Failure Test Case (anchored to BRIEFING §5)
# ---------------------------------------------------------------------------


class TestComplianceFailureBRIEFING:
    """Test that compliance failures are anchored to concrete BRIEFING §5 rules.

    This is the required test case: a draft that promises something the
    BRIEFING prohibits → compliance.pass == false.
    """

    def test_compliance_failure_briefing_rule_setup_days(self) -> None:
        """BRIEFING §5: No montaje/entrega menor a 10 días hábiles.

        A draft promising 5-day setup should violate min_setup_days.
        """
        draft = (
            "Propuesta para Cliente X.\n"
            "Podemos realizar el montaje completo en solo 5 días hábiles.\n"
            "Nuestro equipo está listo para comenzar de inmediato.\n"
            "calidad consistente, experiencia cálida y velocidad de servicio.\n"
            "Validez de la oferta: 30 días.\n"
            "Precio: USD 10,000 (COP 40,000,000)."
        )
        result = evaluate_compliance(draft, {"annual_estimated_usd": 10000.0})

        assert result["pass"] is False, (
            f"Draft promete montaje en 5 días pero BRIEFING §5 exige mínimo 10. "
            f"Violations: {result['violations']}"
        )

        # Verify the specific rule that was violated
        setup_violations = [v for v in result["violations"] if "5 días" in v or "5 dias" in v]
        assert len(setup_violations) > 0, (
            f"Should flag the 5-day setup violation. Got violations: {result['violations']}"
        )

        # Verify the rule ID is included
        assert "min_setup_days" in result["rule_ids"]

    def test_compliance_failure_briefing_rule_competitors(self) -> None:
        """BRIEFING §5: No mencionar competidores.

        A draft mentioning a competitor by name should violate no_competitors.
        """
        draft = (
            "Nuestro servicio de catering es superior a McDonald's y ofrece\n"
            "calidad consistente, experiencia cálida y velocidad de servicio.\n"
            "Validez de la oferta: 30 días desde su emisión.\n"
            "Precio: USD 15,000 (COP 60,000,000).\n"
            "El montaje se realizará en 10 días hábiles."
        )
        result = evaluate_compliance(draft, {"annual_estimated_usd": 15000.0})

        assert result["pass"] is False, (
            f"Draft menciona 'McDonald's' pero BRIEFING §5 prohíbe nombres de competidores. "
            f"Violations: {result['violations']}"
        )

        competitor_violations = [v for v in result["violations"] if "mcdonald" in v.lower()]
        assert len(competitor_violations) > 0, (
            f"Should flag competitor mention. Got violations: {result['violations']}"
        )

        assert "no_competitors" in result["rule_ids"]

    def test_compliance_failure_briefing_rule_prices(self) -> None:
        """BRIEFING §5: Precios deben expresarse en COP y USD.

        A draft with only USD should violate prices_cop_usd.
        """
        draft = (
            "Ofrecemos calidad consistente, experiencia cálida y velocidad de servicio.\n"
            "Precio: USD 10,000 anuales.\n"
            "Validez de la oferta: 30 días.\n"
            "El montaje se realizará en 10 días hábiles."
        )
        result = evaluate_compliance(draft, {"annual_estimated_usd": 10000.0})

        assert result["pass"] is False, (
            f"Draft solo tiene USD, falta COP. Violations: {result['violations']}"
        )

        currency_violations = [v for v in result["violations"] if "COP" in v]
        assert len(currency_violations) > 0
        assert "prices_cop_usd" in result["rule_ids"]

    def test_compliance_pass_all_rules(self) -> None:
        """A draft that follows all BRIEFING §5 rules should pass."""
        draft = (
            "Propuesta para Cliente Demo.\n\n"
            "**Pilares de marca:** Calidad consistente, experiencia cálida y velocidad de servicio.\n\n"
            "**Precios:**\n"
            "- USD 50,000 anuales\n"
            "- COP 200,000,000 anuales\n\n"
            "**Validez de la oferta:** 30 días desde su emisión.\n\n"
            "**Montaje:** Se realizará en un mínimo de 10 días hábiles.\n\n"
            "No se mencionan competidores.\n"
        )
        result = evaluate_compliance(draft, {"annual_estimated_usd": 50000.0})

        assert result["pass"] is True, (
            f"Draft sigue todas las reglas pero falló. Violations: {result['violations']}"
        )
        assert len(result["violations"]) == 0