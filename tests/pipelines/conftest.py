"""pytest configuration for RFP pipeline tests.

Sets up a SQLite in-memory database for testing to avoid requiring a real
PostgreSQL/Supabase connection. All tables are created before tests and
dropped after.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure paths before any imports
ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
for p in (str(ROOT), str(API_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Set DATABASE_URL to SQLite in-memory BEFORE any model imports
os.environ.setdefault("DATABASE_URL", "sqlite:///test_rfp.db")

import pytest


@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    """Create all tables in the test SQLite database before test session."""
    from sqlmodel import SQLModel
    from database import _get_engine

    engine = _get_engine()
    # Create all tables
    SQLModel.metadata.create_all(engine)
    yield
    # Clean up
    try:
        db_path = Path(ROOT / "test_rfp.db")
        if db_path.exists():
            db_path.unlink()
    except Exception:
        pass