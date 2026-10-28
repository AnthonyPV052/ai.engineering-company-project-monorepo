"""Read-only MCP tools for the Brasaland Inventory service.

This module ONLY exposes read operations (GET).  Any attempt to mutate
inventory data — even accidentally — is explicitly rejected by the tools.
Write operations (inbound/outbound orders) are NOT exposed as MCP tools.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import config

logger = logging.getLogger("brasaland-mcp.tools.inventory")

_INVENTORY_PRODUCTS = "/inventory/products"
_INVENTORY_ORDERS = "/inventory/orders"
_HTTP_TIMEOUT = 15.0


class ToolNotFoundError(Exception):
    """The requested resource (e.g. ingredient) does not exist."""
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


class WriteAttemptRejected(Exception):
    """Explicitly raised when a caller attempts to modify inventory via a
    read-only tool.  The MCP server MUST reject any write on inventory."""
    def __init__(self, message: str = "Write operations are not allowed on inventory tools. "
                                        "This server only exposes read-only inventory access.") -> None:
        self.message = message
        super().__init__(message)


def _headers() -> dict[str, str]:
    hdrs = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = config.API_SERVICE_TOKEN
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs


async def _api_get(path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """GET from the backend API."""
    url = f"{config.API_BASE_URL}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 404:
            raise ToolNotFoundError("The requested resource was not found.")
        if resp.status_code >= 400:
            raise ToolApiError(f"Backend API error ({resp.status_code}): {resp.text}")
        return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────


async def list_products(country: str | None = None) -> str:
    """List all inventory products (ingredients) with their current stock levels.

    **Read-only** — this tool cannot modify inventory.  Any write attempt is
    explicitly rejected by the server.

    Parameters
    ----------
    country : str | None
        Optional country filter.  ``CO`` for Colombia, ``US`` for USA.

    Returns
    -------
    str
        JSON-encoded array of products.  Each product has:
        - ``id`` (int): Internal product identifier.
        - ``name`` (str): Product name.
        - ``sku`` (str): Internal SKU, e.g. ``BRS-BEEF-001``.
        - ``unit`` (str): Unit of measure (e.g. ``kg``, ``litro``, ``unidad``).
        - ``category`` (str): Product category (e.g. ``meat``, ``produce``, ``sauce``,
          ``beverage``, ``packaging``, ``cleaning``).
        - ``country`` (str): Country code (``CO`` or ``US``).
        - ``current_stock`` (float): Current stock level calculated as
          total inbound minus total outbound.

    Raises
    ------
    ToolValidationError
        If the country filter is not ``CO`` or ``US``.
    ToolNotFoundError
        If no products are found.
    ToolApiError
        If the backend API returns an unexpected error.
    WriteAttemptRejected
        Explicitly raised if a caller tries to pass write-related parameters.
    """
    params: dict[str, str] = {}
    if country is not None:
        country_upper = country.upper()
        if country_upper not in ("CO", "US"):
            raise ToolValidationError(f"Invalid country '{country}'. Must be 'CO' or 'US'.")
        params["country"] = country_upper

    result = await _api_get(_INVENTORY_PRODUCTS, params=params if params else None)
    logger.info("Listed products count=%d", len(result) if isinstance(result, list) else 0)
    return json.dumps(result, ensure_ascii=False, default=str)


async def get_product(ingredient_id: int) -> str:
    """Retrieve a single inventory product (ingredient) by its ID with current stock.

    **Read-only** — this tool cannot modify inventory.

    Parameters
    ----------
    ingredient_id : int
        Numeric ID of the ingredient/product.

    Returns
    -------
    str
        JSON-encoded product object with fields: ``id``, ``name``, ``sku``,
        ``unit``, ``category``, ``country``, ``current_stock``.

    Raises
    ------
    ToolNotFoundError
        If no product exists with the given ID.
    ToolApiError
        If the backend API returns an unexpected error.
    """
    result = await _api_get(f"{_INVENTORY_PRODUCTS}/{ingredient_id}")
    logger.info("Retrieved product id=%d", ingredient_id)
    return json.dumps(result, ensure_ascii=False, default=str)


async def list_orders(ingredient_id: int | None = None) -> str:
    """List all inbound and outbound inventory orders.

    **Read-only** — this tool cannot create or modify orders.

    Parameters
    ----------
    ingredient_id : int | None
        Optional filter to show only orders for a specific ingredient.

    Returns
    -------
    str
        JSON-encoded array of orders.  Each order has:
        - ``id`` (int): Order identifier.
        - ``type`` (str): ``"entry"`` for inbound (supplier delivery) or
          ``"exit"`` for outbound (consumption/waste).
        - ``ingredient_id`` (int): FK to the ingredient.
        - ``ingredient_name`` (str): Name of the ingredient.
        - ``ingredient_sku`` (str): SKU of the ingredient.
        - ``quantity`` (float): Quantity moved.
        - ``supplier_name`` (str | None): Supplier name (entries only).
        - ``reason`` (str | None): ``"consumption"`` or ``"waste"`` (exits only).
        - ``location_id`` (int): Branch location identifier (1–14).
        - ``created_at`` (str): ISO-8601 timestamp.
        - ``user_uuid`` (str): UUID of the user who registered the order.

    Raises
    ------
    ToolNotFoundError
        If no orders are found.
    ToolApiError
        If the backend API returns an unexpected error.
    WriteAttemptRejected
        Explicitly raised if a caller tries to pass write-related parameters.
    """
    params: dict[str, str] = {}
    if ingredient_id is not None:
        params["ingredient_id"] = str(ingredient_id)

    result = await _api_get(_INVENTORY_ORDERS, params=params if params else None)
    logger.info("Listed orders count=%d", len(result) if isinstance(result, list) else 0)
    return json.dumps(result, ensure_ascii=False, default=str)


# ── Sentinel: explicitly reject writes ─────────────────────────────────


async def reject_write_attempt(
    action: str = "unspecified",
    **kwargs: object,
) -> str:
    """Explicitly reject any attempt to modify inventory data.

    This is NOT a real tool — it exists as a guardrail.  If a caller attempts
    to use the MCP server to create, update, or delete inventory records,
    this function returns a clear error message explaining that inventory
    write operations are not exposed via MCP.

    Parameters
    ----------
    action : str
        The write action that was attempted (e.g. ``create_inbound_order``).

    Returns
    -------
    str
        A JSON-encoded error message explaining that write operations are
        not allowed on inventory tools.

    Raises
    ------
    WriteAttemptRejected
        Always raised to explicitly signal the write rejection.
    """
    msg = (
        f"Write operation '{action}' is not permitted on inventory data through MCP. "
        "This server only exposes read-only inventory access. "
        "To modify inventory, use the Brasaland Supplier Directory API directly "
        "at /inventory/orders/inbound or /inventory/orders/outbound with appropriate authentication."
    )
    logger.warning("Write attempt rejected: action=%s kwargs=%s", action, kwargs)
    raise WriteAttemptRejected(msg)