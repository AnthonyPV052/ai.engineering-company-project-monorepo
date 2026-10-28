"""Configuration for the Brasaland MCP Server.

All settings loaded from environment variables with sensible defaults for development.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Final

ENV_PREFIX = "MCP_BRASALAND_"


class McpConfig:
    """MCP Server configuration — loaded once at startup from env vars."""

    # ── Server identity ──────────────────────────────────────────────
    HOST: Final[str] = os.getenv(f"{ENV_PREFIX}HOST", "0.0.0.0")
    PORT: Final[int] = int(os.getenv(f"{ENV_PREFIX}PORT", "8100"))
    SERVER_NAME: Final[str] = os.getenv(f"{ENV_PREFIX}SERVER_NAME", "Brasaland MCP Server")
    RESOURCE_ID: Final[str] = os.getenv(f"{ENV_PREFIX}RESOURCE_ID", "brasaland-mcp-server")

    # ── Backend API connection ───────────────────────────────────────
    API_BASE_URL: Final[str] = os.getenv(f"{ENV_PREFIX}API_BASE_URL", "http://127.0.0.1:8020")
    # Service-to-service token for MCP → backend calls (inventory requires auth)
    API_SERVICE_TOKEN: Final[str | None] = os.getenv(f"{ENV_PREFIX}API_SERVICE_TOKEN")
    # For dev: fall back to the app's own JWT secret
    FALLBACK_JWT_SECRET: Final[str] = os.getenv("JWT_SECRET_KEY", "dev-secret-key")

    # ── OAuth / OIDC Provider ────────────────────────────────────────
    # In production, point these at your OIDC-compliant provider.
    OAUTH_ISSUER: Final[str] = os.getenv(f"{ENV_PREFIX}OAUTH_ISSUER", "http://127.0.0.1:8020")
    OAUTH_AUTHORIZATION_ENDPOINT: Final[str] = os.getenv(
        f"{ENV_PREFIX}OAUTH_AUTHORIZATION_ENDPOINT",
        f"{OAUTH_ISSUER}/auth/login",
    )
    OAUTH_TOKEN_ENDPOINT: Final[str] = os.getenv(
        f"{ENV_PREFIX}OAUTH_TOKEN_ENDPOINT",
        f"{OAUTH_ISSUER}/auth/token",
    )
    OAUTH_JWKS_URI: Final[str | None] = os.getenv(f"{ENV_PREFIX}OAUTH_JWKS_URI")
    OAUTH_AUDIENCE: Final[str] = os.getenv(f"{ENV_PREFIX}OAUTH_AUDIENCE", RESOURCE_ID)
    OAUTH_EXPECTED_ISSUER: Final[str] = os.getenv(f"{ENV_PREFIX}OAUTH_EXPECTED_ISSUER", OAUTH_ISSUER)

    # When no external OIDC provider is configured, the server validates
    # tokens using FALLBACK_JWT_SECRET (useful for development).
    USE_FALLBACK_AUTH: Final[bool] = os.getenv(f"{ENV_PREFIX}USE_FALLBACK_AUTH", "true").lower() == "true"

    # ── Logging ──────────────────────────────────────────────────────
    LOG_LEVEL: Final[str] = os.getenv(f"{ENV_PREFIX}LOG_LEVEL", "INFO")

    # ── Scopes ───────────────────────────────────────────────────────
    # The full set of scopes this resource server recognises.
    SCOPES_SUPPORTED: Final[list[str]] = [
        "incidents:read",
        "incidents:write",
        "inventory:read",
    ]


# Singleton
config = McpConfig()