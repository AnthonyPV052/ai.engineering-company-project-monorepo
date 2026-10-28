#!/usr/bin/env python
"""Brasaland MCP Server — entry point.

This module:

1. Creates a FastMCP server instance.
2. Registers a custom auth middleware that validates Bearer tokens via OAuth
   (MCP Auth Resource Server mode) before any tool is invoked.
3. Mounts a discovery endpoint at ``.well-known/oauth-protected-resource``.
4. Registers all Incidents Manager and Inventory tools with their required scopes.

Usage
-----
::

    uv run python -m brasaland.server

Or via the MCP CLI::

    mcp run brasaland/server.py

Environment variables (all optional, see ``config.py`` for defaults):

``MCP_BRASALAND_API_BASE_URL``
    Base URL of the backend Brasaland API.
``MCP_BRASALAND_OAUTH_ISSUER``
    OIDC issuer URL for token validation.
``MCP_BRASALAND_OAUTH_JWKS_URI``
    JWKS URI for public key retrieval.
``MCP_BRASALAND_USE_FALLBACK_AUTH``
    If ``true`` (default), validate tokens using the app's JWT shared secret.
``JWT_SECRET_KEY``
    Shared HS256 secret for fallback auth (development only).
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .auth import (
    AuthError,
    InsufficientScopeError,
    InvalidTokenError,
    MissingAuthError,
    TokenPayload,
    extract_bearer_token,
    get_protected_resource_metadata,
    validate_token,
)
from .config import config
from .tools.incidents import (
    ToolApiError as IncidentApiError,
    ToolNotFoundError as IncidentNotFoundError,
    ToolValidationError as IncidentValidationError,
    create_incident as _create_incident,
    get_incident as _get_incident,
    list_incidents as _list_incidents,
    update_incident_status as _update_incident_status,
)
from .tools.inventory import (
    ToolApiError as InventoryApiError,
    ToolNotFoundError as InventoryNotFoundError,
    ToolValidationError as InventoryValidationError,
    WriteAttemptRejected,
    get_product as _get_product,
    list_orders as _list_orders,
    list_products as _list_products,
)

logger = logging.getLogger("brasaland-mcp.server")

# ═══════════════════════════════════════════════════════════════════════
# Auth middleware — injected into every tool call
# ═══════════════════════════════════════════════════════════════════════


async def _resolve_auth(
    authorization: str | None,
    required_scopes: list[str],
) -> TokenPayload:
    """Validate the Bearer token and check required scopes.

    Returns the validated ``TokenPayload`` on success.

    Raises
    ------
    MissingAuthError
        If no Authorization header is present.
    InvalidTokenError
        If the token is invalid, expired, or malformed.
    InsufficientScopeError
        If the token lacks required scopes.
    """
    token_str = extract_bearer_token(authorization)
    payload = validate_token(token_str)
    for scope in required_scopes:
        if scope not in payload.scopes:
            raise InsufficientScopeError(required=scope, token_scopes=" ".join(payload.scopes))
    return payload


# ═══════════════════════════════════════════════════════════════════════
# Error response helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_error(code: str, message: str, http_status: int = 400) -> str:
    return json.dumps({
        "error": code,
        "code": code,
        "message": message,
        "http_status": http_status,
    }, ensure_ascii=False)


def _make_auth_error(error: AuthError) -> str:
    return json.dumps({
        "error": error.error,
        "code": error.error,
        "error_description": error.description,
        "http_status": error.status_code,
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
# MCP Server lifespan
# ═══════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncGenerator[None, None]:
    """Log startup and register the Protected Resource Metadata endpoint."""
    logger.info(
        "Starting %s — auth_mode=%s issuer=%s",
        config.SERVER_NAME,
        "fallback(HS256)" if config.USE_FALLBACK_AUTH else "OIDC(JWKS)",
        config.OAUTH_ISSUER,
    )
    yield
    logger.info("Shutting down %s", config.SERVER_NAME)


# ═══════════════════════════════════════════════════════════════════════
# Create MCP server
# ═══════════════════════════════════════════════════════════════════════

mcp = FastMCP(
    config.SERVER_NAME,
    lifespan=server_lifespan,
    host=config.HOST,
    port=config.PORT,
    log_level=config.LOG_LEVEL,
    # Disable FastMCP's built-in auth so we can implement MCP Auth manually.
    # We handle auth ourselves in every tool handler.
)


# ── Custom HTTP route: OAuth Protected Resource Metadata ──────────────
@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Any) -> Any:
    """Serve MCP Auth Protected Resource Metadata for client discovery."""
    from starlette.responses import JSONResponse

    metadata = get_protected_resource_metadata()
    return JSONResponse(content=metadata.model_dump())

# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: incidents_create
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="incidents_create",
    description=(
        "Create a new incident ticket in the Incidents Manager. "
        "Required scope: incidents:write. "
        "Returns the full incident object including its generated UUID."
    ),
)
async def incidents_create(
    title: str,
    description: str,
    category: str,
    status: str,
    origin: str,
    branch: str,
    authorization: str | None = None,
) -> str:
    """Create a new incident in the Incidents Manager.

    **Required OAuth scope**: ``incidents:write``
    """
    try:
        await _resolve_auth(authorization, ["incidents:write"])
        logger.info("Tool=incidents_create called (title=%s)", title[:50])
        result = await _create_incident(title, description, category, status, origin, branch)
        logger.info("Tool=incidents_create completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=incidents_create auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except IncidentValidationError as exc:
        return _make_error("validation_error", exc.message, http_status=422)
    except IncidentApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=incidents_create unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: incidents_update_status
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="incidents_update_status",
    description=(
        "Transition an incident to a new status using the lifecycle endpoint "
        "(PATCH /api/incidents/{id}/status). Required scope: incidents:write. "
        "Only valid transitions are accepted (see documentation)."
    ),
)
async def incidents_update_status(
    incident_id: str,
    new_status: str,
    authorization: str | None = None,
) -> str:
    """Update the status of an existing incident via the lifecycle endpoint.

    **Required OAuth scope**: ``incidents:write``

    This is the **only** valid way to change an incident's status.  It calls
    the dedicated lifecycle endpoint (PATCH /api/incidents/{id}/status), not
    a generic resource PATCH.
    """
    try:
        await _resolve_auth(authorization, ["incidents:write"])
        logger.info("Tool=incidents_update_status called id=%s new_status=%s", incident_id, new_status)
        result = await _update_incident_status(incident_id, new_status)
        logger.info("Tool=incidents_update_status completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=incidents_update_status auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except IncidentNotFoundError as exc:
        return _make_error("not_found", exc.message, http_status=404)
    except IncidentValidationError as exc:
        return _make_error("validation_error", exc.message, http_status=422)
    except IncidentApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=incidents_update_status unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: incidents_get
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="incidents_get",
    description=(
        "Retrieve a single incident by its UUID. "
        "Required scope: incidents:read. "
        "Returns all fields including status, category, origin, and branch."
    ),
)
async def incidents_get(
    incident_id: str,
    authorization: str | None = None,
) -> str:
    """Retrieve the full details of a single incident.

    **Required OAuth scope**: ``incidents:read``
    """
    try:
        await _resolve_auth(authorization, ["incidents:read"])
        logger.info("Tool=incidents_get called id=%s", incident_id)
        result = await _get_incident(incident_id)
        logger.info("Tool=incidents_get completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=incidents_get auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except IncidentNotFoundError as exc:
        return _make_error("not_found", exc.message, http_status=404)
    except IncidentApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=incidents_get unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: incidents_list
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="incidents_list",
    description=(
        "List incidents with optional filters by status, category, origin, and branch. "
        "Required scope: incidents:read. "
        "Returns an array of matching incident objects."
    ),
)
async def incidents_list(
    status: str | None = None,
    category: str | None = None,
    origin: str | None = None,
    branch: str | None = None,
    authorization: str | None = None,
) -> str:
    """List incidents, optionally filtered by status/category/origin/branch.

    **Required OAuth scope**: ``incidents:read``
    """
    try:
        await _resolve_auth(authorization, ["incidents:read"])
        logger.info("Tool=incidents_list called filters=(status=%s, category=%s, origin=%s, branch=%s)",
                     status, category, origin, branch)
        result = await _list_incidents(status, category, origin, branch)
        logger.info("Tool=incidents_list completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=incidents_list auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except IncidentValidationError as exc:
        return _make_error("validation_error", exc.message, http_status=422)
    except IncidentApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=incidents_list unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: inventory_list_products
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="inventory_list_products",
    description=(
        "[READ-ONLY] List all inventory products (ingredients) with current stock levels. "
        "Required scope: inventory:read. "
        "Optional country filter: CO or US. "
        "This tool CANNOT modify inventory data."
    ),
)
async def inventory_list_products(
    country: str | None = None,
    authorization: str | None = None,
) -> str:
    """List inventory products with optional country filter (CO/US).

    **Required OAuth scope**: ``inventory:read``

    **Guaranteed read-only**: This tool will never create, update, or delete
    inventory data.
    """
    try:
        await _resolve_auth(authorization, ["inventory:read"])
        logger.info("Tool=inventory_list_products called country=%s", country)
        result = await _list_products(country)
        logger.info("Tool=inventory_list_products completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=inventory_list_products auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except InventoryValidationError as exc:
        return _make_error("validation_error", exc.message, http_status=422)
    except InventoryApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=inventory_list_products unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: inventory_get_product
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="inventory_get_product",
    description=(
        "[READ-ONLY] Retrieve a single inventory product by its numeric ID with current stock. "
        "Required scope: inventory:read. "
        "This tool CANNOT modify inventory data."
    ),
)
async def inventory_get_product(
    ingredient_id: int,
    authorization: str | None = None,
) -> str:
    """Retrieve a single inventory product by its numeric ID.

    **Required OAuth scope**: ``inventory:read``
    """
    try:
        await _resolve_auth(authorization, ["inventory:read"])
        logger.info("Tool=inventory_get_product called id=%d", ingredient_id)
        result = await _get_product(ingredient_id)
        logger.info("Tool=inventory_get_product completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=inventory_get_product auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except InventoryNotFoundError as exc:
        return _make_error("not_found", exc.message, http_status=404)
    except InventoryApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=inventory_get_product unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# ── TOOL: inventory_list_orders
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(
    name="inventory_list_orders",
    description=(
        "[READ-ONLY] List all inbound and outbound inventory orders. "
        "Required scope: inventory:read. "
        "Optional filter by ingredient_id. "
        "This tool CANNOT create or modify orders."
    ),
)
async def inventory_list_orders(
    ingredient_id: int | None = None,
    authorization: str | None = None,
) -> str:
    """List all inventory orders (entries and exits) with optional ingredient filter.

    **Required OAuth scope**: ``inventory:read``
    """
    try:
        await _resolve_auth(authorization, ["inventory:read"])
        logger.info("Tool=inventory_list_orders called ingredient_id=%s", ingredient_id)
        result = await _list_orders(ingredient_id)
        logger.info("Tool=inventory_list_orders completed successfully")
        return result
    except AuthError as exc:
        logger.warning("Tool=inventory_list_orders auth_error=%s", exc.error)
        return _make_auth_error(exc)
    except InventoryNotFoundError as exc:
        return _make_error("not_found", exc.message, http_status=404)
    except InventoryApiError as exc:
        return _make_error("api_error", exc.message, http_status=502)
    except Exception as exc:
        logger.exception("Tool=inventory_list_orders unexpected error")
        return _make_error("internal_error", str(exc), http_status=500)


# ═══════════════════════════════════════════════════════════════════════
# Error code reference (documentation)
# ═══════════════════════════════════════════════════════════════════════

ERROR_CODES = {
    "missing_token": "No Bearer token provided in the Authorization header.",
    "invalid_token": "The access token is invalid, expired, or malformed.",
    "insufficient_scope": "The token does not have the required OAuth scope for this operation.",
    "not_found": "The requested resource (incident or product) does not exist.",
    "validation_error": "One or more input parameters failed validation (see message for details).",
    "api_error": "The backend Brasaland API returned an error (HTTP 502 from MCP).",
    "internal_error": "An unexpected error occurred in the MCP server (HTTP 500).",
}


# ═══════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    """Run the MCP server."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger.info("Starting MCP server on %s:%s", config.HOST, config.PORT)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()