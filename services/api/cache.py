"""Caché en memoria con TTL para endpoints de la API.

Estrategia
----------
Se utiliza un diccionario global con expiración por tiempo (TTL).
No se usa Redis porque el stack actual no lo incluye y porque
el volumen de datos del proyecto no lo justifica.

Seguridad
---------
- NO se cachean datos de sesión, privados o personalizados
  (auth/me, profiles/me, users/{id}, etc.).
- Los endpoints que requieren autenticación pero devuelven
  datos NO personalizados (ej. /inventory/products) SÍ se
  cachean porque la respuesta es idéntica para cualquier
  usuario autenticado. La clave de caché NO incluye el user_id.

Invalidación
------------
Los endpoints de escritura (POST/PUT/PATCH/DELETE) deben
llamar a invalidate_cache() con el prefijo del endpoint
afectado para mantener la frescura de los datos.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from fastapi import Request

# ---------------------------------------------------------------------------
# Diccionario de caché
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}  # key → (expiry_timestamp, value)

P = ParamSpec("P")
R = TypeVar("R")


def _build_cache_key(request: Request) -> str:
    """Construye una clave de caché a partir del path y query parameters.

    La clave incluye explícitamente los parámetros de consulta para
    que dos peticiones con distintos filtros obtengan su propia entrada.
    """
    path = request.url.path
    query = request.url.query  # ej. "country=CO&category=meat"
    return f"{path}?{query}" if query else path


def get_cached(key: str) -> Any | None:
    """Retorna el valor cachead si existe y no ha expirado."""
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        del _cache[key]
        return None
    return value


def set_cached(key: str, value: Any, ttl_seconds: float) -> None:
    """Almacena un valor en caché con un TTL en segundos."""
    _cache[key] = (time.monotonic() + ttl_seconds, value)


def invalidate_cache(prefix: str) -> int:
    """Invalida todas las entradas de caché cuya clave empiece por *prefix*.

    Args:
        prefix: Prefijo de ruta, ej. "/api/incidents" o "/inventory/products".

    Returns:
        Número de entradas invalidadas.
    """
    keys_to_delete = [key for key in _cache if key.startswith(prefix)]
    for key in keys_to_delete:
        del _cache[key]
    return len(keys_to_delete)


def invalidate_all_cache() -> int:
    """Limpia completamente la caché.

    Útil en tests o reinicios forzados.
    """
    count = len(_cache)
    _cache.clear()
    return count


def cached(ttl_seconds: float = 30.0) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorador para cachear la respuesta de un endpoint FastAPI.

    La clave de caché se construye automáticamente a partir del
    path y los query parameters de la request.

    Args:
        ttl_seconds: Tiempo de vida de la entrada en caché, en segundos.

    Uso:
        @router.get("/products")
        @cached(ttl_seconds=10.0)
        def list_products(...): ...
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Buscar el objeto Request en los argumentos
            request: Request | None = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                for value in kwargs.values():
                    if isinstance(value, Request):
                        request = value
                        break

            if request is not None:
                key = _build_cache_key(request)
                cached_value = get_cached(key)
                if cached_value is not None:
                    return cached_value  # type: ignore[return-value]

                result = func(*args, **kwargs)
                set_cached(key, result, ttl_seconds)
                return result

            # Si no hay Request (ej. tests), ejecutar sin caché
            return func(*args, **kwargs)
        return wrapper
    return decorator