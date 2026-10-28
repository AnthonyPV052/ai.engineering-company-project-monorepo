from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class IncidentCategory(str, Enum):
    equipment_failure = "equipment_failure"
    supply_issue = "supply_issue"
    customer_complaint = "customer_complaint"
    staff_issue = "staff_issue"
    facility_issue = "facility_issue"
    pos_system = "pos_system"
    delivery_issue = "delivery_issue"
    other = "other"


class IncidentStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    discarded = "discarded"


class IncidentOrigin(str, Enum):
    customer = "customer"
    branch = "branch"
    internal = "internal"


class IncidentBranch(str, Enum):
    central = "central"
    medellin_centro = "medellin_centro"
    medellin_laureles = "medellin_laureles"
    medellin_envigado = "medellin_envigado"
    medellin_bello = "medellin_bello"
    medellin_itagui = "medellin_itagui"
    bogota_chapinero = "bogota_chapinero"
    bogota_usaquen = "bogota_usaquen"
    cali_granada = "cali_granada"
    barranquilla_norte = "barranquilla_norte"
    miami_doral = "miami_doral"
    miami_hialeah = "miami_hialeah"
    miami_kendall = "miami_kendall"
    orlando_international = "orlando_international"
    fort_lauderdale = "fort_lauderdale"


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("no puede estar vacío")
        return value


class IncidentStored(IncidentCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IncidentResponse(IncidentStored):
    pass


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus


class IncidentSummaryResponse(BaseModel):
    """Respuesta tipada para GET /api/incidents/summary."""

    by_status: dict[str, int]
    by_category: dict[str, int]
    by_origin: dict[str, int]
    by_branch: dict[str, int]
