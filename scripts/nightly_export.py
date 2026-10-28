"""Exportación nocturna independiente de FastAPI.

Uso manual: ``python scripts/nightly_export.py``
Cron recomendado (fuera del proceso web): ``15 2 * * * cd /repo && ...``
"""
from __future__ import annotations

import csv
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.job_runner import get_engine, job_run  # noqa: E402

logger = logging.getLogger("nightly_export")
JOB_NAME = "nightly_export"


def log_event(status: str, message: str, **fields: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("job_name=%s status=%s event=%s %s", JOB_NAME, status, message, details)


def resolve_target_date() -> date:
    raw = os.getenv("TARGET_DATE")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("TARGET_DATE debe usar formato YYYY-MM-DD") from exc
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def export_telemetry(engine: Any, target_date: date, destination: Path) -> bool:
    """Exporta una vez; devuelve False si el archivo ya existía."""
    if destination.exists():
        log_event("skipped", "telemetry_export", target_date=target_date, path=destination, reason="already_exists")
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    query = text("""
        SELECT id, event_type, timestamp, service, tags, user_id, session_id
        FROM telemetry_events
        WHERE timestamp >= :start_at AND timestamp < :end_at
        ORDER BY timestamp, id
    """)
    start_at = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_at = start_at + timedelta(days=1)
    with engine.connect() as conn:
        rows = conn.execute(query, {"start_at": start_at, "end_at": end_at})
        # Atomic replace prevents a killed worker from leaving a valid-looking CSV.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=destination.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
            writer = csv.writer(tmp)
            writer.writerow(["id", "event_type", "timestamp", "service", "tags", "user_id", "session_id"])
            for row in rows:
                writer.writerow([
                    row.id, row.event_type, row.timestamp.isoformat() if row.timestamp else "",
                    row.service, json.dumps(row.tags or {}, ensure_ascii=False, sort_keys=True),
                    row.user_id or "", row.session_id or "",
                ])
    try:
        # A hard link publishes the complete temporary file atomically and
        # fails without overwriting a file published by another process.
        os.link(temporary, destination)
    except FileExistsError:
        temporary.unlink(missing_ok=True)
        log_event("skipped", "telemetry_export", target_date=target_date, path=destination, reason="concurrent_file")
        return False
    temporary.unlink(missing_ok=True)
    log_event("completed", "telemetry_export", target_date=target_date, path=destination)
    return True


def pipeline_command(target_date: date) -> list[str]:
    configured = os.getenv("NIGHTLY_PIPELINE_COMMAND")
    if configured:
        import shlex
        return shlex.split(configured)
    # Existing repository pipeline is weekly; process the ISO week containing target_date.
    week_start = target_date - timedelta(days=target_date.weekday())
    return [sys.executable, "-m", "data.pipelines.pipeline", "--week-start", week_start.isoformat()]


def run_pipeline(target_date: date) -> None:
    command = pipeline_command(target_date)
    log_event("processing", "pipeline", target_date=target_date, command=command)
    completed = subprocess.run(command, cwd=ROOT, check=False, text=True, capture_output=True)
    if completed.stdout:
        log_event("processing", "pipeline_stdout", target_date=target_date, output=completed.stdout[-4000:])
    if completed.returncode:
        logger.error("job_name=%s status=failed event=pipeline target_date=%s returncode=%s stderr=%s", JOB_NAME, target_date, completed.returncode, completed.stderr[-4000:])
        raise RuntimeError(f"pipeline exit code {completed.returncode}: {completed.stderr[-1000:]}")
    log_event("completed", "pipeline", target_date=target_date)


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        target_date = resolve_target_date()
        destination = ROOT / "data" / "raw" / f"telemetry_{target_date.isoformat()}.csv"
        engine = get_engine()
    except Exception:
        logger.exception("job_name=%s status=failed event=initialization", JOB_NAME)
        return 1
    try:
        with job_run(engine, target_date) as run_id:
            if run_id is None:
                log_event("skipped", "nightly_export", target_date=target_date, reason="locked_or_completed")
                return 0
            export_telemetry(engine, target_date, destination)
            run_pipeline(target_date)
    except Exception:
        logger.exception("job_name=%s status=failed event=nightly_export target_date=%s", JOB_NAME, target_date)
        return 1
    log_event("completed", "nightly_export", target_date=target_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
