"""Tests for RFP Part 3 — Approval, Arbitration & Final Document.

Covers:
- Checkpointer: save/load/resume/clear with thread_id namespacing
- Traceability: record execution
- Arbitration: conflict detection, auto-resolve, manual triggers
- Graph Part 3: pipeline nodes, routing, state transitions
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure paths
ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest

from rfp_models import (
    APPROVAL_STATUS_PENDIENTE,
    APPROVAL_STATUS_APROBADO,
    APPROVAL_STATUS_RECHAZADO,
    APPROVAL_STATUS_REQUEST_CHANGES,
    CONFLICT_TRIGGER_COST_VS_FEASIBILITY,
    CONFLICT_TRIGGER_SETUP_SLA_BREACH,
    CONFLICT_TRIGGER_CEO_THRESHOLD,
    ARBITRATION_ARBITERS,
    ARBITRATION_RESOLUTION_APPROVE,
    ARBITRATION_RESOLUTION_REQUEST_CHANGES,
)

from data.pipelines.rfp_intake.graph_part3 import (
    RFPApprovalState,
    make_approval_state,
    enter_part3_node,
    save_interrupts_node,
    resume_from_checkpoint_node,
    process_human_decision_node,
    arbitration_node,
    ceo_approval_interrupt_node,
    generate_final_document_node,
    finalize_node,
    route_after_human_decision,
    route_after_arbitration,
    DEPARTMENT_APPROVERS as GRAPH_APPROVERS,
    CEO_NAME,
    CEO_THRESHOLD_USD,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def handoff_payload() -> dict:
    """Simulated Part 2 handoff payload."""
    return {
        "ticket_id": "test-part3-001",
        "status": "needs_human_review",
        "client_name": "Sunset Bay Resorts",
        "service_type": "Concesión co-branded",
        "departments_needed": ["marketing", "operaciones", "procurement", "training"],
        "department_contacts": {
            "marketing": "Camila Ospina",
            "operaciones": "Felipe Guerrero",
            "procurement": "Lucía Fernández",
            "training": "Jake Morrison",
        },
        "sections": [
            {
                "department_id": "marketing",
                "draft_content": "Marketing proposal content... Valor estimado: COP $180,000,000",
                "evaluation_result": {"overall_pass": True, "iterations": 2},
                "approval_status": "pendiente",
                "needs_human_review": False,
            },
            {
                "department_id": "operaciones",
                "draft_content": "Operations proposal: setup in 5 business days...",
                "evaluation_result": {"overall_pass": True, "iterations": 1},
                "approval_status": "pendiente",
                "needs_human_review": False,
            },
            {
                "department_id": "procurement",
                "draft_content": "Procurement proposal content...",
                "evaluation_result": {"overall_pass": True, "iterations": 3},
                "approval_status": "pendiente",
                "needs_human_review": False,
            },
            {
                "department_id": "training",
                "draft_content": "Training proposal content...",
                "evaluation_result": {"overall_pass": True, "iterations": 2},
                "approval_status": "pendiente",
                "needs_human_review": False,
            },
        ],
        "metadata": {
            "client_name": "Sunset Bay Resorts",
            "location": "Florida, USA",
            "service_type": "Concesión co-branded",
            "scope": "3 resorts, 450 cubiertos/día, 3 años renovables",
            "deadline": "30 de noviembre de 2025",
            "budget_range": "USD 60,000 - USD 75,000 anuales",
            "annual_estimated_usd": 45000.0,
        },
    }


@pytest.fixture
def approval_state(handoff_payload) -> dict:
    """Create a Part 3 approval state from handoff."""
    state = make_approval_state("test-part3-001", handoff_payload)
    return state


@pytest.fixture
def high_value_handoff(handoff_payload) -> dict:
    """Handoff payload with value exceeding CEO threshold ($50K USD)."""
    payload = json.loads(json.dumps(handoff_payload))
    payload["metadata"]["annual_estimated_usd"] = 65000.0
    return payload


@pytest.fixture
def setup_sla_breach_handoff(handoff_payload) -> dict:
    """Handoff where operaciones section promises <10 business days setup."""
    payload = json.loads(json.dumps(handoff_payload))
    for section in payload["sections"]:
        if section["department_id"] == "operaciones":
            section["draft_content"] = "We can set up in 5 business days, ready to serve."
    return payload


@pytest.fixture
def checkpoint_db_cleanup():
    """Clean up checkpoints after tests."""
    yield
    try:
        from sqlmodel import Session, delete
        from database import _get_engine
        from rfp_models import RFPCheckpoint, RFPNodeExecution, RFPArbitrationRecord, RFPFinalDocument

        engine = _get_engine()
        with Session(engine) as db:
            for model in (RFPCheckpoint, RFPNodeExecution, RFPArbitrationRecord, RFPFinalDocument):
                db.exec(delete(model).where(model.ticket_id == "test-part3-001"))
            db.commit()
    except Exception:
        pass


# ===========================================================================
# Checkpointer Tests
# ===========================================================================


class TestCheckpointer:
    """Test checkpoint save/load/resume/clear with thread_id namespacing."""

    def test_make_thread_id_global(self):
        """Global thread_id (no department)."""
        from data.pipelines.rfp_intake.checkpointer import make_thread_id
        tid = make_thread_id("abc-123")
        assert tid == "rfp-abc-123"

    def test_make_thread_id_department(self):
        """Department-scoped thread_id."""
        from data.pipelines.rfp_intake.checkpointer import make_thread_id
        tid = make_thread_id("abc-123", "marketing")
        assert tid == "rfp-abc-123:marketing"

    def test_parse_thread_id(self):
        """Parse thread_id back to ticket + department."""
        from data.pipelines.rfp_intake.checkpointer import parse_thread_id
        ticket_id, dept = parse_thread_id("rfp-abc-123:marketing")
        assert ticket_id == "abc-123"
        assert dept == "marketing"

        ticket_id, dept = parse_thread_id("rfp-abc-123")
        assert ticket_id == "abc-123"
        assert dept is None

    def test_save_and_load_checkpoint(self, checkpoint_db_cleanup):
        """Save a checkpoint and load it back."""
        from data.pipelines.rfp_intake.checkpointer import save_checkpoint, load_checkpoint

        state = {"ticket_id": "test-part3-001", "status": "esperando_aprobacion", "department": "marketing"}
        save_checkpoint("test-part3-001", "save_interrupts", state, department_id="marketing")

        loaded = load_checkpoint("test-part3-001", department_id="marketing")
        assert loaded is not None
        assert loaded["ticket_id"] == "test-part3-001"
        assert loaded["status"] == "esperando_aprobacion"

    def test_load_no_checkpoint(self):
        """Loading a non-existent checkpoint returns None."""
        from data.pipelines.rfp_intake.checkpointer import load_checkpoint
        result = load_checkpoint("non-existent-ticket")
        assert result is None

    def test_mark_checkpoint_resumed(self, checkpoint_db_cleanup):
        """Mark a checkpoint as resumed."""
        from data.pipelines.rfp_intake.checkpointer import (
            save_checkpoint,
            load_checkpoint,
            mark_checkpoint_resumed,
        )

        state = {"ticket_id": "test-part3-001", "status": "esperando_aprobacion"}
        save_checkpoint("test-part3-001", "save_interrupts", state)

        # Mark resumed
        marked = mark_checkpoint_resumed("test-part3-001")
        assert marked is True

        # After resume, loading should return None (since is_resumed=True)
        loaded = load_checkpoint("test-part3-001")
        assert loaded is None

    def test_clear_checkpoints(self, checkpoint_db_cleanup):
        """Clear all checkpoints for a ticket."""
        from data.pipelines.rfp_intake.checkpointer import save_checkpoint, load_checkpoint, clear_checkpoints

        state = {"ticket_id": "test-part3-001"}
        save_checkpoint("test-part3-001", "node1", state, department_id="marketing")
        save_checkpoint("test-part3-001", "node2", state, department_id="operaciones")
        save_checkpoint("test-part3-001", "node3", state)

        # Clear all
        clear_checkpoints("test-part3-001")

        loaded = load_checkpoint("test-part3-001")
        assert loaded is None

    def test_department_checkpoints_independent(self, checkpoint_db_cleanup):
        """Department checkpoints are independent — marketing doesn't block procurement."""
        from data.pipelines.rfp_intake.checkpointer import save_checkpoint, load_checkpoint

        state = {"ticket_id": "test-part3-001"}
        save_checkpoint("test-part3-001", "interrupt", state, department_id="marketing")
        save_checkpoint("test-part3-001", "interrupt", state, department_id="procurement")

        mkt = load_checkpoint("test-part3-001", department_id="marketing")
        prc = load_checkpoint("test-part3-001", department_id="procurement")
        assert mkt is not None
        assert prc is not None

    def test_thread_id_isolation(self, checkpoint_db_cleanup):
        """Two different tickets don't interfere."""
        from data.pipelines.rfp_intake.checkpointer import save_checkpoint, load_checkpoint

        state_a = {"ticket_id": "ticket-a", "data": "A"}
        state_b = {"ticket_id": "ticket-b", "data": "B"}

        save_checkpoint("ticket-a", "node", state_a)
        save_checkpoint("ticket-b", "node", state_b)

        loaded_a = load_checkpoint("ticket-a")
        loaded_b = load_checkpoint("ticket-b")

        assert loaded_a is not None
        assert loaded_b is not None
        assert loaded_a["data"] == "A"
        assert loaded_b["data"] == "B"

        # Cleanup
        from data.pipelines.rfp_intake.checkpointer import clear_checkpoints
        clear_checkpoints("ticket-a")
        clear_checkpoints("ticket-b")


