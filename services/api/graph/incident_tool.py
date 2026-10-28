"""Read-only incident lookup used by the support agent."""
from __future__ import annotations

import json
import os
import re
import logging
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Literal
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from incident_models import IncidentResponse

INCIDENT_TOOL_TIMEOUT_SECONDS = 7.0
_INCIDENT_LIST_LIMIT = 5
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="incident-tool")
logger = logging.getLogger("api.agent.incidents")
_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_LABELED_ID = re.compile(
    r"(?i)\b(?:ticket|incidencia|incidente|caso)\s*(?:n(?:ro|úm)?\.?\s*)?#?([a-z0-9][a-z0-9_-]{2,})\b"
)

# -- Filtros extraíbles del lenguaje natural para listados de incidencias --

_INCIDENT_STATUS_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\babiert[ao]s?\b"), "open"),
    (re.compile(r"(?i)\bopen\b"), "open"),
    (re.compile(r"(?i)\ben\s*progreso\b"), "in_progress"),
    (re.compile(r"(?i)\bin.progress\b"), "in_progress"),
    (re.compile(r"(?i)\b(?:resuelt[ao]s?|cerrad[ao]s?)\b"), "resolved"),
    (re.compile(r"(?i)\bresolved\b"), "resolved"),
    (re.compile(r"(?i)\bdescartad[ao]s?\b"), "discarded"),
    (re.compile(r"(?i)\bdiscarded\b"), "discarded"),
]

_INCIDENT_CATEGORY_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\b(?:equip[oa]|equipment)\w*\b"), "equipment_failure"),
    (re.compile(r"(?i)\b(?:proveedor|suministro|supply)\w*\b"), "supply_issue"),
    (re.compile(r"(?i)\b(?:cliente|customer)\w*\b"), "customer_complaint"),
    (re.compile(r"(?i)\b(?:personal|staff)\w*\b"), "staff_issue"),
    (re.compile(r"(?i)\b(?:instalaci[oó]n|facility)\w*\b"), "facility_issue"),
    (re.compile(r"(?i)\b(?:pos|sistema|tpv|system)\b"), "pos_system"),
    (re.compile(r"(?i)\b(?:entrega|delivery)\w*\b"), "delivery_issue"),
]

_INCIDENT_ORIGIN_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\bcliente\b"), "customer"),
    (re.compile(r"(?i)\bcustomer\b"), "customer"),
    (re.compile(r"(?i)\bsucursal\b"), "branch"),
    (re.compile(r"(?i)\bintern[ao]\b"), "internal"),
    (re.compile(r"(?i)\binternal\b"), "internal"),
]

_INCIDENT_BRANCH_FILTERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\bmedell[ií]n\s*centro\b"), "medellin_centro"),
    (re.compile(r"(?i)\bmedell[ií]n\s*laureles\b"), "medellin_laureles"),
    (re.compile(r"(?i)\bmedell[ií]n\s*envigado\b"), "medellin_envigado"),
    (re.compile(r"(?i)\bmedell[ií]n\s*bello\b"), "medellin_bello"),
    (re.compile(r"(?i)\bmedell[ií]n\s*itag[uú]i\b"), "medellin_itagui"),
    (re.compile(r"(?i)\bbogot[áa]\s*chapinero\b"), "bogota_chapinero"),
    (re.compile(r"(?i)\bbogot[áa]\s*[uú]saqu[eé]n\b"), "bogota_usaquen"),
    (re.compile(r"(?i)\bcali\s*granada\b"), "cali_granada"),
    (re.compile(r"(?i)\bbarranquilla\s*norte\b"), "barranquilla_norte"),
    (re.compile(r"(?i)\bmiami\s*doral\b"), "miami_doral"),
    (re.compile(r"(?i)\bmiami\s*hialeah\b"), "miami_hialeah"),
    (re.compile(r"(?i)\bmiami\s*kendall\b"), "miami_kendall"),
    (re.compile(r"(?i)\borlando\b"), "orlando_international"),
    (re.compile(r"(?i)\bfort\s*lauderdale\b"), "fort_lauderdale"),
]


class IncidentToolInput(BaseModel):
    """Input contract for the read-only incident tool."""

    ticket_id: str | None = Field(
        default=None,
        min_length=1,
        description="ID exacto de la incidencia. Si se omite, no se ejecuta la consulta.",
    )


class IncidentToolOutput(BaseModel):
    """Output contract; ``incident`` mirrors GET /api/incidents/{id}."""

    ticket_id: str | None
    outcome: Literal["found", "not_found", "missing_id", "timeout", "service_error"]
    incident: IncidentResponse | None = None
    error: str | None = None


def extract_incident_id(question: str) -> str | None:
    """Find an explicit ticket identifier without guessing one from prose."""
    uuid_match = _UUID.search(question)
    if uuid_match:
        return uuid_match.group(0)
    labeled_match = _LABELED_ID.search(question)
    return labeled_match.group(1) if labeled_match else None


