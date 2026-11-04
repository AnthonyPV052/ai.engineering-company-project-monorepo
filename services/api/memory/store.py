"""Core storage layer for the Agent Memory System.

Implements read/write interface against PostgreSQL + pgvector.
The agent NEVER writes directly -- always via proposal -> confirmation.

Explicit interface:
  - store_memory()         - writes an approved fact (only after user confirmation)
  - search_memories()      - searches relevant memories by embedding
  - get_memory()           - gets a memory by ID
  - get_pending_proposal() - gets the pending proposal for a session
  - create_proposal()      - creates a proposal (never writes directly)
  - resolve_proposal()     - approves/rejects/discards/edits a proposal
  - log_audit_event()      - registers an auditable event
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlmodel import Session, select, text

from database import _get_engine
from memory.models import (
    AgentMemory,
    MemoryProposal,
    MemoryAuditLog,
    MemorySearchResult,
    ProposalStatus,
    AuditEventType,
)

logger = logging.getLogger("brasaland.memory.store")

SIMILARITY_THRESHOLD = 0.85
MAX_SEARCH_RESULTS = 5
ALLOWED_CATEGORIES = {"horarios", "proveedores", "incidentes_conocidos", "preferencias", "general"}
_FORBIDDEN_PATTERNS = (
    re.compile(r"\b(?:payroll|salary|compensation|nómina|salario|sueldo|compensación)\b", re.I),
    re.compile(r"\b(?:brasa\s*points|cliente|customer)\b.{0,100}\b(?:nombre|teléfono|email|correo|dirección|identific|account|cuenta)\b", re.I),
)


def validate_memory_fact(summary: str, category: str) -> None:
    """Enforce the explicit briefing exclusions before creating a proposal or memory."""
    if not summary or not summary.strip():
        raise ValueError("La memoria debe contener un hecho no vacío")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError("Categoría de memoria no permitida")
    if any(pattern.search(summary) for pattern in _FORBIDDEN_PATTERNS):
        raise ValueError("El contenido coincide con una categoría prohibida por el briefing")


# ---------------------------------------------------------------------------
# Embedding helper (reuses same gateway as RAG, separate store)
# ---------------------------------------------------------------------------


def _compute_embedding(text: str) -> list[float]:
    from rag import embed as _rag_embed
    return _rag_embed(text)


def _get_session() -> Session:
    return Session(_get_engine())


# ---------------------------------------------------------------------------
# Memory CRUD (only after user approval)
# ---------------------------------------------------------------------------


def store_memory(
    summary: str,
    location: str = "",
    category: str = "",
    confidence: float = 1.0,
    approved_by: str = "",
    embedding_vector: Optional[list[float]] = None,
) -> AgentMemory:
    """Persist an approved fact as agent memory.

    Must ONLY be called AFTER the user has explicitly approved.
    NEVER call directly from the agent.
    """
    validate_memory_fact(summary, category)
    if embedding_vector is None:
        embedding_vector = _compute_embedding(summary)
    if len(embedding_vector) != 1024:
        raise ValueError(f"El embedding debe tener 1024 dimensiones, recibió {len(embedding_vector)}")
    memory_id = uuid4()
    now = datetime.now(timezone.utc)
    with _get_session() as session:
        session.execute(text("""
            INSERT INTO agent_memories
                (id, summary, location, category, embedding, confidence, approved_by, approved_at, created_at, updated_at)
            VALUES
                (:id, :summary, :location, :category, CAST(:embedding AS vector(1024)), :confidence, :approved_by, :approved_at, :created_at, :updated_at)
        """), {
            "id": memory_id, "summary": summary, "location": location, "category": category,
            "embedding": json.dumps(embedding_vector), "confidence": confidence,
            "approved_by": approved_by, "approved_at": now, "created_at": now, "updated_at": now,
        })
        session.commit()
        memory = session.get(AgentMemory, memory_id)

    logger.info(
        "Memory stored id=%s location=%s category=%s confidence=%.2f",
        memory.id, location, category, confidence,
    )
    return memory


def search_memories(
    query_text: str,
    limit: int = MAX_SEARCH_RESULTS,
    threshold: float = SIMILARITY_THRESHOLD,
    location_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
) -> list[MemorySearchResult]:
    """Search memories by cosine similarity of their embedding.

    Only returns non-archived memories with score > threshold.
    This is what the agent calls BEFORE responding to find relevant context.
    """
    query_embedding = _compute_embedding(query_text)
    if len(query_embedding) != 1024:
        raise ValueError(f"El embedding debe tener 1024 dimensiones, recibió {len(query_embedding)}")

    conditions = ["archived = FALSE"]
    params: dict[str, Any] = {
        "query_embedding": json.dumps(query_embedding),
        "threshold": threshold,
        "limit": limit,
    }

    if location_filter:
        if len(location_filter) > 128:
            raise ValueError("location_filter supera el máximo de 128 caracteres")
        conditions.append("location = :location_filter")
        params["location_filter"] = location_filter
    if category_filter:
        if category_filter not in ALLOWED_CATEGORIES:
            raise ValueError("Categoría de búsqueda no permitida")
        conditions.append("category = :category_filter")
        params["category_filter"] = category_filter

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT
            id,
            summary,
            location,
            category,
            confidence,
            1 - (embedding <=> CAST(:query_embedding AS vector(1024))) AS score,
            usage_count
        FROM agent_memories
        WHERE {where_clause}
          AND 1 - (embedding <=> CAST(:query_embedding AS vector(1024))) > :threshold
        ORDER BY score DESC
        LIMIT :limit
    """)

    with _get_session() as session:
        rows = session.execute(sql, params).fetchall()

    results = []
    for row in rows:
        results.append(MemorySearchResult(
            id=row.id,
            summary=row.summary,
            location=row.location,
            category=row.category,
            confidence=row.confidence,
            score=float(row.score),
            usage_count=row.usage_count,
        ))

    if results:
        _bump_usage_counts([r.id for r in results])
        for result in results:
            log_audit_event(
                event_type=AuditEventType.MEMORY_USED.value,
                description="Memoria recuperada para contexto del agente.",
                event_data={"memory_id": str(result.id), "score": result.score, "query": query_text},
                actor="agent",
            )

    return results