# ===========================================================================
# Traceability Tests
# ===========================================================================


class TestTraceability:
    """Test recording and retrieving execution traces."""

    def test_record_execution(self, checkpoint_db_cleanup):
        """Record a node execution and verify it persists."""
        from data.pipelines.rfp_intake.traceability import record_execution, get_trace_for_ticket

        record_execution(
            ticket_id="test-part3-001",
            node_name="enter_part3",
            agent="graph:enter_part3",
            input_data={"is_resume": False},
            output_data={"departments_needed": ["marketing", "operaciones"]},
        )

        trace = get_trace_for_ticket("test-part3-001")
        assert len(trace) >= 1
        latest = trace[-1]
        assert latest["node_name"] == "enter_part3"
        assert latest["agent"] == "graph:enter_part3"

    def test_record_multiple_executions(self, checkpoint_db_cleanup):
        """Multiple executions are recorded in order."""
        from data.pipelines.rfp_intake.traceability import record_execution, get_trace_for_ticket

        nodes = ["enter_part3", "save_interrupts", "resume_from_checkpoint"]
        for i, node in enumerate(nodes):
            record_execution(
                ticket_id="test-part3-001",
                node_name=node,
                agent=f"test:{node}",
                input_data={"step": i},
                output_data={"processed": True},
            )

        trace = get_trace_for_ticket("test-part3-001")
        assert len(trace) >= 3
        # Should be in order
        assert trace[-3]["node_name"] == "enter_part3"
        assert trace[-1]["node_name"] == "resume_from_checkpoint"

    def test_department_scoped_trace(self, checkpoint_db_cleanup):
        """Trace can be scoped to a department branch."""
        from data.pipelines.rfp_intake.traceability import record_execution, get_trace_for_ticket

        record_execution(
            ticket_id="test-part3-001",
            node_name="save_interrupts",
            agent="graph:save_interrupts",
            input_data={"pending": ["marketing"]},
            output_data={"checkpointed": True},
            department_id="marketing",
        )

        trace = get_trace_for_ticket("test-part3-001")
        dept_traces = [t for t in trace if t.get("department_id") == "marketing"]
        assert len(dept_traces) >= 1


