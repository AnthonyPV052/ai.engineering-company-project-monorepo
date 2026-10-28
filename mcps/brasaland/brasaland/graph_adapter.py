"""MCP-based incident tool — replaces the direct HTTP incident_tool.py.

This module provides the same **synchronous** interface as the original
``incident_tool.py`` (``lookup_incident``, ``list_incidents``,
``extract_incident_id``, ``extract_incident_filters``, ``IncidentToolInput``,
``IncidentToolOutput``) but delegates all calls to the Brasaland MCP Server
instead of calling the Incidents Manager HTTP API directly.

Switchover
----------
To activate this module, change the import in ``graph/nodes.py`` from::

    from graph.incident_tool import ...

to::

    from graph.incident_tool_mcp import ...

The rest of the graph code (``nodes.py``, ``routing.py``) works unchanged
because the public interface is identical.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Literal
from urllib.request import Request as UrllibRequest
from urllib.request import urlopen

from pydantic import BaseModel, Field

from incident_models import IncidentResponse

# ---------------------------------------------------------------------------
# MCP Client — uses /mcp endpoint (JSON-RPC over HTTP) with synchronous HTTP
# ---------------------------------------------------------------------------

_INCIDENT_LIST_LIMIT = 5
MCP_CLIENT_TIMEOUT = 10.0
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-client")
logger = logging.getLogger("api.agent.incidents.mcp")

_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_LABELED_ID = re.compile(
    r"(?i)\b(?:ticket|incidencia|incidente|caso)\s*(?:n(?:ro|úm)?\.?\s*)?#?([a-z0-9][a-z0-9_-]{2,})\b"
)

# -- Filters for natural language list queries (same as original) --

_INCIDENT_STATUS_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\babiert[ao]s?\b"), "open"),
    (re.compile(r"(?i)\bopen\b"), "open"),
    (re.compile(r"(?i)\ben\s*progreso\b"), "in_progress"),
    (re.compile(r"(?i)\bin.progress\b"), "in_progress"),
    (re.compile(r"(?i)\b(?:resuelt[ao]s?|cerrad[ao]s?)\b"), "resolved"),
    (re.compile(r"(?i)\bresolved\b"), "resolved"),
    (re.compile(r"(?i)\bdescartad[ao]s?\b"), "discarded"),
    (re.compile(r"(?i)\bdiscarded\b"), "discarded"),
]

_INCIDENT_CATEGORY_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\b(?:equip[oa]|equipment)\w*\b"), "equipment_failure"),
    (re.compile(r"(?i)\b(?:proveedor|suministro|supply)\w*\b"), "supply_issue"),
    (re.compile(r"(?i)\b(?:cliente|customer)\w*\b"), "customer_complaint"),
    (re.compile(r"(?i)\b(?:personal|staff)\w*\b"), "staff_issue"),
    (re.compile(r"(?i)\b(?:instalaci[oó]n|facility)\w*\b"), "facility_issue"),
    (re.compile(r"(?i)\b(?:pos|sistema|tpv|system)\b"), "pos_system"),
    (re.compile(r"(?i)\b(?:entrega|delivery)\w*\b"), "delivery_issue"),
]

_INCIDENT_ORIGIN_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\bcliente\b"), "customer"),
    (re.compile(r"(?i)\bcustomer\b"), "customer"),
    (re.compile(r"(?i)\bsucursal\b"), "branch"),
    (re.compile(r"(?i)\bintern[ao]\b"), "internal"),
    (re.compile(r"(?i)\binternal\b"), "internal"),
]

_INCIDENT_BRANCH_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\bmedell[ií]n\s*centro\b"), "medellin_centro"),
    (re.compile(r"(?i)\bmedell[ií]n\s*laureles\b"), "medellin_laureles"),
    (re.compile(r"(?i)\bmedell[ií]n\s*envigado\b"), "medellin_envigado"),
    (re.compile(r"(?i)\bmedell[ií]n\s*bello\b"), "medellin_bello"),
    (re.compile(r"(?i)\bmedell[ií]n\s*itag[uú]i\b"), "medellin_itagui"),
    (re.compile(r"(?i)\bbogot[áa]\s*chapinero\b"), "bogota_chapinero"),
    (re.compile(r"(?i)\bbogot[áa]\s*[uú]saqu[eé]n\b"), "bogota_usaquen"),
    (re.compile(r"(?i)\bcali\s*granada\b"), "cali_granada"),
    (re.compile(r"(?i)\bbarranquilla\s*norte\b"), "barranquilla_norte"),
    (re.compile(r"(?i)\bmiami\s*doral\b"), "miami_doral"),
    (re.compile(r"(?i)\bmiami\s*hialeah\b"), "miami_hialeah"),
    (re.compile(r"(?i)\bmiami\s*kendall\b"), "miami_kendall"),
    (re.compile(r"(?i)\borlando\b"), "orlando_international"),
    (re.compile(r"(?i)\bfort\s*lauderdale\b"), "fort_lauderdale"),
]

# ── Public interface (same as original incident_tool.py) ──────────────


class IncidentToolInput(BaseModel):
    """Input contract for the read-only incident lookup."""

    ticket_id: str | None = Field(
        default=None,
        min_length=1,
        description="ID exacto de la incidencia. Si se omite, no se ejecuta la consulta.",
    )


class IncidentToolOutput(BaseModel):
    """Output contract; mirrors original but sourced from MCP."""

    ticket_id: str | None
    outcome: Literal["found", "not_found", "missing_id", "timeout", "service_error"]
    incident: IncidentResponse | None = None
    error: str | None = None


# ── Internal synchronous MCP client ────────────────────────────────────


def _mcp_call(tool_name: str, arguments: dict[str, object]) -> dict | list | None:
    """Call an MCP tool synchronously via the JSON-RPC HTTP endpoint.

    Uses urllib (same as original incident_tool) for zero-dependency sync calls.
    """
    MCP_SERVER_URL = os.getenv("BRASALAND_MCP_SERVER_URL", "http://127.0.0.1:8100").rstrip("/")
    token = os.getenv("BRASALAND_MCP_CLIENT_TOKEN", "")

    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": 1,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = UrllibRequest(f"{MCP_SERVER_URL}/mcp", data=payload, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=MCP_CLIENT_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("MCP call failed tool=%s error=%s", tool_name, exc)
        return None

    if "result" in body:
        content = body["result"].get("content", [])
        text_parts = []
        for item in content:
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        text = "".join(text_parts)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return text
        return body["result"]

    if "error" in body:
        logger.error("MCP error tool=%s code=%s message=%s", tool_name,
                      body["error"].get("code"), body["error"].get("message"))
    return None


# ── Synchronous MCP-backed implementations ─────────────────────────────


def lookup_incident(tool_input: IncidentToolInput) -> IncidentToolOutput:
    """Look up an incident via the MCP Server (sync).

    Mirrors the original ``lookup_incident`` signature.
    """
    incident_id = tool_input.ticket_id
    if not incident_id:
        return IncidentToolOutput(ticket_id=None, outcome="missing_id", error="missing_id")

    def _call() -> IncidentToolOutput:
        result = _mcp_call("incidents_get", {"incident_id": incident_id})
        if result is None:
            return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="service_error")

        if isinstance(result, dict):
            # Check if it's an error response
            if result.get("error") or result.get("code"):
                if result.get("code") == "not_found" or result.get("error") == "not_found":
                    return IncidentToolOutput(ticket_id=incident_id, outcome="not_found")
                return IncidentToolOutput(ticket_id=incident_id, outcome="service_error",
                                          error=result.get("code", "mcp_error"))
            try:
                incident = IncidentResponse(**result)
                return IncidentToolOutput(ticket_id=incident_id, outcome="found", incident=incident)
            except Exception:
                return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="parse_error")

        return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="unexpected_type")

    future: Future[IncidentToolOutput] = _EXECUTOR.submit(_call)
    try:
        return future.result(timeout=MCP_CLIENT_TIMEOUT)
    except FutureTimeout:
        future.cancel()
        logger.warning("MCP timeout en lookup_incident ticket_id=%s", incident_id)
        return IncidentToolOutput(ticket_id=incident_id, outcome="timeout", error="timeout")
    except Exception:
        logger.exception("MCP error en lookup_incident ticket_id=%s", incident_id)
        return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="service_error")


def list_incidents(
    filters: dict[str, str],
    *,
    limit: int = _INCIDENT_LIST_LIMIT,
) -> list[dict[str, object]]:
    """List incidents via the MCP Server (sync).

    Args:
        filters: Dict with optional keys ``status``, ``category``, ``origin``, ``branch``.
        limit: Maximum number of results to return.

    Returns:
        List of incident dicts.
    """
    arguments: dict[str, object] = {}
    for key in ("status", "category", "origin", "branch"):
        if key in filters and filters[key]:
            arguments[key] = filters[key]

    result = _mcp_call("incidents_list", arguments)
    if result is None:
        return []

    if isinstance(result, list):
        return [dict(item) for item in result][:limit]

    return []


# ── Natural language extraction (kept from original, no MCP dependency) ──


def extract_incident_id(question: str) -> str | None:
    """Find an explicit ticket identifier without guessing one from prose."""
    uuid_match = _UUID.search(question)
    if uuid_match:
        return uuid_match.group(0)
    labeled_match = _LABELED_ID.search(question)
    return labeled_match.group(1) if labeled_match else None


def extract_incident_filters(question: str) -> dict[str, str]:
    """Extract filters (status, category, origin, branch) from natural language."""
    filters: dict[str, str] = {}

    for pattern, value in _INCIDENT_STATUS_FILTERS:
        if pattern.search(question):
            filters["status"] = value
            break
    for pattern, value in _INCIDENT_CATEGORY_FILTERS:
        if pattern.search(question):
            filters["category"] = value
            break
    for pattern, value in _INCIDENT_ORIGIN_FILTERS:
        if pattern.search(question):
            filters["origin"] = value
            break
    for pattern, value in _INCIDENT_BRANCH_FILTERS:
        if pattern.search(question):
            filters["branch"] = value
            break

    return filters