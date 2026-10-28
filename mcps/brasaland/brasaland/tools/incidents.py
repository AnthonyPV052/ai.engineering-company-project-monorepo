"""MCP tools for the Brasaland Incidents Manager.

Provides tools to create, update status, and query incidents from the Incidents
Manager API.  All calls go through the backend API at ``config.API_BASE_URL``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx

from ..config import config

logger = logging.getLogger("brasaland-mcp.tools.incidents")

# ── API paths (mirrors the existing routes/incidents.py) ──────────────
_INCIDENTS_BASE = "/api/incidents"
_HTTP_TIMEOUT = 15.0  # seconds

# ── Status lifecycle (copied from routes/incidents.py) ────────────────
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "discarded"},
    "in_progress": {"resolved", "discarded"},
    "resolved": set(),
    "discarded": set(),
}

VALID_STATUSES = {"open", "in_progress", "resolved", "discarded"}
VALID_CATEGORIES = {
    "equipment_failure", "supply_issue", "customer_complaint",
    "staff_issue", "facility_issue", "pos_system", "delivery_issue", "other",
}
VALID_ORIGINS = {"customer", "branch", "internal"}
VALID_BRANCHES = {
    "central", "medellin_centro", "medellin_laureles", "medellin_envigado",
    "medellin_bello", "medellin_itagui", "bogota_chapinero", "bogota_usaquen",
    "cali_granada", "barranquilla_norte", "miami_doral", "miami_hialeah",
    "miami_kendall", "orlando_international", "fort_lauderdale",
}


# ── Helpers ───────────────────────────────────────────────────────────


def _headers(service_token: str | None = None) -> dict[str, str]:
    hdrs = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # Use service token if configured; otherwise rely on backend allowing
    # internal requests (no auth for incidents which uses TinyDB).
    token = service_token or config.API_SERVICE_TOKEN
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs


async def _api_get(path: str, params: dict[str, str] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """GET from the backend API."""
    url = f"{config.API_BASE_URL}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 404:
            raise ToolNotFoundError("The requested incident was not found.")
        if resp.status_code == 422:
            raise ToolValidationError(f"Validation error: {resp.text}")
        if resp.status_code >= 400:
            raise ToolApiError(f"Backend API error ({resp.status_code}): {resp.text}")
        return resp.json()


async def _api_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST to the backend API. Returns the JSON response body."""
    url = f"{config.API_BASE_URL}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(), json=body, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 422:
            raise ToolValidationError(f"Validation error: {resp.text}")
        if resp.status_code >= 400:
            raise ToolApiError(f"Backend API error ({resp.status_code}): {resp.text}")
        doc = resp.json()
        return doc


