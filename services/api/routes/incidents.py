from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from tinydb import Query as TinyQuery

from cache import cached, invalidate_cache
from database import get_incidents_db
from incident_models import (
    IncidentBranch,
    IncidentCategory,
    IncidentCreate,
    IncidentOrigin,
    IncidentResponse,
    IncidentStatus,
    IncidentStatusUpdate,
    IncidentStored,
    IncidentSummaryResponse,
)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

ALLOWED_STATUS_TRANSITIONS = {
    IncidentStatus.open.value: {IncidentStatus.in_progress.value, IncidentStatus.discarded.value},
    IncidentStatus.in_progress.value: {IncidentStatus.resolved.value, IncidentStatus.discarded.value},
    IncidentStatus.resolved.value: set(),
    IncidentStatus.discarded.value: set(),
}


def _to_response(document: dict) -> IncidentResponse:
    return IncidentResponse(**document)


def _find_incident(incident_id: str) -> dict | None:
    query = TinyQuery()
    document = get_incidents_db().get(query.id == incident_id)
    return dict(document) if document is not None else None


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate) -> IncidentResponse:
    stored = IncidentStored(**payload.model_dump())
    db = get_incidents_db()
    db.insert(stored.model_dump(mode="json"))
    # Invalidar caché del summary y del listado porque los datos cambiaron
    invalidate_cache("/api/incidents")
    return IncidentResponse(**stored.model_dump())


@router.get("/summary", response_model=IncidentSummaryResponse)
@cached(ttl_seconds=15.0)  # TTL 15s: los datos cambian con cada creación/transición, pero es aceptable un pequeño desfase en el backoffice
def get_incidents_summary(request: Request) -> IncidentSummaryResponse:
    documents = [dict(document) for document in get_incidents_db().all()]

    def totals(values: list[str], field: str) -> dict[str, int]:
        counter = Counter(document.get(field) for document in documents)
        return {value: counter.get(value, 0) for value in values}

    return IncidentSummaryResponse(
        by_status=totals([item.value for item in IncidentStatus], "status"),
        by_category=totals([item.value for item in IncidentCategory], "category"),
        by_origin=totals([item.value for item in IncidentOrigin], "origin"),
        by_branch=totals([item.value for item in IncidentBranch], "branch"),
    )


@router.get("", response_model=list[IncidentResponse])
def list_incidents(
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    origin: IncidentOrigin | None = Query(default=None),
    branch: IncidentBranch | None = Query(default=None),
    category: IncidentCategory | None = Query(default=None),
) -> list[IncidentResponse]:
    result: list[IncidentResponse] = []
    for document in get_incidents_db().all():
        item = dict(document)
        if status_filter is not None and item.get("status") != status_filter.value:
            continue
        if origin is not None and item.get("origin") != origin.value:
            continue
        if branch is not None and item.get("branch") != branch.value:
            continue
        if category is not None and item.get("category") != category.value:
            continue
        result.append(_to_response(item))
    return result


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: str) -> IncidentResponse:
    incident = _find_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidencia no encontrada")
    return _to_response(incident)


@router.patch("/{incident_id}/status", response_model=IncidentResponse)
def update_incident_status(incident_id: str, payload: IncidentStatusUpdate) -> IncidentResponse:
    incident = _find_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidencia no encontrada")

    current_status = incident["status"]
    next_status = payload.status.value
    if next_status not in ALLOWED_STATUS_TRANSITIONS[current_status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "field": "status",
                "message": f"No se puede cambiar una incidencia de '{current_status}' a '{next_status}'.",
            },
        )

    updated_at = datetime.now(timezone.utc).isoformat()
    query = TinyQuery()
    db = get_incidents_db()
    db.update({"status": next_status, "updated_at": updated_at}, query.id == incident_id)
    updated = db.get(query.id == incident_id)
    # Invalidar caché del summary y del incidente individual
    invalidate_cache("/api/incidents")
    return _to_response(dict(updated))
