"""MCP Client for the Brasaland MCP Server.

This client is used by the support agent to call the MCP Server instead of
directly calling the Incidents Manager HTTP API.  Every tool invocation goes
through the MCP protocol at ``config.MCP_SERVER_URL``.

Usage
-----
::

    from brasaland.client.mcp_client import BrasalandMcpClient

    client = BrasalandMcpClient()
    result = await client.get_incident("some-uuid")
    # result is a dict matching IncidentResponse (see incident_models.py)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("brasaland-mcp.client")

MCP_SERVER_URL = os.getenv(
    "BRASALAND_MCP_SERVER_URL",
    "http://127.0.0.1:8100",  # default port from config.py
)
# Client token to authenticate this service to the MCP server.
# This should be a valid JWT with the required scopes.
MCP_CLIENT_TOKEN = os.getenv("BRASALAND_MCP_CLIENT_TOKEN", "")


@dataclass
class McpResult:
    """Wraps the result of an MCP tool call."""

    success: bool
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    error_code: str | None = None
    error_message: str | None = None


class BrasalandMcpClient:
    """HTTP-based MCP client for the Brasaland MCP Server.

    Uses the MCP HTTP transport to invoke tools on the server.
    In production, use the official MCP SDK client for full protocol support.
    """

    def __init__(self, server_url: str = MCP_SERVER_URL, token: str = MCP_CLIENT_TOKEN) -> None:
        self._server_url = server_url.rstrip("/")
        self._token = token
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    # ── Internal HTTP helpers ────────────────────────────────────────

    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpResult:
        """Invoke an MCP tool via HTTP transport."""
        import httpx

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
            "id": 1,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._server_url}/mcp",
                headers=self._headers,
                json=payload,
                timeout=30.0,
            )

            if resp.status_code == 401:
                body = resp.json()
                return McpResult(
                    success=False,
                    error_code=body.get("error", "missing_token"),
                    error_message=body.get("error_description", "Authentication required"),
                )

            if resp.status_code == 403:
                body = resp.json()
                return McpResult(
                    success=False,
                    error_code=body.get("error", "insufficient_scope"),
                    error_message=body.get("error_description", "Insufficient permissions"),
                )

            if resp.status_code >= 400:
                return McpResult(
                    success=False,
                    error_code="http_error",
                    error_message=f"HTTP {resp.status_code}: {resp.text}",
                )

            result = resp.json()

            # MCP JSON-RPC result structure
            if "result" in result:
                content = result["result"].get("content", [])
                # Extract text content from MCP response
                text_parts = []
                for item in content:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                text = "".join(text_parts)
                if text:
                    try:
                        data = json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        data = text
                    return McpResult(success=True, data=data)

                return McpResult(success=True, data=result["result"])

            if "error" in result:
                err = result["error"]
                return McpResult(
                    success=False,
                    error_code=err.get("code", "mcp_error"),
                    error_message=err.get("message", "Unknown MCP error"),
                )

            return McpResult(success=False, error_code="unknown", error_message="Unexpected response")

    # ── Incidents Manager tools ──────────────────────────────────────

    async def create_incident(
        self,
        title: str,
        description: str,
        category: str,
        status: str,
        origin: str,
        branch: str,
    ) -> McpResult:
        """Create a new incident in the Incidents Manager via MCP.

        Required scope on token: ``incidents:write``
        """
        return await self._call_tool("incidents_create", {
            "title": title,
            "description": description,
            "category": category,
            "status": status,
            "origin": origin,
            "branch": branch,
        })

    async def update_incident_status(self, incident_id: str, new_status: str) -> McpResult:
        """Transition an incident status via the lifecycle endpoint (MCP).

        Required scope on token: ``incidents:write``
        """
        return await self._call_tool("incidents_update_status", {
            "incident_id": incident_id,
            "new_status": new_status,
        })

    async def get_incident(self, incident_id: str) -> McpResult:
        """Retrieve the full details of a single incident via MCP.

        Required scope on token: ``incidents:read``
        """
        return await self._call_tool("incidents_get", {
            "incident_id": incident_id,
        })

    async def list_incidents(
        self,
        status: str | None = None,
        category: str | None = None,
        origin: str | None = None,
        branch: str | None = None,
    ) -> McpResult:
        """List incidents via MCP with optional filters.

        Required scope on token: ``incidents:read``
        """
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if category is not None:
            params["category"] = category
        if origin is not None:
            params["origin"] = origin
        if branch is not None:
            params["branch"] = branch
        return await self._call_tool("incidents_list", params)

    # ── Inventory tools (read-only) ──────────────────────────────────

    async def list_products(self, country: str | None = None) -> McpResult:
        """List inventory products via MCP (read-only).

        Required scope on token: ``inventory:read``
        """
        params: dict[str, str] = {}
        if country is not None:
            params["country"] = country
        return await self._call_tool("inventory_list_products", params)

    async def get_product(self, ingredient_id: int) -> McpResult:
        """Get a single product via MCP (read-only).

        Required scope on token: ``inventory:read``
        """
        return await self._call_tool("inventory_get_product", {
            "ingredient_id": ingredient_id,
        })

    async def list_orders(self, ingredient_id: int | None = None) -> McpResult:
        """List inventory orders via MCP (read-only).

        Required scope on token: ``inventory:read``
        """
        params: dict[str, str] = {}
        if ingredient_id is not None:
            params["ingredient_id"] = str(ingredient_id)
        return await self._call_tool("inventory_list_orders", params)