from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine
from tinydb import TinyDB

# ---------------------------------------------------------------------------
# TinyDB — base de datos local basada en archivos JSON (legado)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUPPLIERS_DB_FILE = DATA_DIR / "suppliers.json"
USERS_DB_FILE = DATA_DIR / "users.json"
PROFILES_DB_FILE = DATA_DIR / "profiles.json"
PASSWORD_RESET_TOKENS_DB_FILE = DATA_DIR / "password_reset_tokens.json"
INCIDENTS_DB_FILE = DATA_DIR / "incidents.json"


def _open_db(file_path: Path) -> TinyDB:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return TinyDB(file_path)


def get_tinydb_db() -> TinyDB:
    """Retorna la base TinyDB de proveedores (legado)."""
    return _open_db(SUPPLIERS_DB_FILE)


def get_users_db() -> TinyDB:
    return _open_db(USERS_DB_FILE)


def get_profiles_db() -> TinyDB:
    return _open_db(PROFILES_DB_FILE)


def get_password_reset_tokens_db() -> TinyDB:
    return _open_db(PASSWORD_RESET_TOKENS_DB_FILE)


def get_incidents_db() -> TinyDB:
    return _open_db(INCIDENTS_DB_FILE)


# ---------------------------------------------------------------------------
# Cargar variables de entorno desde .env si no se han cargado ya
# ---------------------------------------------------------------------------

ENV_FILE = BASE_DIR / ".env"


def _load_dotenv() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# ---------------------------------------------------------------------------
# SQLModel — conexión a Supabase (PostgreSQL) — inicialización perezosa
# ---------------------------------------------------------------------------
# El motor se crea bajo demanda, no al importar el módulo. Esto permite que
# security.py (que carga las variables de entorno desde .env) se importe
# antes de que se necesite DATABASE_URL.

_engine = None


def _get_engine():
    """Retorna el motor SQLModel, creándolo la primera vez que se llama."""
    global _engine
    if _engine is None:
        database_url: str = os.getenv("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Define it in services/api/.env "
                "or export it as an environment variable."
            )
        _engine = create_engine(database_url, echo=False)
    return _engine


def init_db(*, exclude_tables: set[str] | None = None) -> None:
    """Crea tablas SQLModel; migration-owned tables can be explicitly excluded."""
    tables = [
        table for table in SQLModel.metadata.sorted_tables
        if table.name not in (exclude_tables or set())
    ]
    SQLModel.metadata.create_all(_get_engine(), tables=tables)


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI que provee una sesión SQLModel por petición.

    Se usa con Depends(get_db) en los endpoints. La sesión se cierra
    automáticamente al finalizar la petición gracias al generador con yield.
    """
    with Session(_get_engine()) as session:
        yield session