def _bump_usage_counts(memory_ids: list[UUID]) -> None:
    """Increment usage_count and update last_used_at for retrieved memories."""
    with _get_session() as session:
        for mid in memory_ids:
            stmt = select(AgentMemory).where(AgentMemory.id == mid)
            memory = session.exec(stmt).first()
            if memory:
                memory.usage_count = (memory.usage_count or 0) + 1
                memory.last_used_at = datetime.now(timezone.utc)
                session.add(memory)
        session.commit()


def get_memory(memory_id: UUID) -> Optional[AgentMemory]:
    """Get a single memory by ID."""
    with _get_session() as session:
        stmt = select(AgentMemory).where(AgentMemory.id == memory_id)
        return session.exec(stmt).first()


# ---------------------------------------------------------------------------
# Proposal Management
# ---------------------------------------------------------------------------


def create_proposal(
    session_id: str,
    summary: str,
    location: str = "",
    category: str = "",
    confidence: float = 0.8,
    trigger_message: str = "",
    conversation_id: Optional[UUID] = None,
) -> Optional[MemoryProposal]:
    """Create a pending memory proposal.

    Only ONE pending proposal per session is allowed.
    If one already exists, returns None.
    """
    validate_memory_fact(summary, category)

    proposal = MemoryProposal(
        id=uuid4(),
        session_id=session_id,
        conversation_id=conversation_id,
        proposed_summary=summary,
        proposed_location=location,
        proposed_category=category,
        proposed_confidence=confidence,
        trigger_message=trigger_message,
        status=ProposalStatus.PENDING.value,
    )

    with _get_session() as session:
        try:
            session.add(proposal)
            session.commit()
            session.refresh(proposal)
        except Exception as exc:
            session.rollback()
            # The partial unique index resolves concurrent creates safely.
            if "uq_pending_proposal_per_session" in str(exc) or "unique" in str(exc).lower():
                return None
            raise

    log_audit_event(
        event_type=AuditEventType.PROPOSAL_CREATED.value,
        description=f"Proposal created: {summary[:100]}",
        event_data={
            "proposal_id": str(proposal.id),
            "summary": summary,
            "location": location,
            "category": category,
            "confidence": confidence,
            "source_message": trigger_message,
        },
        session_id=session_id,
        actor="agent",
        proposal_id=proposal.id,
    )

    logger.info(
        "Proposal created id=%s session=%s summary=%s",
        proposal.id, session_id, summary[:80],
    )
    return proposal


