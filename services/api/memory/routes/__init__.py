"""API routes for the Agent Memory System."""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from memory.models import MemoryProposalResponse, MemorySearchResult
from memory.store import (
    create_proposal,
    get_pending_proposal,
    resolve_proposal,
    search_memories,
    get_audit_log,
    consolidate_memories,
)

logger = logging.getLogger("brasaland.memory.api")
router = APIRouter(prefix="/memory", tags=["memory"])


# --- Request/Response Schemas ---

class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    location_filter: str = ""
    category_filter: str = ""
    limit: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    results: list[MemorySearchResult]
    count: int


class ProposalCreateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    location: str = ""
    category: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    trigger_message: str = ""


class ProposalCreateResponse(BaseModel):
    proposal: Optional[MemoryProposalResponse] = None
    error: str = ""


class ProposalResolveRequest(BaseModel):
    session_id: str = Field(min_length=1)
    proposal_id: UUID
    resolution: str = Field(pattern=r"^(approved|rejected|discarded|edited)$")
    edited_summary: str = ""
    edited_location: str = ""
    edited_category: str = ""
    edited_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    actor: str = "user"
    note: str = ""


class ProposalResolveResponse(BaseModel):
    success: bool
    memory_id: Optional[str] = None
    error: str = ""


class ProposalPendingRequest(BaseModel):
    session_id: str = Field(min_length=1)


class ProposalPendingResponse(BaseModel):
    proposal: Optional[MemoryProposalResponse] = None


# --- Endpoints ---

@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    results = search_memories(
        query_text=request.query,
        limit=request.limit,
        location_filter=request.location_filter or None,
        category_filter=request.category_filter or None,
    )
    return SearchResponse(results=results, count=len(results))


@router.post("/proposal", response_model=ProposalCreateResponse)
def create_memory_proposal(request: ProposalCreateRequest) -> ProposalCreateResponse:
    try:
        proposal = create_proposal(
            session_id=request.session_id,
            summary=request.summary,
            location=request.location,
            category=request.category,
            confidence=request.confidence,
            trigger_message=request.trigger_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if proposal is None:
        return ProposalCreateResponse(
            proposal=None,
            error="A pending proposal already exists for this session. Resolve it first.",
        )
    return ProposalCreateResponse(
        proposal=MemoryProposalResponse(
            id=proposal.id,
            summary=proposal.proposed_summary,
            location=proposal.proposed_location,
            category=proposal.proposed_category,
            confidence=proposal.proposed_confidence,
            trigger_message=proposal.trigger_message,
            status=proposal.status,
            created_at=proposal.created_at,
        ),
    )


@router.post("/proposal/pending", response_model=ProposalPendingResponse)
def get_pending(request: ProposalPendingRequest) -> ProposalPendingResponse:
    proposal = get_pending_proposal(request.session_id)
    if proposal is None:
        return ProposalPendingResponse()
    return ProposalPendingResponse(
        proposal=MemoryProposalResponse(
            id=proposal.id,
            summary=proposal.proposed_summary,
            location=proposal.proposed_location,
            category=proposal.proposed_category,
            confidence=proposal.proposed_confidence,
            trigger_message=proposal.trigger_message,
            status=proposal.status,
            created_at=proposal.created_at,
        ),
    )


@router.post("/proposal/resolve", response_model=ProposalResolveResponse)
def resolve_memory_proposal(request: ProposalResolveRequest) -> ProposalResolveResponse:
    try:
        proposal = resolve_proposal(
            session_id=request.session_id,
            proposal_id=request.proposal_id,
            resolution=request.resolution,
            edited_summary=request.edited_summary,
            edited_location=request.edited_location,
            edited_category=request.edited_category,
            edited_confidence=request.edited_confidence,
            actor=request.actor,
            note=request.note,
        )
        if proposal is None:
            return ProposalResolveResponse(
                success=False,
                error="Proposal not found or already resolved",
            )
        memory_id = str(proposal.approved_memory_id) if proposal.approved_memory_id else None
        return ProposalResolveResponse(success=True, memory_id=memory_id)
    except Exception as exc:
        logger.exception("Failed to resolve proposal")
        return ProposalResolveResponse(success=False, error=str(exc))


@router.post("/consolidate")
def run_consolidation() -> dict:
    stats = consolidate_memories()
    return {"status": "ok", "stats": stats}


@router.get("/audit")
def get_audit(session_id: str = "", limit: int = 50) -> list:
    return get_audit_log(
        session_id=session_id or None,
        limit=min(limit, 200),
    )