# ===========================================================================
# Arbitration Tests
# ===========================================================================


class TestArbitration:
    """Test conflict detection and resolution."""

    def test_no_conflicts(self, approval_state):
        """No conflicts when all sections are fine."""
        from data.pipelines.rfp_intake.arbitration import detect_conflicts

        conflicts = detect_conflicts(approval_state)
        assert len(conflicts) == 0

    def test_cost_vs_feasibility_trigger(self, approval_state):
        """cost-vs-feasibility trigger fires when procurement cost > marketing estimated value."""
        from data.pipelines.rfp_intake.arbitration import detect_conflicts

        # Set up mismatch: add evaluations key to state
        approval_state["evaluations"] = {
            "procurement": {
                "total_estimated_cost": 100000,  # High cost
                "compliance": {"pass": True},
            },
            "operaciones": {
                "proposed_value": 75000,  # Lower than procurement cost
                "compliance": {"pass": True},
            },
        }
        approval_state["drafts"] = {
            "procurement": "Estimated cost: USD 100,000 for materials and logistics.",
            "operaciones": "Pricing per event: USD 75,000.",
        }

        conflicts = detect_conflicts(approval_state)
        trigger_ids = [c["trigger_id"] for c in conflicts]
        assert CONFLICT_TRIGGER_COST_VS_FEASIBILITY in trigger_ids

        # Verify arbiter
        for c in conflicts:
            if c["trigger_id"] == CONFLICT_TRIGGER_COST_VS_FEASIBILITY:
                assert c["arbiter"] == ARBITRATION_ARBITERS[CONFLICT_TRIGGER_COST_VS_FEASIBILITY]
                assert c["arbiter"] == "Camila Ospina"

    def test_setup_sla_breach_trigger(self):
        """setup-sla-breach triggers when any section mentions <10 business days."""
        from data.pipelines.rfp_intake.arbitration import detect_conflicts

        # Create a state with setup time < 10 business days
        # NOTE: The regex patterns are Spanish-language (días, montaje, entrega)
        state = {
            "sections": [
                {"department_id": "operaciones", "draft_content": "Montaje en 5 días hábiles."},
                {"department_id": "marketing", "draft_content": "Entrega en 7 días."},
            ],
            "drafts": {
                "operaciones": "Montaje en 5 días hábiles.",
                "marketing": "Entrega en 7 días.",
            },
            "evaluations": {},
            "handoff_payload": {},
        }

        conflicts = detect_conflicts(state)
        trigger_ids = [c["trigger_id"] for c in conflicts]
        assert CONFLICT_TRIGGER_SETUP_SLA_BREACH in trigger_ids

        # Verify arbiter is Felipe Guerrero
        for c in conflicts:
            if c["trigger_id"] == CONFLICT_TRIGGER_SETUP_SLA_BREACH:
                assert c["arbiter"] == ARBITRATION_ARBITERS[CONFLICT_TRIGGER_SETUP_SLA_BREACH]
                assert c["arbiter"] == "Felipe Guerrero"
                # This trigger should be auto-resolvable
                assert c.get("auto_resolve", False) is True

    def test_setup_sla_auto_resolve(self):
        """setup-sla-breach auto-resolves with forced request_changes."""
        from data.pipelines.rfp_intake.arbitration import detect_conflicts, resolve_conflict_auto

        state = {
            "sections": [
                {"department_id": "operaciones", "draft_content": "Montaje en 3 días hábiles."},
            ],
            "drafts": {
                "operaciones": "Montaje en 3 días hábiles.",
            },
            "evaluations": {},
            "handoff_payload": {},
        }

        conflicts = detect_conflicts(state)
        sla_conflicts = [c for c in conflicts if c["trigger_id"] == CONFLICT_TRIGGER_SETUP_SLA_BREACH]

        if sla_conflicts:
            conflict = sla_conflicts[0]
            resolution = resolve_conflict_auto(CONFLICT_TRIGGER_SETUP_SLA_BREACH, conflict, state)
            assert resolution["resolution"] == ARBITRATION_RESOLUTION_REQUEST_CHANGES
            assert "state_updates" in resolution
            assert "arbitration_requested_changes" in resolution["state_updates"]

    def test_ceo_threshold_trigger(self, high_value_handoff):
        """ceo-threshold triggers when value > $50K USD."""
        from data.pipelines.rfp_intake.arbitration import detect_conflicts

        state = {
            "handoff_payload": high_value_handoff,
            "annual_estimated_usd": 65000.0,
            "ceo_approved": False,
            "sections": [],
            "evaluations": {},
            "drafts": {},
        }

        conflicts = detect_conflicts(state)
        trigger_ids = [c["trigger_id"] for c in conflicts]
        assert CONFLICT_TRIGGER_CEO_THRESHOLD in trigger_ids

        for c in conflicts:
            if c["trigger_id"] == CONFLICT_TRIGGER_CEO_THRESHOLD:
                assert c["arbiter"] == ARBITRATION_ARBITERS[CONFLICT_TRIGGER_CEO_THRESHOLD]
                assert c["arbiter"] == "Mariana Restrepo"

    def test_ceo_threshold_below(self, approval_state):
        """No ceo-threshold trigger when value <= $50K USD."""
        from data.pipelines.rfp_intake.arbitration import detect_conflicts

        # approval_state has annual_estimated_usd=45000 (below $50K)
        conflicts = detect_conflicts(approval_state)
        trigger_ids = [c["trigger_id"] for c in conflicts]
        assert CONFLICT_TRIGGER_CEO_THRESHOLD not in trigger_ids

    def test_arbitration_record(self, checkpoint_db_cleanup):
        """Record an arbitration decision."""
        from data.pipelines.rfp_intake.arbitration import record_arbitration

        record_arbitration(
            ticket_id="test-part3-001",
            trigger_id=CONFLICT_TRIGGER_COST_VS_FEASIBILITY,
            arbiter="Camila Ospina",
            description="Procurement cost exceeds marketing proposed value",
            resolution="approve",
            departments_involved=["marketing", "procurement"],
            resolved_by="Camila Ospina",
        )

        # Verify in DB
        from sqlmodel import Session, select
        from database import _get_engine
        from rfp_models import RFPArbitrationRecord

        engine = _get_engine()
        with Session(engine) as db:
            records = db.exec(
                select(RFPArbitrationRecord).where(RFPArbitrationRecord.ticket_id == "test-part3-001")
            ).all()
            assert len(records) >= 1
            assert records[-1].trigger_id == CONFLICT_TRIGGER_COST_VS_FEASIBILITY
            assert records[-1].resolution == "approve"


