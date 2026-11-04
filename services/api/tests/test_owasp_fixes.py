"""
Verificación de correcciones de seguridad OWASP Top 10:2025.

Uso:
    pytest tests/test_owasp_fixes.py -v

Requiere que el servidor esté corriendo en http://localhost:8020
"""

from __future__ import annotations

import os
import pytest
import requests
from datetime import datetime, timezone

API_BASE = os.getenv("TEST_API_URL", "http://localhost:8020")

# =============================================================================
# Helper
# =============================================================================


def _auth_token(email: str = "test@brasaland.com", password: str = "test1234") -> str:
    """Obtiene un token JWT válido para las pruebas autenticadas."""
    resp = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# =============================================================================
# A01: Broken Access Control — Verificación de autenticación
# =============================================================================

class TestA01BrokenAccessControl:

    def test_knowledge_query_requires_auth(self):
        """ANTES: /knowledge/query era público. DESPUÉS: debe rechazar sin token."""
        resp = requests.post(
            f"{API_BASE}/knowledge/query",
            json={"question": "¿Cuál es el horario de Medellín?"},
        )
        assert resp.status_code == 401, (
            f"Se esperaba 401, got {resp.status_code}. "
            "Si obtuviste 200, la corrección de autenticación no funciona."
        )
        print("✅ A01.1: /knowledge/query requiere autenticación")

    def test_knowledge_query_works_with_auth(self):
        """Con token válido, /knowledge/query debe funcionar."""
        token = _auth_token()
        resp = requests.post(
            f"{API_BASE}/knowledge/query",
            json={"question": "¿Cuál es el horario de Medellín?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (200, 502), (
            f"Se esperaba 200 o 502 (si no hay LLM), got {resp.status_code}"
        )
        print("✅ A01.2: /knowledge/query funciona con autenticación")

    def test_incidents_requires_auth(self):
        """ANTES: /api/incidents era público. DESPUÉS: debe rechazar sin token."""
        resp = requests.get(f"{API_BASE}/api/incidents")
        assert resp.status_code == 401, (
            f"Se esperaba 401, got {resp.status_code}"
        )
        print("✅ A01.3: /api/incidents requiere autenticación")

    def test_incidents_create_requires_auth(self):
        """Crear incidencia sin token debe ser rechazado."""
        resp = requests.post(
            f"{API_BASE}/api/incidents",
            json={
                "title": "Test",
                "description": "Test",
                "status": "open",
                "category": "food_safety",
                "origin": "store",
                "branch": "Medellín",
            },
        )
        assert resp.status_code == 401, (
            f"Se esperaba 401, got {resp.status_code}"
        )
        print("✅ A01.4: POST /api/incidents requiere autenticación")

    def test_tasks_requires_auth(self):
        """ANTES: /tasks/{id} era público. DESPUÉS: debe rechazar sin token."""
        resp = requests.get(f"{API_BASE}/tasks/fake-task-id")
        assert resp.status_code == 401, (
            f"Se esperaba 401, got {resp.status_code}"
        )
        print("✅ A01.5: /tasks/{task_id} requiere autenticación")


# =============================================================================
# A02: Security Misconfiguration
# =============================================================================

class TestA02SecurityMisconfiguration:

    def test_security_headers_present(self):
        """Verifica que los headers de seguridad OWASP están presentes."""
        resp = requests.get(f"{API_BASE}/health")
        headers = resp.headers

        assert "Strict-Transport-Security" in headers, "Falta HSTS"
        assert "X-Content-Type-Options" in headers, "Falta X-Content-Type-Options"
        assert "X-Frame-Options" in headers, "Falta X-Frame-Options"
        assert "Content-Security-Policy" in headers, "Falta CSP"
        assert "Referrer-Policy" in headers, "Falta Referrer-Policy"
        assert "Permissions-Policy" in headers, "Falta Permissions-Policy"

        assert headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        print("✅ A02.1: Headers de seguridad HTTP presentes y correctos")

    def test_cors_methods_restricted(self):
        """Verifica que CORS no permita métodos arbitrarios."""
        resp = requests.options(
            f"{API_BASE}/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_methods = resp.headers.get("Access-Control-Allow-Methods", "")
        # No debería permitir métodos peligrosos como TRACE
        assert "TRACE" not in allow_methods, "CORS permite TRACE"
        print("✅ A02.2: CORS methods restringidos (sin TRACE)")


# =============================================================================
# A05: Injection — Validación de entrada
# =============================================================================

class TestA05Injection:

    def test_knowledge_query_max_length(self):
        """Verifica que question tenga un límite de longitud máximo."""
        token = _auth_token()
        long_question = "A" * 2500
        resp = requests.post(
            f"{API_BASE}/knowledge/query",
            json={"question": long_question},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, (
            f"Se esperaba 422 por exceder max_length, got {resp.status_code}"
        )
        print("✅ A05.1: question con max_length validado")


# =============================================================================
# A07: Authentication Failures
# =============================================================================

class TestA07Authentication:

    def test_invalid_login_returns_401(self):
        """Login inválido debe devolver 401."""
        resp = requests.post(
            f"{API_BASE}/auth/login",
            json={"email": "nonexistent@test.com", "password": "wrong"},
        )
        assert resp.status_code == 401
        print("✅ A07.1: Login inválido devuelve 401")


# =============================================================================
# Docker: Verificación de hardening
# =============================================================================

class TestDockerHardening:
    """Pruebas que requieren acceso a Docker (saltar si no hay Docker)."""

    def test_non_root_user(self):
        """Verifica que el contenedor no corre como root."""
        import subprocess
        result = subprocess.run(
            ["docker", "exec", "brasaland-backend", "whoami"],
            capture_output=True, text=True, timeout=10,
        )
        user = result.stdout.strip()
        assert user != "root", (
            f"El contenedor corre como root. "
            "La corrección del Dockerfile para crear usuario no-root no se aplicó."
        )
        assert user == "brasaland", f"Se esperaba 'brasaland', got '{user}'"
        print(f"✅ Docker: Contenedor corre como '{user}' (no root)")

    def test_directory_permissions(self):
        """Verifica permisos de directorios en el contenedor."""
        import subprocess
        result = subprocess.run(
            ["docker", "exec", "brasaland-backend", "stat", "-c", "%a", "/app/data"],
            capture_output=True, text=True, timeout=10,
        )
        perms = result.stdout.strip()
        # 750 = rwxr-x---
        assert perms in ("750",), (
            f"Se esperaba permiso 750 en /app/data, got {perms}"
        )
        print(f"✅ Docker: /app/data tiene permisos {perms}")
