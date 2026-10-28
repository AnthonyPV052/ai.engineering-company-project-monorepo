"""OAuth 2.1 / OIDC Authentication for MCP Resource Server (MCP Auth).

Implements Protected Resource Metadata as defined by the MCP Auth specification.
Validates Bearer JWTs against an OIDC-compatible provider or a fallback HS256 key.

Architecture
────────────
This module follows the MCP Auth Resource Server mode:
  1. The server serves ``.well-known/oauth-protected-resource`` metadata so that
     any MCP client can discover authentication requirements *before* calling tools.
  2. Every tool invocation goes through ``require_auth``, which validates the
     Bearer token in the ``Authorization`` header.
  3. Token validation: decode JWT → verify signature (JWKS or shared secret) →
     verify issuer & audience → extract scopes claim.
  4. The ``required_scopes`` decorator enforces fine-grained authorization per tool.

Error responses follow RFC 6750 / RFC 9493 for Bearer token errors.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, ParamSpec, TypeVar
from urllib.request import Request as UrllibRequest
from urllib.request import urlopen

from jose import JWTError, jwt
from jose.constants import ALGORITHMS
from pydantic import BaseModel, Field

from .config import config

logger = logging.getLogger("brasaland-mcp.auth")

P = ParamSpec("P")
R = TypeVar("R")

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class AuthError(Exception):
    """Base for all auth failures. Carries the RFC 6750 error details."""

    def __init__(
        self,
        error: str,
        description: str,
        status_code: int = 401,
        scope: str | None = None,
    ) -> None:
        self.error = error
        self.description = description
        self.status_code = status_code
        self.scope = scope
        super().__init__(self._response_body())

    def _response_body(self) -> str:
        return json.dumps(
            {
                "error": self.error,
                "error_description": self.description,
                "scope": self.scope,
            },
            ensure_ascii=False,
        )

    def to_headers(self) -> dict[str, str]:
        """Build WWW-Authenticate header per RFC 6750 §3."""
        params = f'realm="{config.RESOURCE_ID}", error="{self.error}", error_description="{self.description}"'
        if self.scope:
            params += f', scope="{self.scope}"'
        return {"WWW-Authenticate": f"Bearer {params}"}


class InvalidTokenError(AuthError):
    """The access token is invalid, expired, or malformed."""

    def __init__(self, description: str = "The access token is invalid or expired.") -> None:
        super().__init__(error="invalid_token", description=description, status_code=401)


class InsufficientScopeError(AuthError):
    """The token does not have the required scopes."""

    def __init__(self, required: str, token_scopes: str) -> None:
        super().__init__(
            error="insufficient_scope",
            description=f"Token requires scope '{required}', has '{token_scopes}'.",
            status_code=403,
            scope=required,
        )


class MissingAuthError(AuthError):
    """No Authorization header was provided."""

    def __init__(self) -> None:
        super().__init__(
            error="missing_token",
            description="No Bearer token provided in Authorization header.",
            status_code=401,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Protected Resource Metadata (MCP Auth)
# ─────────────────────────────────────────────────────────────────────────────


class ProtectedResourceMetadata(BaseModel):
    """MCP Auth Protected Resource Metadata — served at ``.well-known/oauth-protected-resource``.

    This is the discovery document that tells MCP clients how to authenticate
    against this resource server.  See MCP Auth specification § Resource Server Metadata.
    """

    resource: str = Field(
        default=config.RESOURCE_ID,
        description="The resource server identifier.",
    )
    authorization_servers: list[str] = Field(
        default=[config.OAUTH_ISSUER],
        description="List of authorization server URIs that clients can use to obtain tokens.",
    )
    scopes_supported: list[str] = Field(
        default=config.SCOPES_SUPPORTED,
        description="The set of scopes this resource server understands.",
    )
    bearer_methods_supported: list[str] = Field(
        default=["header"],
        description="Supported methods for presenting Bearer tokens ('header', 'body', 'query').",
    )
    token_endpoint: str = Field(
        default=config.OAUTH_TOKEN_ENDPOINT,
        description="OAuth 2.1 token endpoint for clients to obtain tokens.",
    )
    authorization_endpoint: str = Field(
        default=config.OAUTH_AUTHORIZATION_ENDPOINT,
        description="OAuth 2.1 authorization endpoint for clients to start the flow.",
    )


def get_protected_resource_metadata() -> ProtectedResourceMetadata:
    """Return the MCP Auth Protected Resource Metadata document."""
    return ProtectedResourceMetadata()


# ─────────────────────────────────────────────────────────────────────────────
# Token introspection — cached JWKS client
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TokenPayload:
    """Decoded and validated token payload."""

    sub: str
    scopes: list[str]
    iss: str | None = None
    aud: str | None = None
    exp: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class JwksCache:
    """Simple JWKS cache with TTL."""

    def __init__(self, jwks_uri: str, ttl_seconds: int = 300) -> None:
        self._jwks_uri = jwks_uri
        self._ttl_seconds = ttl_seconds
        self._keys: list[dict[str, Any]] = []
        self._fetched_at: float = 0.0

    def _fetch_keys(self) -> list[dict[str, Any]]:
        try:
            req = UrllibRequest(self._jwks_uri, headers={"Accept": "application/json"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            logger.info("Fetched %d JWK keys from %s", len(data.get("keys", [])), self._jwks_uri)
            return data.get("keys", [])
        except Exception:
            logger.exception("Failed to fetch JWKS from %s", self._jwks_uri)
            return []

    def get_keys(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if now - self._fetched_at > self._ttl_seconds or not self._keys:
            self._keys = self._fetch_keys()
            self._fetched_at = now
        return self._keys


_jwks_cache: JwksCache | None = None


def _get_jwks_cache() -> JwksCache | None:
    global _jwks_cache
    if config.OAUTH_JWKS_URI:
        if _jwks_cache is None:
            _jwks_cache = JwksCache(config.OAUTH_JWKS_URI)
        return _jwks_cache
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Token validation
# ─────────────────────────────────────────────────────────────────────────────


def _decode_fallback(token: str) -> dict[str, Any]:
    """Decode JWT using the fallback HS256 shared secret (development mode)."""
    try:
        payload = jwt.decode(
            token,
            config.FALLBACK_JWT_SECRET,
            algorithms=[ALGORITHMS.HS256],
            audience=config.OAUTH_AUDIENCE,
            issuer=config.OAUTH_EXPECTED_ISSUER,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
        )
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    return payload


def _decode_with_jwks(token: str) -> dict[str, Any]:
    """Decode JWT using remote JWKS (production mode)."""
    cache = _get_jwks_cache()
    if cache is None:
        raise InvalidTokenError("JWKS URI not configured; cannot validate token signature.")

    # Extract kid from header
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    keys = cache.get_keys()
    if not keys:
        raise InvalidTokenError("No JWK keys available for token validation.")

    # Find the matching key
    for key in keys:
        if kid and key.get("kid") != kid:
            continue
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHMS.RS256, ALGORITHMS.ES256],
                audience=config.OAUTH_AUDIENCE,
                issuer=config.OAUTH_EXPECTED_ISSUER,
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                },
            )
            return payload
        except JWTError:
            continue

    raise InvalidTokenError("No matching JWK key could verify the token signature.")


def _extract_scopes(payload: dict[str, Any]) -> list[str]:
    """Extract scopes from the JWT payload.

    Supports both 'scope' (space-separated string per RFC 8693) and 'scp' (array).
    Falls back to an empty list if neither is present.
    """
    scope_str = payload.get("scope", "")
    if isinstance(scope_str, str) and scope_str.strip():
        return scope_str.strip().split()
    scp = payload.get("scp", [])
    if isinstance(scp, list):
        return [s for s in scp if isinstance(s, str)]
    return []


def validate_token(token: str) -> TokenPayload:
    """Validate a Bearer token and return the decoded payload.

    Resolution order:
      1. If USE_FALLBACK_AUTH is True → decode with HS256 shared secret.
      2. If OAUTH_JWKS_URI is set → decode using JWKS.
      3. Otherwise → fallback.

    Raises ``InvalidTokenError`` on any validation failure.
    """
    raw_payload: dict[str, Any]
    if config.USE_FALLBACK_AUTH:
        raw_payload = _decode_fallback(token)
    elif config.OAUTH_JWKS_URI:
        raw_payload = _decode_with_jwks(token)
    else:
        raw_payload = _decode_fallback(token)

    scopes = _extract_scopes(raw_payload)

    return TokenPayload(
        sub=raw_payload.get("sub", "unknown"),
        scopes=scopes,
        iss=raw_payload.get("iss"),
        aud=raw_payload.get("aud"),
        exp=raw_payload.get("exp"),
        raw=raw_payload,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Decorators & middleware helpers
# ─────────────────────────────────────────────────────────────────────────────


def extract_bearer_token(auth_header: str | None) -> str:
    """Extract the Bearer token from the Authorization header value.

    Raises ``MissingAuthError`` if absent or malformed.
    """
    if not auth_header:
        raise MissingAuthError()
    if not auth_header.startswith("Bearer "):
        raise MissingAuthError()
    token = auth_header[7:]
    if not token.strip():
        raise MissingAuthError()
    return token


def require_scopes(*required_scopes: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that enforces OAuth scopes on an MCP tool handler.

    The decorated function **must** accept an ``Authorization`` header via the
    MCP context or via the function arguments.

    Usage::

        @mcp.tool()
        @require_scopes("incidents:read")
        async def get_incident(ctx, incident_id: str) -> str:
            ...
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Extract token from the function's context or kwargs
            # The token is injected by the middleware layer in server.py
            token_payload: TokenPayload | None = kwargs.pop("_token_payload", None)
            if token_payload is None:
                raise MissingAuthError()

            for scope in required_scopes:
                if scope not in token_payload.scopes:
                    raise InsufficientScopeError(
                        required=scope,
                        token_scopes=" ".join(token_payload.scopes) or "(none)",
                    )

            return func(*args, **kwargs)
        return wrapper
    return decorator