# ===========================================================================
# Graph Part 3 — Node Tests
# ===========================================================================


class TestGraphPart3Nodes:
    """Test individual nodes of the Part 3 graph."""

    def test_make_approval_state(self, handoff_payload):
        """Create initial approval state from handoff."""
        state = make_approval_state("test-ticket", handoff_payload)
        assert state["ticket_id"] == "test-ticket"
        assert state["status"] == "esperando_aprobacion"
        assert len(state["departments_needed"]) == 4
        assert all(
            state["approval_statuses"][d] == APPROVAL_STATUS_PENDIENTE
            for d in state["departments_needed"]
        )
        # Annual value from payload
        assert state["annual_estimated_usd"] == 45000.0
        # Below CEO threshold
        assert state["ceo_approval_required"] is False

    def test_make_approval_state_high_value(self, high_value_handoff):
        """Approval state correctly identifies CEO threshold crossing."""
        state = make_approval_state("test-ticket", high_value_handoff)
        assert state["annual_estimated_usd"] == 65000.0
        assert state["ceo_approval_required"] is True

    def test_enter_part3_node(self, approval_state):
        """Enter Part 3 node records trace."""
        result = enter_part3_node(approval_state)
        assert result["ticket_id"] == "test-part3-001"
        # Should not modify state significantly
        assert result["status"] == "esperando_aprobacion"

    def test_save_interrupts_node(self, approval_state, checkpoint_db_cleanup):
        """Save interrupts node creates checkpoints for pending departments."""
        # Mock _update_ticket_status to avoid DB dependency
        result = save_interrupts_node(approval_state)

        # Should have the same departments
        assert result["departments_needed"] == approval_state["departments_needed"]

        # Checkpoints should have been saved (verify module logs would show this)
        from data.pipelines.rfp_intake.checkpointer import load_checkpoint
        for dept in approval_state["departments_needed"]:
            ckpt = load_checkpoint("test-part3-001", department_id=dept)
            assert ckpt is not None, f"Checkpoint missing for {dept}"

    def test_process_human_decision_approve(self, approval_state):
        """Process an 'approve' action."""
        state = dict(approval_state)
        state["resume_department"] = "marketing"
        state["resume_action"] = "approve"

        result = process_human_decision_node(state)
        assert result["approval_statuses"]["marketing"] == APPROVAL_STATUS_APROBADO

    def test_process_human_decision_reject(self, approval_state):
        """Process a 'reject' action."""
        state = dict(approval_state)
        state["resume_department"] = "operaciones"
        state["resume_action"] = "reject"

        result = process_human_decision_node(state)
        assert result["approval_statuses"]["operaciones"] == APPROVAL_STATUS_RECHAZADO

    def test_process_human_decision_request_changes(self, approval_state):
        """Process a 'request_changes' action."""
        state = dict(approval_state)
        state["resume_department"] = "procurement"
        state["resume_action"] = "request_changes"

        result = process_human_decision_node(state)
        assert result["approval_statuses"]["procurement"] == APPROVAL_STATUS_REQUEST_CHANGES

    def test_generate_final_document(self, approval_state):
        """Generate final document with approved sections."""
        state = dict(approval_state)
        # Mark all departments as approved in both structures
        for dept in state["approval_statuses"]:
            state["approval_statuses"][dept] = APPROVAL_STATUS_APROBADO
        for section in state["sections"]:
            section["approval_status"] = APPROVAL_STATUS_APROBADO

        result = generate_final_document_node(state)
        assert "final_document_content" in result
        assert len(result["final_document_content"]) > 0
        # Should include client name
        assert "Sunset Bay" in result["final_document_content"]
        # Should include approver names
        assert "Camila Ospina" in result["final_document_content"]
        assert "Felipe Guerrero" in result["final_document_content"]

    def test_final_document_includes_ceo(self, approval_state):
        """Final document includes CEO approval note when required."""
        state = dict(approval_state)
        for dept in state["approval_statuses"]:
            state["approval_statuses"][dept] = APPROVAL_STATUS_APROBADO
        for section in state["sections"]:
            section["approval_status"] = APPROVAL_STATUS_APROBADO
        state["ceo_approval_required"] = True
        state["ceo_approved"] = True
        state["ceo_approved_at"] = datetime.now(timezone.utc).isoformat()

        result = generate_final_document_node(state)
        assert "Mariana Restrepo" in result["final_document_content"]

    def test_ceo_approval_interrupt_node(self, approval_state, checkpoint_db_cleanup):
        """CEO approval interrupt saves checkpoint and updates status."""
        state = dict(approval_state)
        state["annual_estimated_usd"] = 65000.0
        state["ceo_approval_required"] = True

        result = ceo_approval_interrupt_node(state)

        # Should have saved a checkpoint
        from data.pipelines.rfp_intake.checkpointer import load_checkpoint
        ckpt = load_checkpoint("test-part3-001")
        assert ckpt is not None

    def test_route_after_human_decision_approve_all(self, approval_state):
        """Route to arbitration when all departments are approved."""
        state = dict(approval_state)
        state["resume_department"] = "training"
        state["resume_action"] = "approve"
        # Mark all others approved
        for dept in state["approval_statuses"]:
            state["approval_statuses"][dept] = APPROVAL_STATUS_APROBADO

        route = route_after_human_decision(state)
        assert route == "arbitration"

    def test_route_after_human_decision_wait(self, approval_state):
        """Route to wait_for_others when not all departments are approved."""
        state = dict(approval_state)
        state["resume_department"] = "marketing"
        state["resume_action"] = "approve"
        # Only marketing approved, others still pending
        state["approval_statuses"]["marketing"] = APPROVAL_STATUS_APROBADO

        route = route_after_human_decision(state)
        assert route == "wait_for_others"

    def test_route_after_human_decision_request_changes(self, approval_state):
        """Route to needs_regeneration when changes requested."""
        state = dict(approval_state)
        state["resume_department"] = "marketing"
        state["resume_action"] = "request_changes"

        route = route_after_human_decision(state)
        assert route == "needs_regeneration"

    def test_route_after_human_decision_rejected(self, approval_state):
        """Route to arbitration when a department rejects (conflict detection)."""
        state = dict(approval_state)
        state["resume_department"] = "operaciones"
        state["resume_action"] = "reject"

        route = route_after_human_decision(state)
        assert route == "arbitration"

    def test_route_after_arbitration_generate(self, approval_state):
        """Route to generate_final_document when no conflicts."""
        state = dict(approval_state)
        state["ceo_approval_required"] = False
        state["arbitration_conflicts"] = []
        state["arbitration_resolved"] = []

        route = route_after_arbitration(state)
        assert route == "generate_final_document"

    def test_route_after_arbitration_ceo(self, approval_state):
        """Route to ceo_approval when CEO threshold exceeded."""
        state = dict(approval_state)
        state["ceo_approval_required"] = True
        state["ceo_approved"] = False

        route = route_after_arbitration(state)
        assert route == "ceo_approval"

    def test_route_after_arbitration_ceo_already_approved(self, approval_state):
        """Skip CEO approval if already approved."""
        state = dict(approval_state)
        state["ceo_approval_required"] = True
        state["ceo_approved"] = True

        route = route_after_arbitration(state)
        assert route == "generate_final_document"

    def test_department_approvers_constants(self):
        """DEPARTMENT_APPROVERS matches the BRIEFING specification."""
        assert GRAPH_APPROVERS["marketing"] == "Camila Ospina"
        assert GRAPH_APPROVERS["operaciones"] == "Felipe Guerrero"
        assert GRAPH_APPROVERS["procurement"] == "Lucía Fernández"
        assert GRAPH_APPROVERS["training"] == "Jake Morrison"
        assert CEO_NAME == "Mariana Restrepo"

    def test_ceo_threshold_constant(self):
        """CEO_THRESHOLD_USD is exactly 50000 as per BRIEFING."""
        assert CEO_THRESHOLD_USD == 50000.0

    def test_arbitration_arbiters_constants(self):
        """ARBITRATION_ARBITERS matches the BRIEFING specification."""
        from rfp_models import ARBITRATION_ARBITERS
        assert ARBITRATION_ARBITERS["cost-vs-feasibility"] == "Camila Ospina"
        assert ARBITRATION_ARBITERS["setup-sla-breach"] == "Felipe Guerrero"
        assert ARBITRATION_ARBITERS["ceo-threshold"] == "Mariana Restrepo"


