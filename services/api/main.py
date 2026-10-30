from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from database import init_db
from routes.auth import router as auth_router
from routes.incidents import router as incidents_router
from routes.inventory import router as inventory_router
from routes.knowledge import router as knowledge_router
from routes.profiles import router as profiles_router
from routes.suppliers import router as suppliers_router
from routes.users import router as users_router
from routes.rfp import router as rfp_router
from telemetry.router import router as telemetry_router
from telemetry.report import router as report_router

# --- Reporting (pipeline de desempeño de negocio) ---
from reporting.router import router as reporting_router

# --- Agent Memory System ---
from memory.routes import router as memory_router

import time
import logging
from fastapi import Request

from telemetry_util import emit_api_perf_event, emit_api_error_event, emit_telemetry_event
from celery.result import AsyncResult
from celery_app import celery_app

logger = logging.getLogger("api.timing")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Inicializa la base de datos si Supabase está disponible al arrancar.

    Una caída temporal del servicio PostgreSQL externo no debe impedir que
    arranquen el API y las rutas que no dependen de SQL.
    """
    try:
        # Memory schema is provisioned by migration 003 (pgvector/partial index).
        # Do not let SQLModel create incompatible placeholder columns for it.
        import memory.models  # noqa: F401

        init_db(exclude_tables={"agent_memories", "memory_proposals", "memory_audit_log"})
    except OperationalError:
        logger.exception(
            "No se pudo conectar a DATABASE_URL durante el arranque; "
            "el API seguirá disponible y los endpoints SQL fallarán hasta "
            "que la base de datos vuelva a estar accesible."
        )
    yield


app = FastAPI(title="Brasaland Supplier Directory API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = (time.perf_counter() - start) * 1000  # ms

    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} | {duration:.1f}ms"
    )

    # Emitir evento de latencia de API para todas las rutas (excepto telemetry para evitar bucles)
    if not request.url.path.startswith("/telemetry"):
        emit_api_perf_event(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration, 1),
            country=getattr(request.state, "country", ""),
        )

    return response


# ---------------------------------------------------------------------------
# Middleware de seguridad: detecta intentos de modificar stock fuera de las
# órdenes de entrada/salida (PATCH, PUT, DELETE sobre /inventory/products)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def direct_stock_edit_guard(request: Request, call_next):
    """Rechaza cualquier PATCH/PUT/DELETE sobre /inventory/products/* y emite
    evento direct_stock_edit_rejected.

    El modelo de negocio de Brasaland exige que toda modificación de stock
    pase por InboundOrder (entrada) u OutboundOrder (salida).
    """
    path = request.url.path
    method = request.method

    # Detectar intentos de modificación directa sobre productos de inventario
    if method in ("PATCH", "PUT", "DELETE") and "/inventory/products" in path:
        emit_telemetry_event(
            "direct_stock_edit_rejected",
            properties={
                "location_id": 0,
                "country": "",
                "product_id": 0,
                "attempt_type": "api_direct_patch",
                "reason_rejected": "no_endpoint",
            },
        )

        return JSONResponse(
            status_code=405,
            content={
                "error": {
                    "message": (
                        "El stock no se modifica directamente. "
                        "Usa POST /inventory/orders/inbound o "
                        "POST /inventory/orders/outbound."
                    )
                }
            },
        )

    response = await call_next(request)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4011",
        "http://127.0.0.1:4011",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(suppliers_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(profiles_router)
app.include_router(incidents_router)
app.include_router(inventory_router)
app.include_router(knowledge_router)
app.include_router(rfp_router)
app.include_router(telemetry_router)
app.include_router(report_router)
app.include_router(reporting_router)
app.include_router(memory_router)


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict[str, object]:
    """Consulta el estado real de Celery y su resultado cuando termina."""
    result = AsyncResult(task_id, app=celery_app)
    state = result.status.lower()
    # Celery exposes RETRY, but the public contract intentionally has four
    # lifecycle states. A retry is still actively being processed.
    if state == "retry":
        state = "started"
    return {
        "task_id": task_id,
        "status": state,
        "result": result.result if state == "success" else (str(result.result) if state == "failure" else None),
    }


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    error = exc.errors()[0]
    location = error.get("loc", [])
    field = str(location[-1]) if location else "request"
    error_type = error.get("type", "")
    if error_type == "missing":
        message = "Este campo es obligatorio."
    elif "enum" in error_type:
        message = "Contiene un valor no permitido."
    else:
        message = str(error.get("msg", "El valor no es válido.")).replace("Value error, ", "")
    
    # Emitir evento de error de validación
    emit_api_error_event(
        method=request.method,
        path=request.url.path,
        status_code=400,
        error_type="validation_error",
        country=getattr(request.state, "country", ""),
    )
    
    return JSONResponse(status_code=400, content={"error": {"field": field, "message": message}})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Emitir evento de error no controlado
    emit_api_error_event(
        method=request.method,
        path=request.url.path,
        status_code=500,
        error_type="server_error",
        country=getattr(request.state, "country", ""),
    )
    return JSONResponse(status_code=500, content={"error": {"message": "Error interno del servidor."}})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