def _fetch_incident(incident_id: str) -> IncidentResponse | None:
    base_url = os.getenv("INCIDENTS_API_URL", "http://127.0.0.1:8020/api/incidents").rstrip("/")
    url = f"{base_url}/{quote(incident_id, safe='')}"
    headers = {"Accept": "application/json"}
    # Local in-process API routes do not require auth. For a separately hosted
    # incident service, configure a service-to-service token explicitly.
    token = os.getenv("INCIDENTS_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=INCIDENT_TOOL_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return IncidentResponse.model_validate_json(payload)


def lookup_incident(tool_input: IncidentToolInput) -> IncidentToolOutput:
    """GET one incident and return the typed result in at most seven seconds."""
    incident_id = tool_input.ticket_id
    if not incident_id:
        return IncidentToolOutput(ticket_id=None, outcome="missing_id", error="missing_id")

    future: Future[IncidentResponse | None] = _EXECUTOR.submit(_fetch_incident, incident_id)
    try:
        incident = future.result(timeout=INCIDENT_TOOL_TIMEOUT_SECONDS)
        if incident is None:
            logger.info("La tool de incidencias no encontró ticket_id=%s", incident_id)
            return IncidentToolOutput(ticket_id=incident_id, outcome="not_found")
        logger.info("La tool de incidencias encontró ticket_id=%s", incident_id)
        return IncidentToolOutput(ticket_id=incident_id, outcome="found", incident=incident)
    except FutureTimeout:
        # Do not wait for a stalled network call: this node and graph can finish now.
        future.cancel()
        logger.warning("Timeout de %.1fs al consultar ticket_id=%s", INCIDENT_TOOL_TIMEOUT_SECONDS, incident_id)
        return IncidentToolOutput(ticket_id=incident_id, outcome="timeout", error="timeout")
    except HTTPError:
        logger.exception("El servicio de incidencias rechazó la consulta")
        return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="service_error")
    except URLError as exc:
        if not isinstance(exc.reason, TimeoutError):
            logger.exception("Falló la consulta HTTP de la incidencia")
            return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="service_error")
        logger.warning("Timeout HTTP al consultar ticket_id=%s", incident_id)
        return IncidentToolOutput(ticket_id=incident_id, outcome="timeout", error="timeout")
    except TimeoutError:
        logger.warning("Timeout HTTP al consultar ticket_id=%s", incident_id)
        return IncidentToolOutput(ticket_id=incident_id, outcome="timeout", error="timeout")
    except (ValueError, ValidationError):
        logger.exception("Falló la consulta tipada de la incidencia")
        return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="service_error")
    except Exception:
        # Unexpected transport/serialization errors also produce the typed safe fallback.
        logger.exception("Error inesperado en la tool de incidencias")
        return IncidentToolOutput(ticket_id=incident_id, outcome="service_error", error="service_error")


def extract_incident_filters(question: str) -> dict[str, str]:
    """Extrae filtros (status, category, origin, branch) del lenguaje natural.

    Devuelve un dict con las claves que coinciden; puede estar vacío si la
    pregunta no menciona ningún filtro reconocible.
    """
    filters: dict[str, str] = {}

    for pattern, value in _INCIDENT_STATUS_FILTERS:
        if pattern.search(question):
            filters["status"] = value
            break
    for pattern, value in _INCIDENT_CATEGORY_FILTERS:
        if pattern.search(question):
            filters["category"] = value
            break
    for pattern, value in _INCIDENT_ORIGIN_FILTERS:
        if pattern.search(question):
            filters["origin"] = value
            break
    for pattern, value in _INCIDENT_BRANCH_FILTERS:
        if pattern.search(question):
            filters["branch"] = value
            break

    return filters


def list_incidents(
    filters: dict[str, str],
    *,
    limit: int = _INCIDENT_LIST_LIMIT,
) -> list[dict[str, object]]:
    """Llama a GET /api/incidents con los filtros dados y devuelve resultados.

    Devuelve como máximo ``limit`` resultados más uno extra para detectar
    truncamiento. La llamada HTTP se ejecuta en el executor compartido y
    respeta ``INCIDENT_TOOL_TIMEOUT_SECONDS``.
    """
    base_url = os.getenv("INCIDENTS_API_URL", "http://127.0.0.1:8020/api/incidents").rstrip("/")
    params = "&".join(f"{key}={quote(value, safe='')}" for key, value in sorted(filters.items()))
    url = f"{base_url}?{params}" if params else base_url
    headers = {"Accept": "application/json"}
    token = os.getenv("INCIDENTS_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=INCIDENT_TOOL_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        logger.exception("Falló el listado de incidencias")
        raise
    items = payload if isinstance(payload, list) else []
    # Pide uno más del límite para detectar si hay más resultados sin hacer
    # una segunda llamada.
    oversized = items[: limit + 1]
    return oversized


__all__ = [
    "IncidentToolInput",
    "IncidentToolOutput",
    "extract_incident_id",
    "extract_incident_filters",
    "lookup_incident",
    "list_incidents",
    "INCIDENT_TOOL_TIMEOUT_SECONDS",
]