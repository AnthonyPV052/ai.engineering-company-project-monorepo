"""Notificaciones en tiempo real (SSE) para tickets de RFP — Parte 1.

Este módulo implementa el stream Server-Sent Events que avisa al equipo de
Marketing and Digital Experience (Camila Ospina) cuando entra un ticket de RFP
nuevo al sistema.

Reglas de dominio (ver ``BRIEFING.es.md`` — "Sistemas en Tiempo Real, Parte 1"):

- El evento se emite en el momento exacto en que un ticket nuevo entra al
  sistema con ``status = "analizando"`` (el estado inicial con el que se crea
  el ticket en ``routes/rfp.py -> upload_rfp``).
- Los nombres de los campos del payload reutilizan EXACTAMENTE las entidades
  del sistema de RFPs ya existente (``RFPTicket`` / ``RFPMetadata`` en
  ``rfp_models.py``). No se inventan nombres nuevos:
  * del ticket: ``ticket_id``, ``status``, ``created_at``
  * de la metadata RFP: ``client_name``, ``location``, ``service_type``,
    ``scope``, ``deadline``, ``budget_range``, ``departments_needed``
- Formato SSE: línea ``event: rfp_ticket_created`` + cuerpo JSON en ``data:``
  (payload directo, sin sobre anidado ``{"event","data"}``). Cada evento lleva
  además ``id: <ticket_id>`` para soportar ``Last-Event-ID``.
- El frontend consume el stream con fetch + ReadableStream para poder mandar el
  JWT en ``Authorization: Bearer ...`` (EventSource no permite headers de auth
  personalizados de forma limpia).

Recuperación tras caída (replay corto + refetch + dedup):

- El servidor mantiene un ring buffer (``SSE_REPLAY_BUFFER_SIZE``) de los
  últimos eventos ``rfp_ticket_created`` publicados en este proceso.
- El endpoint acepta el header estándar SSE ``Last-Event-ID`` (o el query param
  ``last_event_id``) con el ``ticket_id`` del último evento procesado por el
  cliente. Al reconectar el servidor re-emite, tras un evento ``connected``, los
  eventos publicados después de ese ``ticket_id``. Si el ticket indicado ya
  salió del buffer (reinicio del proceso/desbordamiento), se relee ese ticket de
  la BD y además se re-emiten los eventos recientes del buffer.
- El frontend (``sseRfpClient.ts``) además hace un refetch de la lista de
  tickets al reconectar y deduplica por ``ticket_id``, de modo que ningún ticket
  registrado durante la desconexión se pierde ni se pinta dos veces en la UI.

Mecánica de publicación (pub/sub en memoria por proceso):

- ``publish_rfp_ticket_created(payload)`` se llama desde el endpoint de upload
  (mismo proceso uvicorn — worker único en Compose) y despacha el payload a
  todas las colas ``asyncio.Queue`` suscritas + lo guarda en el ring buffer.
- Si no hay ningún suscriptor conectado, el evento no se entrega en vivo; los
  clientes se recuperan al reconectar vía Last-Event-ID/refetch (comportamiento
  aceptable por diseño, documentado en ``docs/sse-notifications.es.md``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, AsyncGenerator, Optional

from fastapi import Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from database import get_db
from rfp_models import RFPMetadata, RFPTicket
from security import get_current_user

logger = logging.getLogger("api.sse")

# ---------------------------------------------------------------------------
# Contrato público del evento (BRIEFING.es.md §3)
# ---------------------------------------------------------------------------

# Nombre de evento SSE exigido por el BRIEFING.
SSE_EVENT_RFP_TICKET_CREATED = "rfp_ticket_created"

# Evento de control emitido al abrir el stream (no es un ticket; no usa
# nombres de campos del dominio RFP).
SSE_EVENT_CONNECTED = "connected"

# Intervalo de comentario keep-alive: si la cola lleva inactiva este tiempo,
# el server emite ": comentario" para que proxies/load balancers no cierren la
# conexión. No dispara ningún evento en el cliente.
SSE_KEEP_ALIVE_INTERVAL_S = 15.0

# Máximo de eventos recientes retenidos para replay tras una caída.
SSE_REPLAY_BUFFER_SIZE = 100

# Campos mínimos que el evento DEBE contener (los exige el dashboard).
PAYLOAD_REQUIRED_FIELDS = (
    "ticket_id",
    "status",
    "created_at",
)
# Campos de metadata RFP opcionales (se omiten si aún no fueron extraídos).
PAYLOAD_OPTIONAL_FIELDS = (
    "client_name",
    "location",
    "service_type",
    "scope",
    "deadline",
    "budget_range",
    "departments_needed",
)

# ---------------------------------------------------------------------------
# Hub pub/sub en memoria (por proceso) + ring buffer para replay
# ---------------------------------------------------------------------------

_lock = Lock()
_subscribers: set["asyncio.Queue[dict[str, Any]]"] = set()
# Ring buffer de eventos ya publicados (orden de publicación).
_recent_events: "deque[dict[str, Any]]" = deque(maxlen=SSE_REPLAY_BUFFER_SIZE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Framing SSE (código compartido por el servidor y las pruebas)
# ---------------------------------------------------------------------------


def format_sse_event(event: str, payload: dict[str, Any], event_id: str | None = None) -> bytes:
    """Serializa un evento SSE en el wire.

    ``event:`` con nombre explícito, ``data:`` con JSON directo del payload y,
    opcionalmente, ``id:`` para soportar ``Last-Event-ID`` (recuperación).
    Termina con la línea en blanco que delimita el frame.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {body}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def parse_sse_frames(raw: str) -> list[dict[str, Any]]:
    """Parseador SSE mínimo usado en las pruebas sobre el wire real.

    Devuelve una lista de frames con las claves ``event``, ``id`` y ``data``
    cuando aplica. Las líneas ``data:`` multilínea se unen con ``\\n`` según la
    especificación SSE; los comentarios (``:``) se descartan.
    """
    frames: list[dict[str, Any]] = []
    current_event: str | None = None
    current_id: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_event, current_id, data_lines
        if data_lines or current_event is not None:
            frames.append(
                {
                    "event": current_event,
                    "id": current_id,
                    "data": "\n".join(data_lines),
                }
            )
        data_lines = []
        current_id = None
        current_event = None

    for line in raw.splitlines():
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue  # comentario keep-alive
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("id:"):
            current_id = line[len("id:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())

    # Frame sin delimitador final (EOF): se cierra si quedaron líneas.
    if data_lines or current_event is not None:
        flush()

    return frames


# ---------------------------------------------------------------------------
# Construcción del payload (misma nomenclatura que el sistema de RFPs)
# ---------------------------------------------------------------------------


def build_rfp_ticket_payload(ticket: RFPTicket, metadata: RFPMetadata | None) -> dict[str, Any]:
    """Construye el payload del evento a partir del ticket y su metadata.

    Reutiliza los nombres exactos de ``rfp_models.py``. El documento completo y
    las secciones por departamento NO se incluyen (solo lo suficiente para que
    quien mira el dashboard sepa qué llegó). Los campos metadata aún no
    extraídos (None) se omiten del payload en lugar de enviar nulls.
    """
    departments_needed: list[str] = []
    if metadata and metadata.departments_needed:
        try:
            parsed = json.loads(metadata.departments_needed)
            if isinstance(parsed, list):
                departments_needed = [str(d) for d in parsed]
        except (json.JSONDecodeError, TypeError):
            departments_needed = []

    payload: dict[str, Any] = {
        "ticket_id": ticket.ticket_id,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else _now_iso(),
        "client_name": metadata.client_name if metadata else None,
        "location": metadata.location if metadata else None,
        "service_type": metadata.service_type if metadata else None,
        "scope": metadata.scope if metadata else None,
        "deadline": metadata.deadline if metadata else None,
        "budget_range": metadata.budget_range if metadata else None,
        "departments_needed": departments_needed,
    }
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Publicador (lo invoca routes/rfp.py al crear un ticket)
# ---------------------------------------------------------------------------


def publish_rfp_ticket_created(payload: dict[str, Any]) -> None:
    """Publica ``rfp_ticket_created`` a todos los streams suscritos.

    Guarda el evento en el ring buffer (para replay) y lo despacha a las colas
    de los suscriptores conectados. No bloquea: si no hay suscriptores, el
    evento se pierde en vivo (los clientes se recuperan con Last-Event-ID o con
    el refetch al reconectar).
    """
    ticket_id = payload.get("ticket_id")
    try:
        frame = format_sse_event(SSE_EVENT_RFP_TICKET_CREATED, payload, event_id=ticket_id)
    except (TypeError, ValueError):
        logger.exception("Cannot serialize RFP ticket payload for SSE")
        return

    _lock.acquire()
    try:
        _recent_events.append({"ticket_id": ticket_id, "frame": frame})
        targets = list(_subscribers)
    finally:
        _lock.release()

    logger.info("Publishing %s (ticket=%s) to %d subscriber(s)",
                SSE_EVENT_RFP_TICKET_CREATED, ticket_id, len(targets))
    for queue in targets:
        try:
            queue.put_nowait({"frame": frame})
        except asyncio.QueueFull:
            logger.warning("SSE subscriber queue full; dropping event for %s", ticket_id)


# ---------------------------------------------------------------------------
# Replay corto (Last-Event-ID)
# ---------------------------------------------------------------------------


def _replay_frames(last_event_id: str, db: Session) -> list[bytes]:
    """Determina qué frames re-emitir tras una reconexión.

    - Si ``last_event_id`` (un ``ticket_id``) está en el ring buffer, se
      re-emiten los eventos publicados DESPUÉS de él.
    - Si ya salió del buffer (reinicio/desbordamiento) pero el ticket sigue en
      la BD, se re-emite ese ticket (reconstruido) + los eventos recientes.
    - Si no está en ningún lado, se re-emiten los eventos recientes (el
      frontend deduplica por ``ticket_id``).
    """
    _lock.acquire()
    try:
        ordered = list(_recent_events)
    finally:
        _lock.release()

    found_at: int | None = None
    for i, entry in enumerate(ordered):
        if entry["ticket_id"] == last_event_id:
            found_at = i
            break

    if found_at is not None:
        return [entry["frame"] for entry in ordered[found_at + 1:]]

    # El ticket indicado ya no está en el buffer.
    frames: list[bytes] = []
    ticket = db.get(RFPTicket, last_event_id)
    if ticket is not None:
        metadata = db.exec(
            select(RFPMetadata).where(RFPMetadata.ticket_id == ticket.ticket_id)
        ).first()
        frames.append(
            format_sse_event(
                SSE_EVENT_RFP_TICKET_CREATED,
                build_rfp_ticket_payload(ticket, metadata),
                event_id=ticket.ticket_id,
            )
        )

    frames.extend(entry["frame"] for entry in ordered)
    return frames


# ---------------------------------------------------------------------------
# Stream SSE
# ---------------------------------------------------------------------------


async def _sse_stream(
    request: Request,
    db: Session,
    last_event_id: str | None,
) -> AsyncGenerator[bytes, None]:
    """Generador de frames SSE ejecutado dentro de StreamingResponse."""
    # 1) Evento de control "connected": el stream quedó establecido. Deja claro
    #    cuántos eventos se re-emiten en el replay y permite al cliente limpiar
    #    el estado de backoff.
    replay = _replay_frames(last_event_id, db) if last_event_id else []
    connected_payload = {
        "status": "connected",
        "replay_count": len(replay),
        "last_event_id": last_event_id,
    }
    yield format_sse_event(SSE_EVENT_CONNECTED, connected_payload)

    # 2) Replay corto de los eventos perdidos durante la desconexión.
    for frame in replay:
        yield frame

    # 3) Suscripción en vivo.
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
    _lock.acquire()
    try:
        _subscribers.add(queue)
    finally:
        _lock.release()

    try:
        while True:
            # keep-alive: comenta el stream cada N segundos si no hay eventos.
            try:
                item = await asyncio.wait_for(queue.get(), timeout=SSE_KEEP_ALIVE_INTERVAL_S)
            except asyncio.TimeoutError:
                yield b": keep-alive\n\n"
                continue
            yield item["frame"]
            if await request.is_disconnected():
                logger.debug("SSE client disconnected; closing stream")
                break
    finally:
        _lock.acquire()
        try:
            _subscribers.discard(queue)
        finally:
            _lock.release()


async def sse_rfp_tickets_stream(
    request: Request,
    last_event_id: Optional[str] = Query(default=None, alias="last_event_id"),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """GET /api/rfp/events/stream — Stream SSE de tickets de RFP nuevos.

    Protegido con el MISMO JWT que el resto del BackOffice
    (``Authorization: Bearer …``). Un cliente sin autenticación recibe 401.

    Headers de la conexión:
    - ``Content-Type: text/event-stream``
    - ``Cache-Control: no-cache``
    - ``Connection: keep-alive``
    - ``X-Accel-Buffering: no`` (proxies NGINX no bufferizan el stream)

    Recuperación:
    - Header estándar SSE ``Last-Event-ID`` (o query ``last_event_id``) con el
      ``ticket_id`` del último evento procesado. El servidor re-emite los
      eventos perdidos tras el evento ``connected``.
    """
    # El header estándar SSE tiene prioridad sobre el query param.
    header_last_event: str | None = request.headers.get("Last-Event-ID")
    if header_last_event:
        last_event_id = header_last_event

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    return StreamingResponse(
        _sse_stream(request, db, last_event_id),
        status_code=200,
        headers=headers,
        media_type="text/event-stream",
    )