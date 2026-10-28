"""Persistencia y máquina de estados para jobs fuera de FastAPI.

El estado ``processing`` es el único lock del job. Las transiciones se hacen
con SQL condicional para que dos procesos concurrentes no puedan adquirirlo.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger("services.job_runner")

JOB_NAME = "nightly_export"
_ALLOWED = {"pending", "processing", "completed", "failed"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _log(status: str, message: str, **fields: object) -> None:
    logger.info(
        "%s job_name=%s status=%s %s",
        message,
        fields.pop("job_name", JOB_NAME),
        status,
        " ".join(f"{key}={value}" for key, value in fields.items()),
    )


def get_engine() -> Engine:
    """Create an independent SQLAlchemy engine for the worker process."""
    import os

    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no está configurada")
    return create_engine(url, pool_pre_ping=True)


def has_processing_lock(conn: Connection, job_name: str = JOB_NAME) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM job_runs WHERE job_name = :job_name AND status = 'processing' LIMIT 1
    """), {"job_name": job_name}).first())


def has_completed_for_date(conn: Connection, target_date: date, job_name: str = JOB_NAME) -> bool:
    return bool(conn.execute(text("""
        SELECT 1 FROM job_runs
        WHERE job_name = :job_name AND target_date = :target_date AND status = 'completed'
        LIMIT 1
    """), {"job_name": job_name, "target_date": target_date}).first())


def create_pending(conn: Connection, target_date: date, job_name: str = JOB_NAME) -> int:
    result = conn.execute(text("""
        INSERT INTO job_runs (job_name, target_date, status, created_at)
        VALUES (:job_name, :target_date, 'pending', :created_at)
        RETURNING id
    """), {"job_name": job_name, "target_date": target_date, "created_at": utc_now()})
    run_id = int(result.scalar_one())
    _log("pending", "job_run_created", job_name=job_name, run_id=run_id, target_date=target_date)
    return run_id


def mark_processing(conn: Connection, run_id: int) -> bool:
    """Atomically acquire the processing lock for a pending row."""
    result = conn.execute(text("""
        UPDATE job_runs
        SET status = 'processing', started_at = :now, error_message = NULL
        WHERE id = :run_id AND status = 'pending'
    """), {"run_id": run_id, "now": utc_now()})
    acquired = result.rowcount == 1
    if acquired:
        _log("processing", "job_lock_acquired", run_id=run_id)
    return acquired


def mark_completed(conn: Connection, run_id: int) -> None:
    _transition(conn, run_id, "completed", None)


def mark_failed(conn: Connection, run_id: int, error_message: str) -> None:
    _transition(conn, run_id, "failed", error_message[:4000])


def _transition(conn: Connection, run_id: int, status: str, error_message: str | None) -> None:
    if status not in _ALLOWED - {"pending", "processing"}:
        raise ValueError(f"Estado final inválido: {status}")
    result = conn.execute(text("""
        UPDATE job_runs
        SET status = :status, finished_at = :finished_at, error_message = :error_message
        WHERE id = :run_id AND status = 'processing'
    """), {"run_id": run_id, "status": status, "finished_at": utc_now(), "error_message": error_message})
    if result.rowcount != 1:
        raise RuntimeError(f"No se pudo pasar job_run {run_id} a {status}")
    _log(status, "job_run_transitioned", run_id=run_id)


@contextmanager
def job_run(engine: Engine, target_date: date, job_name: str = JOB_NAME) -> Iterator[int | None]:
    """Adquiere el lock y garantiza ``failed`` si el cuerpo lanza excepción.

    La adquisición se confirma antes de ejecutar trabajo externo; por eso una
    excepción del subprocess puede actualizar la misma fila en una transacción
    independiente y nunca deja ``processing`` huérfano.
    """
    try:
        with engine.begin() as conn:
            if has_processing_lock(conn, job_name) or has_completed_for_date(conn, target_date, job_name):
                _log("skipped", "job_run_skipped", job_name=job_name, target_date=target_date,
                     reason="processing_lock_or_completed")
                yield None
                return
            run_id = create_pending(conn, target_date, job_name)
            if not mark_processing(conn, run_id):
                yield None
                return
        try:
            yield run_id
        except Exception as exc:
            fail_run(engine, run_id, str(exc))
            raise
        else:
            try:
                with engine.begin() as conn:
                    mark_completed(conn, run_id)
            except Exception as exc:
                # A failure while committing the success state must also be
                # reflected in the row whenever the database is reachable.
                fail_run(engine, run_id, str(exc))
                raise
    except IntegrityError:
        # Another worker acquired processing between the check and INSERT.
        # The partial unique index makes this a normal, silent lock miss.
        logger.info("job_lock_not_acquired job_name=%s", job_name)
        yield None
    except Exception:
        raise


def fail_run(engine: Engine, run_id: int, error_message: str) -> None:
    with engine.begin() as conn:
        mark_failed(conn, run_id, error_message)