def get_pending_proposal(session_id: str) -> Optional[MemoryProposal]:
    """Get the currently pending proposal for a session."""
    with _get_session() as session:
        stmt = select(MemoryProposal).where(
            MemoryProposal.session_id == session_id,
            MemoryProposal.status == ProposalStatus.PENDING.value,
        )
        return session.exec(stmt).first()


def resolve_proposal(
    session_id: str,
    proposal_id: UUID,
    resolution: str,
    edited_summary: str = "",
    edited_location: str = "",
    edited_category: str = "",
    edited_confidence: float = 0.8,
    actor: str = "user",
    note: str = "",
) -> Optional[MemoryProposal]:
    """Atomically resolve a proposal and persist an approved memory."""
    if resolution not in {status.value for status in ProposalStatus}:
        raise ValueError("Unsupported proposal resolution")

    with _get_session() as session:
        proposal = session.exec(select(MemoryProposal).where(
            MemoryProposal.id == proposal_id,
            MemoryProposal.session_id == session_id,
            MemoryProposal.status == ProposalStatus.PENDING.value,
        ).with_for_update()).first()
        if proposal is None:
            return None

        memory_id = None
        if resolution in {ProposalStatus.APPROVED.value, ProposalStatus.EDITED.value}:
            summary = edited_summary or proposal.proposed_summary
            location = edited_location or proposal.proposed_location
            category = edited_category or proposal.proposed_category
            confidence = proposal.proposed_confidence if edited_confidence == 0.8 else edited_confidence
            validate_memory_fact(summary, category)
            vector = _compute_embedding(summary)
            if len(vector) != 1024:
                raise ValueError("El embedding debe tener 1024 dimensiones")
            memory_id = uuid4()
            now = datetime.now(timezone.utc)
            session.execute(text("""
                INSERT INTO agent_memories
                    (id, summary, location, category, embedding, confidence, approved_by, approved_at, created_at, updated_at)
                VALUES
                    (:id, :summary, :location, :category, CAST(:embedding AS vector(1024)), :confidence, :approved_by, :approved_at, :created_at, :updated_at)
            """), {
                "id": memory_id, "summary": summary, "location": location, "category": category,
                "embedding": json.dumps(vector), "confidence": confidence, "approved_by": actor,
                "approved_at": now, "created_at": now, "updated_at": now,
            })

        proposal.status = resolution
        proposal.resolved_by = actor
        proposal.resolved_at = datetime.now(timezone.utc)
        proposal.resolution_note = note
        if memory_id:
            proposal.approved_memory_id = memory_id
        session.add(proposal)
        session.add(MemoryAuditLog(
            proposal_id=proposal.id,
            event_type=resolution,
            description=f"Proposal {resolution}: {proposal.proposed_summary}",
            event_data={"proposal_id": str(proposal.id), "resolution": resolution,
                        "summary": proposal.proposed_summary, "edited_summary": edited_summary,
                        "approved_memory_id": str(memory_id) if memory_id else None,
                        "message": note},
            session_id=session_id,
            actor=actor,
        ))
        session.commit()
        session.refresh(proposal)
        return proposal