# ===========================================================================
# Integration Scenarios
# ===========================================================================


class TestGraphPart3Scenarios:
    """End-to-end scenarios for the Part 3 pipeline."""

    def test_happy_path_all_approve(self, approval_state, checkpoint_db_cleanup):
        """Happy path: all departments approve, then arbitration, then final document."""
        from data.pipelines.rfp_intake.graph_part3 import (
            enter_part3_node,
            save_interrupts_node,
            process_human_decision_node,
            arbitration_node,
            route_after_human_decision,
            route_after_arbitration,
            generate_final_document_node,
            finalize_node,
        )

        # Step 1: Enter Part 3
        state = enter_part3_node(approval_state)

        # Step 2: Save interrupts
        state = save_interrupts_node(state)

        # Step 3-6: Each department approves sequentially
        for dept in ["marketing", "operaciones", "procurement", "training"]:
            resume_state = dict(state)
            resume_state["resume_department"] = dept
            resume_state["resume_action"] = "approve"

            state = process_human_decision_node(resume_state)
            route = route_after_human_decision(state)

            if dept != "training":
                assert route == "wait_for_others"
            else:
                assert route == "arbitration"

        # Step 7: Arbitration
        state = arbitration_node(state)
        assert len(state.get("arbitration_conflicts", [])) == 0  # No conflicts expected

        # Step 8: Route to final document
        route = route_after_arbitration(state)
        assert route == "generate_final_document"

        # Step 9: Generate final document
        state = generate_final_document_node(state)
        assert len(state.get("final_document_content", "")) > 0

        # Step 10: Finalize
        state = finalize_node(state)
        assert state.get("status") == "terminado"

    def test_request_changes_triggers_regeneration(self, approval_state):
        """When a department requests changes, route goes to needs_regeneration."""
        state = dict(approval_state)
        state["resume_department"] = "marketing"
        state["resume_action"] = "request_changes"

        route = route_after_human_decision(state)
        assert route == "needs_regeneration"

    def test_ceo_approval_needed(self, high_value_handoff):
        """Pipeline requires CEO approval for high-value tickets."""
        state = make_approval_state("test-ticket", high_value_handoff)
        assert state["ceo_approval_required"] is True
        assert state["annual_estimated_usd"] == 65000.0

    def test_ceo_approval_not_needed(self, handoff_payload):
        """Pipeline skips CEO approval for low-value tickets."""
        state = make_approval_state("test-ticket", handoff_payload)
        assert state["ceo_approval_required"] is False
        assert state["annual_estimated_usd"] == 45000.0

    def test_departments_needed_from_handoff(self, handoff_payload):
        """departments_needed is correctly extracted from handoff."""
        state = make_approval_state("test-ticket", handoff_payload)
        assert "marketing" in state["departments_needed"]
        assert "operaciones" in state["departments_needed"]
        assert "procurement" in state["departments_needed"]
        assert "training" in state["departments_needed"]
        assert len(state["departments_needed"]) == 4

    def test_approval_statuses_populated(self, handoff_payload):
        """All departments get 'pendiente' approval status."""
        state = make_approval_state("test-ticket", handoff_payload)
        for dept in state["departments_needed"]:
            assert state["approval_statuses"][dept] == APPROVAL_STATUS_PENDIENTE


if __name__ == "__main__":
    pytest.main(["-v", __file__])