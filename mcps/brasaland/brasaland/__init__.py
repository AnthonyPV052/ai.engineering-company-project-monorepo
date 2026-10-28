"""Brasaland MCP Server — exposes Incidents Manager and Inventory services as MCP tools.

This server implements MCP Auth (Resource Server mode) for OAuth 2.1 / OIDC authentication.
Every tool invocation requires a valid Bearer JWT with the appropriate scopes.
"""