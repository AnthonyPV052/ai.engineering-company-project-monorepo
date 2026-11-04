"""Rate limiting middleware for Brasaland AI endpoints.

Prevents uncontrolled cost loops from LLM calls by limiting request rates
to AI-powered endpoints.

Implements a sliding window counter per user/IP with configurable limits.
Uses Redis when available, falls back to in-memory.

Reference: OWASP Top 10 for LLM Applications (LLM07 — Excessive Agency)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Any, Callable

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("api.security.rate_limiter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Rate limits: (requests, window_seconds)
# These are generous for normal use but prevent runaway costs.
DEFAULT_RATE_LIMITS: dict[str, tuple[int, int]] = {
    # LLM-powered endpoints
    "knowledge_query": (30, 60),       # 30 requests per minute
    "chat_ws": (60, 60),               # 60 messages per minute via WebSocket
    "rfp_upload": (10, 60),            # 10 uploads per minute
    "rfp_generate": (5, 60),           # 5 generation triggers per minute
    # Default for unprotected endpoints
    "default": (60, 60),               # 60 requests per minute
}

_REDIS_AVAILABLE: bool | None = None


def _check_redis() -> bool:
    """Check if Redis is available for rate limit storage."""
    global _REDIS_AVAILABLE
    if _REDIS_AVAILABLE is not None:
        return _REDIS_AVAILABLE
    try:
        import redis.asyncio as aioredis
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            _REDIS_AVAILABLE = True
            return True
    except ImportError:
        pass
    _REDIS_AVAILABLE = False
    return False


# ---------------------------------------------------------------------------
# In-memory sliding window counter (fallback when Redis is unavailable)
# ---------------------------------------------------------------------------

class _SlidingWindowCounter:
    """Thread-safe sliding window rate counter."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def _prune(self, key: str, window_seconds: int) -> None:
        """Remove timestamps outside the current window."""
        cutoff = time.monotonic() - window_seconds
        self._windows[key] = [
            ts for ts in self._windows[key] if ts > cutoff
        ]

    async def check_and_increment(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, int]:
        """Check rate limit and increment counter.

        Returns (is_allowed, current_count).
        """
        async with self._lock:
            await self._prune(key, window_seconds)
            current_count = len(self._windows[key])
            if current_count >= max_requests:
                return False, current_count
            self._windows[key].append(time.monotonic())
            return True, current_count + 1


_counter = _SlidingWindowCounter()


async def _check_rate_limit_memory(
    key: str, max_requests: int, window_seconds: int
) -> tuple[bool, int]:
    """Check rate limit using in-memory counter."""
    return await _counter.check_and_increment(key, max_requests, window_seconds)


async def _check_rate_limit_redis(
    key: str, max_requests: int, window_seconds: int
) -> tuple[bool, int]:
    """Check rate limit using Redis (sorted set sliding window)."""
    import redis.asyncio as aioredis

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return await _check_rate_limit_memory(key, max_requests, window_seconds)

    try:
        r = await aioredis.from_url(redis_url, socket_connect_timeout=1)
        now = time.time()
        window_start = now - window_seconds
        pipe = r.pipeline()
        redis_key = f"ratelimit:{key}"
        # Remove old entries
        await pipe.zremrangebyscore(redis_key, 0, window_start)
        # Count current entries
        await pipe.zcard(redis_key)
        # Add current request
        await pipe.zadd(redis_key, {str(now + id(pipe)): now})
        # Set TTL
        await pipe.expire(redis_key, window_seconds * 2)
        results = await pipe.execute()
        current_count = results[1]  # zcard result
        if current_count >= max_requests:
            await r.aclose()
            return False, current_count
        await r.aclose()
        return True, current_count + 1
    except Exception:
        # Redis unavailable, fall back to in-memory
        logger.warning("Redis rate limit unavailable, falling back to memory")
        return await _check_rate_limit_memory(key, max_requests, window_seconds)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_rate_limit(
    key: str,
    *,
    endpoint_type: str = "default",
    max_requests: int | None = None,
    window_seconds: int | None = None,
) -> tuple[bool, int, int]:
    """Check whether ``key`` has exceeded its rate limit.

    Parameters
    ----------
    key : str
        Unique identifier (e.g., ``user:<user_id>`` or ``ip:<client_ip>``).
    endpoint_type : str
        One of ``DEFAULT_RATE_LIMITS`` keys.
    max_requests : int, optional
        Override the default max requests for this endpoint type.
    window_seconds : int, optional
        Override the default window for this endpoint type.

    Returns
    -------
    tuple[bool, int, int]
        ``(is_allowed, current_count, limit)``
    """
    limit = max_requests or DEFAULT_RATE_LIMITS.get(endpoint_type, DEFAULT_RATE_LIMITS["default"])[0]
    window = window_seconds or DEFAULT_RATE_LIMITS.get(endpoint_type, DEFAULT_RATE_LIMITS["default"])[1]

    if _check_redis():
        allowed, count = await _check_rate_limit_redis(key, limit, window)
    else:
        allowed, count = await _check_rate_limit_memory(key, limit, window)

    return allowed, count, limit


def rate_limit_middleware(endpoint_type: str = "default"):
    """Decorator factory for rate-limiting FastAPI endpoints.

    Usage::

        @router.post("/knowledge/query")
        @rate_limit_middleware("knowledge_query")
        async def my_endpoint(...):
            ...

    The decorator extracts the user from ``request.state.user`` (set by
    ``get_current_user``) or from the client IP, then checks the rate limit.
    """
    def decorator(func: Callable) -> Callable:
        from functools import wraps

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                for val in kwargs.values():
                    if isinstance(val, Request):
                        request = val
                        break

            if request is None:
                logger.warning("rate_limit_middleware: no Request found, skipping")
                return await func(*args, **kwargs)

            # Build key from user or IP
            user = getattr(request.state, "user", None)
            if user and hasattr(user, "get"):
                uid = user.get("id", "anonymous")
                key = f"user:{uid}"
            else:
                key = f"ip:{request.client.host if request.client else 'unknown'}"

            allowed, count, limit = await check_rate_limit(key, endpoint_type=endpoint_type)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "rate_limit_exceeded",
                        "message": f"Has excedido el límite de {limit} solicitudes. Intenta de nuevo en un momento.",
                        "retry_after_seconds": 30,
                    },
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


__all__ = [
    "check_rate_limit",
    "rate_limit_middleware",
]