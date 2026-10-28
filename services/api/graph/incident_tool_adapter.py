"""MCP-backed incident tool — uses ``langchain-mcp-adapters``.

**This module replaces ``incident_tool.py`` and ``incident_tool_mcp.py``.**

Instead of calling the Incidents Manager API directly (HTTP GET/POST/PATCH) or
using a hand-rolled urllib JSON-RPC client, it communicates with the Brasaland
MCP Server via the official ``langchain-mcp-adapters`` library.

The public interface is identical to ``incident_tool.py`` so the rest of the
graph (``nodes.py``, ``routing.py``) works unchanged.

Usage
-----
The agent graph already imports from here::

    from graph.incident_tool_adapter import (
        IncidentToolInput,
        IncidentToolOutput,
        extract_incident_id,
        extract_incident_filters,
        lookup_incident,
        list_incidents,
        _INCIDENT_LIST_LIMIT,
    )

Environment variables
---------------------
``BRASALAND_MCP_SERVER_URL``
    URL of the Brasaland MCP Server (default ``http://127.0.0.1:8100/mcp``).
``BRASALAND_MCP_CLIENT_TOKEN``
    JWT string to pass as the ``authorization`` tool argument (default ``""``).
    **Important**: the token is sent as a tool call argument, *not* as an HTTP
    ``Authorization`` header, because the MCP server reads ``authorization``
    from the tool parameters (see ``server.py`` tool definitions).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Literal

from pydantic import BaseModel, Field

from incident_models import IncidentResponse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INCIDENT_LIST_LIMIT = 5
MCP_CLIENT_TIMEOUT = 10.0
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-adapter")
logger = logging.getLogger("api.agent.incidents.adapter")

# ---------------------------------------------------------------------------
# Natural-language patterns (identical to original incident_tool.py)
# ---------------------------------------------------------------------------

_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_LABELED_ID = re.compile(
    r"(?i)\b(?:ticket|incidencia|incidente|caso)\s*(?:n(?:ro|úm)?\.?\s*)?#?([a-z0-9][a-z0-9_-]{2,})\b"
)

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

# ---------------------------------------------------------------------------
# Public types (mirrors incident_tool.py)
# ---------------------------------------------------------------------------


class IncidentToolInput(BaseModel):
    """Input contract for the read-only incident lookup."""

    ticket_id: str | None = Field(
        default=None,
        min_length=1,
        description="ID exacto de la incidencia. Si se omite, no se ejecuta la consulta.",
    )


class IncidentToolOutput(BaseModel):
    """Output contract; ``incident`` mirrors GET /api/incidents/{id}."""

    ticket_id: str | None
    outcome: Literal["found", "not_found", "missing_id", "timeout", "service_error"]
    incident: IncidentResponse | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# langchain-mcp-adapters-based MCP client
# ---------------------------------------------------------------------------


def _get_mcp_connection() -> dict[str, Any]:
    """Build a ``StreamableHttpConnection`` TypedDict for the Brasaland MCP."""
    return {
        "transport": "streamable_http",
        "url": os.getenv("BRASALAND_MCP_SERVER_URL", "http://127.0.0.1:8100/mcp"),
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        "timeout": MCP_CLIENT_TIMEOUT,
    }


def _get_auth_token() -> str:
    """Return the Bearer token (or empty string) from env."""
    return os.getenv("BRASALAND_MCP_CLIENT_TOKEN", "")


async def _async_call_mcp_tool(
    tool_name: str,
    arguments: dict[str, object],
) -> dict | list | None:
    """Call an MCP tool asynchronously using ``langchain-mcp-adapters``.

    This function:
      1. Creates a ``StreamableHttpConnection``.
      2. Opens a session via ``create_session``.
      3. Initializes the session.
      4. Calls the tool, injecting ``authorization`` as a tool argument.
      5. Parses the result text content as JSON.
      6. Returns the parsed data.

    Returns ``None`` if the call fails or the server returns an error.
    """
    from langchain_mcp_adapters.sessions import create_session

    connection = _get_mcp_connection()

    # ── Inject auth token as a tool argument ─────────────────────────────
    token = _get_auth_token()
    if token:
        arguments = {**arguments, "authorization": f"Bearer {token}"}

    async with create_session(connection) as session:
        await session.initialize()

        try:
            result = await session.call_tool(tool_name, arguments)
        except Exception as exc:
            logger.error(
                "MCP SDK call failed tool=%s error_type=%s error=%s",
                tool_name,
                type(exc).__name__,
                exc,
            )
            return None

        # ── Parse CallToolResult content ─────────────────────────────────
        if result.isError:
            logger.warning("MCP tool returned error tool=%s", tool_name)
            # Try to extract error detail from content
            if hasattr(result, "content") and result.content:
                for item in result.content:
                    if item.type == "text" and item.text:
                        try:
                            err_details = json.loads(item.text)
                            logger.warning(
                                "MCP error details: %s", err_details
                            )
                        except (json.JSONDecodeError, ValueError):
                            pass
            return None

        content = getattr(result, "content", [])
        for item in content:
            if item.type == "text" and item.text:
                try:
                    return json.loads(item.text)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.error(
                        "MCP result parse error tool=%s error=%s",
                        tool_name,
                        exc,
                    )
                    return {"_raw_text": item.text}

    return None


def _call_mcp_tool(
    tool_name: str,
    arguments: dict[str, object],
) -> dict | list | None:
    """Synchronous wrapper around ``_async_call_mcp_tool``.

    Uses ``asyncio.run()`` to bridge the sync → async boundary.
    Each call creates a fresh event loop, which is the recommended
    pattern for short-lived async tasks from sync code.
    """
    try:
        return asyncio.run(_async_call_mcp_tool(tool_name, arguments))
    except Exception as exc:
        logger.error(
            "MCP call failed (sync wrapper) tool=%s error_type=%s error=%s",
            tool_name,
            type(exc).__name__,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public API (same signatures as incident_tool.py)
# ---------------------------------------------------------------------------


def lookup_incident(tool_input: IncidentToolInput) -> IncidentToolOutput:
    """Look up an incident via the MCP Server (sync).

    Calls ``incidents_get`` on the Brasaland MCP Server using
    ``langchain-mcp-adapters`` internally.
    """
    incident_id = tool_input.ticket_id
    if not incident_id:
        return IncidentToolOutput(
            ticket_id=None, outcome="missing_id", error="missing_id"
        )

    def _call() -> IncidentToolOutput:
        result = _call_mcp_tool(
            "incidents_get", {"incident_id": incident_id}
        )
        if result is None:
            return IncidentToolOutput(
                ticket_id=incident_id,
                outcome="service_error",
                error="service_error",
            )

        if isinstance(result, dict):
            # Check for structured error responses from MCP server
            if result.get("error") or result.get("code"):
                code = (
                    result.get("code", "")
                    or result.get("error", "")
                )
                if code in ("not_found", "missing_token", "invalid_token"):
                    if code == "not_found":
                        return IncidentToolOutput(
                            ticket_id=incident_id, outcome="not_found"
                        )
                return IncidentToolOutput(
                    ticket_id=incident_id,
                    outcome="service_error",
                    error=code,
                )

            try:
                incident = IncidentResponse(**result)
                return IncidentToolOutput(
                    ticket_id=incident_id,
                    outcome="found",
                    incident=incident,
                )
            except Exception as exc:
                logger.error(
                    "IncidentResponse parse error id=%s error=%s",
                    incident_id,
                    exc,
                )
                return IncidentToolOutput(
                    ticket_id=incident_id,
                    outcome="service_error",
                    error="parse_error",
                )

        return IncidentToolOutput(
            ticket_id=incident_id,
            outcome="service_error",
            error="unexpected_type",
        )

    future: Future[IncidentToolOutput] = _EXECUTOR.submit(_call)
    try:
        return future.result(timeout=MCP_CLIENT_TIMEOUT)
    except FutureTimeout:
        future.cancel()
        logger.warning(
            "MCP timeout en lookup_incident ticket_id=%s", incident_id
        )
        return IncidentToolOutput(
            ticket_id=incident_id, outcome="timeout", error="timeout"
        )
    except Exception:
        logger.exception(
            "MCP error en lookup_incident ticket_id=%s", incident_id
        )
        return IncidentToolOutput(
            ticket_id=incident_id,
            outcome="service_error",
            error="service_error",
        )


def list_incidents(
    filters: dict[str, str],
    *,
    limit: int = _INCIDENT_LIST_LIMIT,
) -> list[dict[str, object]]:
    """List incidents via the MCP Server (sync).

    Calls ``incidents_list`` on the Brasaland MCP Server using
    ``langchain-mcp-adapters`` internally.
    """
    arguments: dict[str, object] = {}
    for key in ("status", "category", "origin", "branch"):
        if key in filters and filters[key]:
            arguments[key] = filters[key]

    result = _call_mcp_tool("incidents_list", arguments)
    if result is None:
        return []

    if isinstance(result, list):
        return [dict(item) for item in result][:limit]

    return []


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


__all__ = [
    "IncidentToolInput",
    "IncidentToolOutput",
    "extract_incident_id",
    "extract_incident_filters",
    "lookup_incident",
    "list_incidents",
    "_INCIDENT_LIST_LIMIT",
]