async def _api_patch(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """PATCH the backend API. Returns the JSON response body."""
    url = f"{config.API_BASE_URL}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=_headers(), json=body, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 404:
            raise ToolNotFoundError("The requested incident was not found.")
        if resp.status_code == 400:
            detail = resp.json().get("detail", resp.text)
            raise ToolValidationError(f"Bad request: {detail}")
        if resp.status_code >= 400:
            raise ToolApiError(f"Backend API error ({resp.status_code}): {resp.text}")
        return resp.json()


# ── Domain error types ────────────────────────────────────────────────


class ToolNotFoundError(Exception):
    """The requested resource (e.g. incident) does not exist."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ToolValidationError(Exception):
    """The input parameters failed validation."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ToolApiError(Exception):
    """The backend API returned an unexpected error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ToolAuthError(Exception):
    """Authentication or authorization failure."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────


async def create_incident(
    title: str,
    description: str,
    category: str,
    status: str,
    origin: str,
    branch: str,
) -> str:
    """Create a new incident in the Incidents Manager.

    Parameters
    ----------
    title : str
        Short title of the incident (1–200 characters).
    description : str
        Detailed description of the incident (1–5000 characters).
    category : str
        Incident category. One of: ``equipment_failure``, ``supply_issue``,
        ``customer_complaint``, ``staff_issue``, ``facility_issue``,
        ``pos_system``, ``delivery_issue``, ``other``.
    status : str
        Initial status. One of: ``open``, ``in_progress``, ``resolved``,
        ``discarded``.
    origin : str
        Where the incident was reported. One of: ``customer``, ``branch``,
        ``internal``.
    branch : str
        Branch associated with the incident. One of: ``central``,
        ``medellin_centro``, ``medellin_laureles``, ``medellin_envigado``,
        ``medellin_bello``, ``medellin_itagui``, ``bogota_chapinero``,
        ``bogota_usaquen``, ``cali_granada``, ``barranquilla_norte``,
        ``miami_doral``, ``miami_hialeah``, ``miami_kendall``,
        ``orlando_international``, ``fort_lauderdale``.

    Returns
    -------
    str
        JSON-encoded incident object with ``id``, ``title``, ``description``,
        ``category``, ``status``, ``origin``, ``branch``, ``created_at``,
        and ``updated_at`` fields.

    Raises
    ------
    ToolValidationError
        If any field fails validation (e.g. invalid category, missing title).
    ToolApiError
        If the backend API returns an unexpected error.
    """
    # ── Validate domain values ────────────────────────────────────────
    if category not in VALID_CATEGORIES:
        raise ToolValidationError(
            f"Invalid category '{category}'. Valid values: {', '.join(sorted(VALID_CATEGORIES))}."
        )
    if status not in VALID_STATUSES:
        raise ToolValidationError(
            f"Invalid status '{status}'. Valid values: {', '.join(sorted(VALID_STATUSES))}."
        )
    if origin not in VALID_ORIGINS:
        raise ToolValidationError(
            f"Invalid origin '{origin}'. Valid values: {', '.join(sorted(VALID_ORIGINS))}."
        )
    if branch not in VALID_BRANCHES:
        raise ToolValidationError(
            f"Invalid branch '{branch}'. Valid values: {', '.join(sorted(VALID_BRANCHES))}."
        )
    if not title.strip():
        raise ToolValidationError("title must not be empty.")
    if not description.strip():
        raise ToolValidationError("description must not be empty.")

    body = {
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "status": status,
        "origin": origin,
        "branch": branch,
    }

    result = await _api_post(_INCIDENTS_BASE, body)
    logger.info("Created incident id=%s", result.get("id"))
    return json.dumps(result, ensure_ascii=False, default=str)


async def update_incident_status(incident_id: str, new_status: str) -> str:
    """Transition an incident to a new status using the lifecycle endpoint.

    This tool calls ``PATCH /api/incidents/{id}/status`` — the **only** valid
    way to change an incident's status.  Direct PATCH on the incident resource
    is not supported.

    Parameters
    ----------
    incident_id : str
        UUID of the incident to update.
    new_status : str
        Target status. One of: ``open``, ``in_progress``, ``resolved``,
        ``discarded``.

    Allowed transitions
    -------------------
    - open        → in_progress, discarded
    - in_progress → resolved, discarded
    - resolved    → (none — terminal)
    - discarded   → (none — terminal)

    Returns
    -------
    str
        JSON-encoded incident object with the updated status.

    Raises
    ------
    ToolNotFoundError
        If no incident exists with the given ID.
    ToolValidationError
        If the transition is not allowed or the status value is invalid.
    ToolApiError
        If the backend API returns an unexpected error.
    """
    if new_status not in VALID_STATUSES:
        raise ToolValidationError(
            f"Invalid status '{new_status}'. Valid values: {', '.join(sorted(VALID_STATUSES))}."
        )

    body = {"status": new_status}
    result = await _api_patch(f"{_INCIDENTS_BASE}/{incident_id}/status", body)
    logger.info("Updated incident id=%s status=%s", incident_id, new_status)
    return json.dumps(result, ensure_ascii=False, default=str)


async def get_incident(incident_id: str) -> str:
    """Retrieve the full details of a single incident by its ID.

    Parameters
    ----------
    incident_id : str
        UUID of the incident to retrieve.

    Returns
    -------
    str
        JSON-encoded incident object with ``id``, ``title``, ``description``,
        ``category``, ``status``, ``origin``, ``branch``, ``created_at``,
        and ``updated_at`` fields.

    Raises
    ------
    ToolNotFoundError
        If no incident exists with the given ID.
    ToolApiError
        If the backend API returns an unexpected error.
    """
    result = await _api_get(f"{_INCIDENTS_BASE}/{incident_id}")
    logger.info("Retrieved incident id=%s", incident_id)
    return json.dumps(result, ensure_ascii=False, default=str)


async def list_incidents(
    status: str | None = None,
    category: str | None = None,
    origin: str | None = None,
    branch: str | None = None,
) -> str:
    """List incidents with optional filters.

    Parameters
    ----------
    status : str | None
        Filter by status: ``open``, ``in_progress``, ``resolved``, ``discarded``.
    category : str | None
        Filter by category: ``equipment_failure``, ``supply_issue``,
        ``customer_complaint``, ``staff_issue``, ``facility_issue``,
        ``pos_system``, ``delivery_issue``, ``other``.
    origin : str | None
        Filter by origin: ``customer``, ``branch``, ``internal``.
    branch : str | None
        Filter by branch name (e.g. ``medellin_centro``, ``miami_doral``).

    Returns
    -------
    str
        JSON-encoded array of matching incident objects.  Each incident has
        ``id``, ``title``, ``description``, ``category``, ``status``,
        ``origin``, ``branch``, ``created_at``, and ``updated_at`` fields.

    Raises
    ------
    ToolValidationError
        If any filter value is invalid.
    ToolApiError
        If the backend API returns an unexpected error.
    """
    params: dict[str, str] = {}
    if status is not None:
        if status not in VALID_STATUSES:
            raise ToolValidationError(
                f"Invalid status '{status}'. Valid values: {', '.join(sorted(VALID_STATUSES))}."
            )
        params["status"] = status
    if category is not None:
        if category not in VALID_CATEGORIES:
            raise ToolValidationError(
                f"Invalid category '{category}'. Valid values: {', '.join(sorted(VALID_CATEGORIES))}."
            )
        params["category"] = category
    if origin is not None:
        if origin not in VALID_ORIGINS:
            raise ToolValidationError(
                f"Invalid origin '{origin}'. Valid values: {', '.join(sorted(VALID_ORIGINS))}."
            )
        params["origin"] = origin
    if branch is not None:
        if branch not in VALID_BRANCHES:
            raise ToolValidationError(
                f"Invalid branch '{branch}'. Valid values: {', '.join(sorted(VALID_BRANCHES))}."
            )
        params["branch"] = branch

    result = await _api_get(_INCIDENTS_BASE, params=params if params else None)
    logger.info("Listed incidents count=%d", len(result) if isinstance(result, list) else 0)
    return json.dumps(result, ensure_ascii=False, default=str)