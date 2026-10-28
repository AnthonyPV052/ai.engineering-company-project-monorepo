from __future__ import annotations

from pathlib import Path
from tinydb import TinyDB

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "suppliers.json"


def get_db() -> TinyDB:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return TinyDB(DB_PATH)