def discard_proposal_by_topic_change(session_id: str, proposal_id: UUID) -> None:
    """Discard the proposal because the user changed the topic.

    Never assume approval by silence or ambiguity.
    """
    resolve_proposal(
        session_id=session_id,
        proposal_id=proposal_id,
        resolution="discarded",
        actor="system",
        note="Proposal discarded due to topic change (no explicit confirmation)",
    )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def log_audit_event(
    event_type: str,
    description: str = "",
    event_data: Optional[dict[str, Any]] = None,
    session_id: str = "",
    actor: str = "system",
    proposal_id: Optional[UUID] = None,
) -> MemoryAuditLog:
    """Register an event in the audit table."""
    if event_data is None:
        event_data = {}

    entry = MemoryAuditLog(
        proposal_id=proposal_id,
        event_type=event_type,
        description=description,
        event_data=event_data,
        session_id=session_id,
        actor=actor,
    )

    with _get_session() as session:
        session.add(entry)
        session.commit()
        session.refresh(entry)

    return entry


def get_audit_log(
    session_id: Optional[str] = None,
    proposal_id: Optional[UUID] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> list[MemoryAuditLog]:
    """Get audit log with optional filters."""
    with _get_session() as session:
        query = select(MemoryAuditLog)
        if session_id:
            query = query.where(MemoryAuditLog.session_id == session_id)
        if proposal_id:
            query = query.where(MemoryAuditLog.proposal_id == proposal_id)
        if event_type:
            query = query.where(MemoryAuditLog.event_type == event_type)
        query = query.order_by(MemoryAuditLog.created_at.desc()).limit(limit)
        return list(session.exec(query).all())


# ---------------------------------------------------------------------------
# Consolidation and Cleanup
# ---------------------------------------------------------------------------


def consolidate_memories() -> dict[str, int]:
    """Consolidate memories: deduplicate and merge similar entries.

    Strategy:
    - Preserve distinct facts; never replace a group with only its highest-confidence row.
    - Archive only low-confidence records or unused records older than 90 days.
    - Entries with confidence < 0.3 are archived automatically.
    - Entries with usage_count = 0 and older than 90 days are archived.

    Returns:
        Dict with consolidation stats.
    """
    now = datetime.now(timezone.utc)
    stats: dict[str, int] = {
        "archived_low_confidence": 0,
        "archived_unused": 0,
        "consolidated": 0,
        "total_before": 0,
        "total_after": 0,
    }

    with _get_session() as session:
        # Count before
        total_before = len(session.exec(
            select(AgentMemory).where(AgentMemory.archived == False)
        ).all())
        stats["total_before"] = total_before

        # 1. Archive low-confidence entries (confidence < 0.3)
        low_conf = session.exec(
            select(AgentMemory).where(
                AgentMemory.archived == False,
                AgentMemory.confidence < 0.3,
            )
        ).all()
        for memory in low_conf:
            memory.archived = True
            memory.archived_at = now
            session.add(memory)
            stats["archived_low_confidence"] += 1

        # 2. Archive unused entries (usage_count == 0, older than 90 days)
        from sqlalchemy import or_
        try:
            from dateutil.relativedelta import relativedelta
            cutoff = now - relativedelta(days=90)
        except ImportError:
            # fallback: approximate 90 days
            cutoff = datetime(now.year, now.month - 3 if now.month > 3 else 1,
                              now.day, tzinfo=timezone.utc)

        unused = session.exec(
            select(AgentMemory).where(
                AgentMemory.archived == False,
                AgentMemory.usage_count == 0,
                AgentMemory.created_at < cutoff,
                or_(
                    AgentMemory.last_used_at.is_(None),
                    AgentMemory.last_used_at < cutoff,
                ),
            )
        ).all()
        for memory in unused:
            memory.archived = True
            memory.archived_at = now
            session.add(memory)
            stats["archived_unused"] += 1

        # Grouping is a retrieval/maintenance dimension, not permission to
        # discard distinct facts. No lossy auto-merge is performed.

        session.commit()

        # Count after
        total_after = len(session.exec(
            select(AgentMemory).where(AgentMemory.archived == False)
        ).all())
        stats["total_after"] = total_after

    if stats["archived_low_confidence"] or stats["archived_unused"]:
        log_audit_event(
            event_type=AuditEventType.CONSOLIDATED.value,
            description="Memoria obsoleta archivada; no se fusionaron hechos distintos.",
            event_data=stats,
            actor="system",
        )
    return stats