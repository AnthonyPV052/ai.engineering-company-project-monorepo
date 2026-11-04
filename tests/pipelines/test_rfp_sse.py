"""Tests para el endpoint SSE de tickets de RFP (Parte 1 — Tiempo Real).

Verifica sobre el WIRE SSE REAL (no dicts abstractos):
- Framing: ``event: rfp_ticket_created`` + ``data: <JSON>`` + ``id: <ticket_id>``,
  y el evento de control ``connected`` al abrir el stream.
- Payload: ``data:`` es JSON con los campos EXACTOS del sistema de RFPs
  (``ticket_id``, ``status``, ``created_at`` obligatorios; ``client_name``,
  ``location``, ``service_type``, ``scope``, ``deadline``, ``budget_range``,
  ``departments_needed`` opcionales). Sin nombres inventados.
- Headers de la respuesta HTTP: ``Content-Type: text/event-stream``.
- El stream emite ``connected`` y luego los eventos publicados en vivo.
- Recuperación: ``Last-Event-ID`` → el servidor re-emite eventos perdidos.
- ``keep-alive``: comentario ``: keep-alive`` emitido ante inactividad.
- Autenticación: 401 sin JWT (mismo guard del BackOffice).

Estrategia (sin pytest-asyncio):
- Framing / payload: tests síncronos puros de format_sse_event / parse_sse_frames.
- Comportamiento del generador (connected, live, replay, keep-alive): se ejecuta
  ``_sse_stream`` real (AsyncGenerator) con ``anyio.run()`` en el mismo event
  loop. El pub/sub y ring buffer son los mismos del proceso productivo.
- Headers HTTP: servidor uvicorn en un hilo + httpx streaming (faithful al wire).
- 401: TestClient contra la app (sin override de auth).

Verificación manual de reconexión + recuperación (usuaria):
    Ver docs/sse-notifications.es.md § "Procedimiento de verificación manual".
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///test_rfp_sse.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-sse-tests")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")

import anyio
import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request

from database import get_db
from rfp_models import RFPMetadata, RFPTicket, TICKET_STATUS_ANALIZANDO
from security import get_current_user
from sse_notifications import (
    SSE_EVENT_CONNECTED,
    SSE_EVENT_RFP_TICKET_CREATED,
    build_rfp_ticket_payload,
    format_sse_event,
    parse_sse_frames,
    publish_rfp_ticket_created,
    _lock,
    _recent_events,
    _subscribers,
    _sse_stream,
)
import sse_notifications as _sse_mod

MOCK_USER = {"id": "test-user-001", "email": "test@brasaland.io", "is_active": True, "role": "admin"}


# ===================================================================
# Helpers
# ===================================================================


def _make_request(path: str = "/api/rfp/events/stream") -> Request:
    """Crea una Request ASGI que nunca indica desconexión."""
    async def _never_receive() -> dict[str, Any]:
        await anyio.sleep_forever()

    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
        "receive": _never_receive,
    }
    return Request(scope)


class _StoppableServer(uvicorn.Server):
    """Server uvicorn ejecutable en un hilo (sin signal handlers)."""
    def install_signal_handlers(self) -> None:
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite:///test_rfp_sse.db", echo=False)
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean_globals():
    """Limpia hub pub/sub y ring buffer antes de cada test."""
    _lock.acquire()
    try:
        _subscribers.clear()
        _recent_events.clear()
    finally:
        _lock.release()
    yield


# ===================================================================
# 1) Framing SSE (wire real)
# ===================================================================


class TestSseFraming:
    """Prueba que el wire SSE tenga la forma exacta que espera el frontend."""

    def test_format_event_wire_shape(self) -> None:
        """El wire usa event: rfp_ticket_created + data: JSON + id: + delimitador."""
        payload = {"ticket_id": "t-abc", "status": "analizando", "created_at": "2026-01-01T00:00:00Z"}
        raw = format_sse_event(SSE_EVENT_RFP_TICKET_CREATED, payload, event_id="t-abc")
        text = raw.decode("utf-8")

        assert "event: rfp_ticket_created" in text
        assert 'data: {"ticket_id":"t-abc","status":"analizando","created_at":"2026-01-01T00:00:00Z"}' in text
        assert "id: t-abc" in text
        # Termina con el delimitador de frame (doble newline)
        assert text.endswith("\n\n")

    def test_parse_roundtrip_all_fields(self) -> None:
        """Roundtrip con todos los campos del payload del dominio."""
        payload = {
            "ticket_id": "t-full",
            "status": "analizando",
            "created_at": "2026-06-15T12:00:00Z",
            "client_name": "Sunset Bay Resorts",
            "location": "Miami Beach, FL",
            "service_type": "Concesión de restaurante",
            "scope": "3 resorts",
            "deadline": "2026-07-01T00:00:00Z",
            "budget_range": "60000-75000 USD",
            "departments_needed": ["marketing", "operations"],
        }
        raw = format_sse_event(SSE_EVENT_RFP_TICKET_CREATED, payload, event_id="t-full")
        frames = parse_sse_frames(raw.decode("utf-8"))

        assert len(frames) == 1
        f = frames[0]
        assert f["event"] == "rfp_ticket_created"
        assert f["id"] == "t-full"
        data = json.loads(f["data"])
        assert data["ticket_id"] == "t-full"
        assert data["status"] == "analizando"
        assert data["client_name"] == "Sunset Bay Resorts"
        assert data["departments_needed"] == ["marketing", "operations"]

    def test_connected_event_wire(self) -> None:
        """El evento de control 'connected' llega como frame SSE."""
        raw = format_sse_event(SSE_EVENT_CONNECTED, {"status": "connected", "replay_count": 0})
        frames = parse_sse_frames(raw.decode("utf-8"))
        assert len(frames) == 1
        assert frames[0]["event"] == "connected"
        assert json.loads(frames[0]["data"])["status"] == "connected"

    def test_keepalive_comment_ignored(self) -> None:
        """El parser descarta líneas de comentario (': ...')."""
        frames = parse_sse_frames(": keep-alive\n\n")
        assert len(frames) == 0


# ===================================================================
# 2) Payload (nombres de campo del dominio RFP)
# ===================================================================


class TestBuildPayload:
    """Verifica que build_rfp_ticket_payload use los nombres EXACTOS del sistema."""

    def test_required_fields_present(self) -> None:
        """ticket_id, status, created_at siempre en el payload."""
        ticket = RFPTicket(ticket_id="req-1", status=TICKET_STATUS_ANALIZANDO)
        payload = build_rfp_ticket_payload(ticket, None)
        assert payload["ticket_id"] == "req-1"
        assert payload["status"] == "analizando"
        assert payload["created_at"]

    def test_optional_fields_omitted_when_none(self) -> None:
        """Con metadata None, los opcionales no aparecen (ni nulls).

        Excepción por diseño del dominio: ``departments_needed`` SIEMPRE está
        presente (como lista) porque el frontend lo espera para renderizar
        etiquetas de departamento; cuando todavía no se extrajo, llega ``[]``.
        """
        ticket = RFPTicket(ticket_id="opt-none", status=TICKET_STATUS_ANALIZANDO)
        payload = build_rfp_ticket_payload(ticket, None)
        for field in ("client_name", "location", "service_type", "scope",
                      "deadline", "budget_range"):
            assert field not in payload
        assert payload["departments_needed"] == []

    def test_optional_fields_included_when_present(self) -> None:
        """Con metadata poblada, se incluyen con nombre EXACTO."""
        ticket = RFPTicket(ticket_id="opt-full", status=TICKET_STATUS_ANALIZANDO)
        meta = RFPMetadata(
            ticket_id="opt-full",
            client_name="Cliente Test",
            location="Bogotá",
            service_type="Catering",
            scope="220 empleados",
            deadline="2026-01-15T00:00:00Z",
            budget_range="18-22M COP",
            departments_needed='["marketing","operations"]',
        )
        payload = build_rfp_ticket_payload(ticket, meta)
        assert payload["client_name"] == "Cliente Test"
        assert payload["location"] == "Bogotá"
        assert payload["scope"] == "220 empleados"
        assert payload["departments_needed"] == ["marketing", "operations"]


# ===================================================================
# 3) Comportamiento del stream (generador real, mismo event loop)
# ===================================================================


class TestStreamBehavior:
    """Ejecuta ``_sse_stream`` real (AsyncGenerator) con anyio.run()."""

    def test_connected_then_live_event(self, engine) -> None:
        """Tras connected, un evento publicado en vivo llega al stream."""
        with Session(engine) as session:
            collected: list[bytes] = []

            async def run() -> None:
                nonlocal collected
                gen = _sse_stream(_make_request(), session, None)
                # Primer frame: connected (igual que en el wire real)
                collected.append(await gen.__anext__())

                # Un drain sigue avanzando el generador; solo al pasar por el
                # segundo __anext__ el generador llega al paso de suscripción
                # (_subscribers.add).
                async def drain() -> None:
                    try:
                        while True:
                            collected.append(await gen.__anext__())
                    except BaseException:
                        pass

                async with anyio.create_task_group() as tg:
                    tg.start_soon(drain)

                    # Esperar suscripción activa
                    for _ in range(500):
                        _lock.acquire()
                        try:
                            if len(_subscribers) >= 1:
                                break
                        finally:
                            _lock.release()
                        await anyio.sleep(0.01)

                    assert len(_subscribers) >= 1, "Stream debe estar suscrito"

                    # Publicar y dejar que el drain capture el frame en vivo
                    publish_rfp_ticket_created(
                        {"ticket_id": "live-1", "status": "analizando",
                         "created_at": "2026-01-01T00:00:00Z"}
                    )
                    await anyio.sleep(0.1)
                    tg.cancel_scope.cancel()
                await gen.aclose()

            anyio.run(run)

        text = b"".join(collected).decode("utf-8")
        parsed = parse_sse_frames(text)
        assert parsed[0]["event"] == "connected"

        ticket_frames = [f for f in parsed if f["event"] == "rfp_ticket_created"]
        assert len(ticket_frames) == 1
        data = json.loads(ticket_frames[0]["data"])
        assert data["ticket_id"] == "live-1"
        assert data["status"] == "analizando"

    def test_replay_with_last_event_id(self, engine) -> None:
        """Last-Event-ID recupera eventos del ring buffer."""
        publish_rfp_ticket_created({"ticket_id": "h1", "status": "analizando", "created_at": "t"})
        publish_rfp_ticket_created({"ticket_id": "h2", "status": "analizando", "created_at": "t"})
        publish_rfp_ticket_created({"ticket_id": "h3", "status": "analizando", "created_at": "t"})

        with Session(engine) as session:
            collected: list[bytes] = []

            async def run() -> None:
                nonlocal collected
                gen = _sse_stream(_make_request(), session, "h1")
                collected.append(await gen.__anext__())  # connected
                collected.append(await gen.__anext__())  # h2
                collected.append(await gen.__anext__())  # h3
                await gen.aclose()

            anyio.run(run)

        text = b"".join(collected).decode("utf-8")
        parsed = parse_sse_frames(text)
        ticket_ids = [
            json.loads(f["data"])["ticket_id"]
            for f in parsed if f["event"] == "rfp_ticket_created"
        ]
        assert ticket_ids == ["h2", "h3"]

    def test_replay_count_in_connected(self, engine) -> None:
        """connected.replay_count refleja cuántos eventos se re-emiten."""
        publish_rfp_ticket_created({"ticket_id": "r1", "status": "analizando", "created_at": "t"})
        publish_rfp_ticket_created({"ticket_id": "r2", "status": "analizando", "created_at": "t"})

        with Session(engine) as session:
            collected: list[bytes] = []

            async def run() -> None:
                nonlocal collected
                gen = _sse_stream(_make_request(), session, "r1")
                collected.append(await gen.__anext__())  # connected
                await gen.aclose()

            anyio.run(run)

        parsed = parse_sse_frames(collected[0].decode("utf-8"))
        data = json.loads(parsed[0]["data"])
        assert data["status"] == "connected"
        assert data["replay_count"] == 1  # solo r2 (después de r1)

    def test_keepalive_comment_emitted_on_idle(self, engine, monkeypatch) -> None:
        """Con SSE_KEEP_ALIVE_INTERVAL_S bajo, se emite ': keep-alive'."""
        monkeypatch.setattr(_sse_mod, "SSE_KEEP_ALIVE_INTERVAL_S", 0.05)

        with Session(engine) as session:
            collected: list[bytes] = []

            async def run() -> None:
                nonlocal collected
                gen = _sse_stream(_make_request(), session, None)
                collected.append(await gen.__anext__())  # connected
                with anyio.move_on_after(3):
                    collected.append(await gen.__anext__())  # keep-alive
                await gen.aclose()

            anyio.run(run)

        text = b"".join(collected).decode("utf-8")
        assert ": keep-alive" in text


# ===================================================================
# 4) HTTP real (uvicorn + httpx streaming)
# ===================================================================


@pytest.fixture
def http_app(engine) -> FastAPI:
    """App FastAPI con overrides de auth/BD (mismo router)."""
    from routes.rfp import router as rfp_router

    app = FastAPI()
    app.include_router(rfp_router)
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER

    def _get_test_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = _get_test_db
    return app


class TestHttpEndpoint:
    """Pruebas sobre HTTP real (headers, auth)."""

    def test_response_headers(self, http_app: FastAPI) -> None:
        """GET /api/rfp/events/stream → Content-Type: text/event-stream."""
        port = _free_port()
        config = uvicorn.Config(http_app, host="127.0.0.1", port=port,
                                log_level="error", lifespan="off")
        server = _StoppableServer(config)
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(0.02)

            async def run() -> None:
                async with httpx.AsyncClient(timeout=10) as client:
                    async with client.stream(
                        "GET", f"http://127.0.0.1:{port}/api/rfp/events/stream",
                        headers={"Authorization": "Bearer test-token"},
                    ) as resp:
                        assert resp.status_code == 200
                        ct = resp.headers.get("content-type", "")
                        assert "text/event-stream" in ct
                        assert resp.headers.get("cache-control") == "no-cache"
                        it = resp.aiter_bytes()
                        first = await it.__anext__()
                        assert "event: connected" in first.decode()
                        await resp.aclose()

            anyio.run(run)
        finally:
            server.should_exit = True
            t.join(timeout=3)

    def test_unauthorized_without_token(self, engine) -> None:
        """Sin JWT → 401 (sin override de auth)."""
        from routes.rfp import router as rfp_router

        app = FastAPI()
        app.include_router(rfp_router)

        def _get_test_db():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_db] = _get_test_db

        with TestClient(app) as client:
            resp = client.get("/api/rfp/events/stream")
            assert resp.status_code == 401